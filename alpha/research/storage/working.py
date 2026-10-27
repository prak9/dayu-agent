"""研究工作笔记、计算与草稿的原子日志；身份从持久受理的 Run 关联解析。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research import ResearchConflictError, ResearchTurnState
from alpha.contracts.research_working import ResearchReportContent, ResearchWorkingKind, ResearchWorkingRecord, ResearchWorkScope
from alpha.research.evidence import decode_research_evidence, encode_research_evidence
from alpha.research.storage.encoding import canonical_json, content_hash, encode_time, utc_now
from alpha.research.storage.store import ResearchStore
from alpha.research.storage.scope import scope_for_run
from alpha.research.storage.analysis import SQLiteResearchAnalysis

_MAX_RECORD_BYTES = 20 * 1024 * 1024
_MAX_PAGE_RECORDS = 50


def _record_content(
    *, research_id: str, turn_id: str, run_id: str, tool_call_id: str, sequence: int,
    kind: ResearchWorkingKind, body_json: str, created_at: str,
) -> str:
    """编码记录完整性视图。参数：来源、顺序、类别、正文及时间。返回：规范 JSON。异常：非法数值。"""
    return canonical_json({"research_id": research_id, "turn_id": turn_id, "run_id": run_id,
                           "tool_call_id": tool_call_id, "sequence": sequence, "kind": kind.value,
                           "body_json": body_json, "created_at": created_at})


def _from_row(row: sqlite3.Row) -> ResearchWorkingRecord:
    """核验并投影记录。参数：数据行。返回：工作记录。异常：完整性损坏时冲突。"""
    kind = ResearchWorkingKind(str(row["kind"]))
    encoded = _record_content(research_id=str(row["research_id"]), turn_id=str(row["turn_id"]), run_id=str(row["source_run_id"]),
                              tool_call_id=str(row["tool_call_id"]), sequence=int(row["sequence"]), kind=kind,
                              body_json=str(row["body_json"]), created_at=str(row["created_at"]))
    if content_hash(encoded) != str(row["content_hash"]):
        raise ResearchConflictError("研究工作记录校验失败")
    return ResearchWorkingRecord(str(row["record_id"]), str(row["source_run_id"]), str(row["tool_call_id"]),
                                 int(row["sequence"]), kind, str(row["body_json"]), str(row["content_hash"]),
                                 datetime.fromisoformat(str(row["created_at"])))


class SQLiteResearchWorkingRecords:
    """一条工具调用至多一个工作记录，重放保留原顺序；旧草稿重放不覆盖新草稿。"""

    def __init__(self, store: ResearchStore) -> None:
        """注入存储。参数：store 研究库。返回：无。异常：无。"""
        self._store = store

    def scope_for_run(self, run_id: str) -> ResearchWorkScope:
        """解析可信 Run 上下文。参数：Run。返回：研究作用域。异常：未关联。"""
        with self._store.connection() as conn:
            return scope_for_run(conn, run_id)

    def append_note(self, scope: ResearchWorkScope, tool_call_id: str, *, title: str, content: str) -> ResearchWorkingRecord:
        """保存笔记。参数：作用域、调用 ID、标题、正文。返回：不可变记录。异常：空内容或来源冲突。"""
        if not title.strip() or not content.strip():
            raise ValueError("研究笔记标题和正文不能为空")
        return self._append(scope, tool_call_id, ResearchWorkingKind.NOTE, {"title": title, "content": content})

    def append_calculation(
        self, scope: ResearchWorkScope, tool_call_id: str, *, method: str, inputs: dict[str, JsonValue],
        result: dict[str, JsonValue], accepted: bool,
    ) -> ResearchWorkingRecord:
        """保存计算依据及结果。参数：作用域、调用、方法、输入、输出、是否通过。返回：记录。异常：来源冲突。"""
        return self._append(scope, tool_call_id, ResearchWorkingKind.CALCULATION,
                            {"method": method, "inputs": inputs, "result": result, "accepted": accepted})

    def append_report(self, scope: ResearchWorkScope, tool_call_id: str, report: ResearchReportContent) -> ResearchWorkingRecord:
        """保存正式提交前的报告。参数：作用域、调用 ID、内容。返回：记录。异常：空正文、证据或来源非法。"""
        if not report.report_markdown.strip():
            raise ValueError("研究报告不能为空")
        analysis = SQLiteResearchAnalysis(self._store)
        coverage = analysis.coverage_errors(scope)
        if coverage:
            raise ValueError(canonical_json({"financial_coverage_errors": coverage}))
        if analysis.requirements(scope) and report.data_contract_json is None:
            raise ValueError("财报研究必须提供数据核验契约")
        contract = None if report.data_contract_json is None else cast(JsonValue, json.loads(report.data_contract_json))
        return self._append(scope, tool_call_id, ResearchWorkingKind.REPORT, {
            "report_markdown": report.report_markdown, "evidence": encode_research_evidence(report.evidence, scope.as_of),
            "data_contract": contract,
        })

    def _append(
        self, scope: ResearchWorkScope, tool_call_id: str, kind: ResearchWorkingKind, body: dict[str, JsonValue],
    ) -> ResearchWorkingRecord:
        """原子追加不可变调用记录。参数：作用域、调用、类别、显式正文。返回：记录。异常：冲突、超限或输入已结束。"""
        if not tool_call_id.strip():
            raise ValueError("工具调用 ID 不能为空")
        body_json = canonical_json(body)
        if len(body_json.encode("utf-8")) > _MAX_RECORD_BYTES:
            raise ValueError("研究工作记录超过 20 MiB 限制")
        with self._store.connection(write=True) as conn:
            if scope_for_run(conn, scope.run_id) != scope:
                raise ResearchConflictError("研究工作作用域与受理不匹配")
            existing = conn.execute("SELECT * FROM research_working_records WHERE source_run_id=? AND tool_call_id=?",
                                    (scope.run_id, tool_call_id)).fetchone()
            if existing is not None:
                record = _from_row(existing)
                if record.kind != kind or record.body_json != body_json:
                    raise ResearchConflictError("同一工具调用的工作记录内容发生变化")
                return record
            turn = conn.execute("SELECT state FROM research_turns WHERE turn_id=?", (scope.turn_id,)).fetchone()
            if str(turn["state"]) != ResearchTurnState.SUBMITTED.value:
                raise ResearchConflictError("输入已结束，拒绝迟到的工作记录")
            sequence = int(conn.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM research_working_records WHERE turn_id=?",
                                        (scope.turn_id,)).fetchone()[0])
            record_id = "record_" + uuid5(NAMESPACE_URL, f"alpha:{scope.run_id}:{tool_call_id}").hex
            created_at = encode_time(utc_now())
            assert created_at is not None
            encoded = _record_content(research_id=scope.research_id, turn_id=scope.turn_id, run_id=scope.run_id,
                                      tool_call_id=tool_call_id, sequence=sequence, kind=kind, body_json=body_json, created_at=created_at)
            conn.execute("INSERT INTO research_working_records VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (record_id, scope.research_id, scope.turn_id, scope.run_id, tool_call_id, sequence,
                          kind.value, body_json, content_hash(encoded), created_at))
            return _from_row(conn.execute("SELECT * FROM research_working_records WHERE record_id=?", (record_id,)).fetchone())

    def list_records(self, scope: ResearchWorkScope, *, after_sequence: int = 0, limit: int = 20) -> list[ResearchWorkingRecord]:
        """列出当前输入的工作记录。参数：作用域、序号游标、数量。返回：升序记录。异常：范围或作用域非法。"""
        if after_sequence < 0 or not 1 <= limit <= _MAX_PAGE_RECORDS:
            raise ValueError("记录游标或数量非法")
        with self._store.connection() as conn:
            if scope_for_run(conn, scope.run_id) != scope:
                raise ResearchConflictError("研究工作作用域不匹配")
            return [_from_row(row) for row in conn.execute(
                "SELECT * FROM research_working_records WHERE turn_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                (scope.turn_id, after_sequence, limit),
            ).fetchall()]

    def get_record(self, scope: ResearchWorkScope, record_id: str) -> ResearchWorkingRecord:
        """读取作用域内记录。参数：作用域、记录 ID。返回：记录。异常：不存在、越界或损坏。"""
        with self._store.connection() as conn:
            if scope_for_run(conn, scope.run_id) != scope:
                raise ResearchConflictError("研究工作作用域不匹配")
            row = conn.execute("SELECT * FROM research_working_records WHERE turn_id=? AND record_id=?",
                               (scope.turn_id, record_id)).fetchone()
            if row is None:
                raise KeyError("工作记录不属于当前研究输入")
            return _from_row(row)

    def list_named_notes(self, scope: ResearchWorkScope, title: str) -> list[ResearchWorkingRecord]:
        """读取同研究指定类别的历史笔记。参数：作用域、类别标题。返回：经完整性校验的升序事件。异常：越权或损坏。"""
        with self._store.connection() as conn:
            if scope_for_run(conn, scope.run_id) != scope:
                raise ResearchConflictError("研究笔记作用域不匹配")
            rows = conn.execute(
                "SELECT w.* FROM research_working_records w JOIN research_turns t ON t.turn_id=w.turn_id "
                "WHERE t.research_id=? AND t.as_of<=? AND w.kind=? "
                "AND json_extract(w.body_json,'$.title')=? ORDER BY w.created_at,w.record_id",
                (scope.research_id, scope.as_of.isoformat(), ResearchWorkingKind.NOTE.value, title),
            ).fetchall()
            return [_from_row(row) for row in rows]

    def latest_report(self, scope: ResearchWorkScope) -> ResearchReportContent | None:
        """读取当前 Run 最后提交的报告。参数：作用域。返回：报告或空。异常：作用域、完整性或格式损坏。"""
        with self._store.connection() as conn:
            if scope_for_run(conn, scope.run_id) != scope:
                raise ResearchConflictError("研究工作作用域不匹配")
            row = conn.execute("SELECT * FROM research_working_records WHERE turn_id=? AND source_run_id=? AND kind=? "
                               "ORDER BY sequence DESC LIMIT 1", (scope.turn_id, scope.run_id, ResearchWorkingKind.REPORT.value)).fetchone()
            if row is None:
                return None
            record = _from_row(row)
        body = cast(JsonValue, json.loads(record.body_json))
        if not isinstance(body, dict) or not isinstance(body.get("report_markdown"), str):
            raise ResearchConflictError("报告工作记录格式损坏")
        data_contract = body.get("data_contract")
        return ResearchReportContent(str(body["report_markdown"]), decode_research_evidence(body.get("evidence")),
                                     canonical_json(data_contract) if data_contract is not None else None)

    def list_checkpoints(self, scope: ResearchWorkScope, *, limit: int = 20) -> list[dict[str, JsonValue]]:
        """列出同研究且不晚于本轮截止的工作记录。参数：作用域、数量。返回：来源索引。异常：范围或来源冲突。"""
        if not 1 <= limit <= _MAX_PAGE_RECORDS:
            raise ValueError("检查点数量超出范围")
        with self._store.connection() as conn:
            if scope_for_run(conn, scope.run_id) != scope:
                raise ResearchConflictError("研究检查点作用域不匹配")
            rows = conn.execute("SELECT w.*,t.as_of,t.method_hash FROM research_working_records w JOIN research_turns t ON t.turn_id=w.turn_id "
                                "WHERE t.research_id=? AND t.as_of<=? ORDER BY w.created_at DESC LIMIT ?", (scope.research_id, scope.as_of.isoformat(), limit)).fetchall()
            return [_checkpoint(row, include_body=False) for row in rows]

    def read_checkpoint(self, scope: ResearchWorkScope, record_id: str) -> dict[str, JsonValue]:
        """读取历史完整记录，不改变原来源。参数：作用域、记录。返回：正文、截止、方法。异常：越界或完整性失败。"""
        with self._store.connection() as conn:
            if scope_for_run(conn, scope.run_id) != scope:
                raise ResearchConflictError("研究检查点作用域不匹配")
            row = conn.execute("SELECT w.*,t.as_of,t.method_hash FROM research_working_records w JOIN research_turns t ON t.turn_id=w.turn_id "
                               "WHERE w.record_id=? AND t.research_id=? AND t.as_of<=?", (record_id, scope.research_id, scope.as_of.isoformat())).fetchone()
            if row is None:
                raise KeyError("工作检查点不属于当前研究的信息集合")
            return _checkpoint(row, include_body=True)


def _checkpoint(row: sqlite3.Row, *, include_body: bool) -> dict[str, JsonValue]:
    """投影已校验的恢复记录。参数：行、是否含正文。返回：来源与可选正文。异常：完整性失败。"""
    record = _from_row(row)
    result: dict[str, JsonValue] = {"record_id": record.record_id, "source_turn_id": str(row["turn_id"]),
        "source_run_id": record.source_run_id, "as_of": str(row["as_of"]), "method_hash": str(row["method_hash"]), "kind": record.kind.value}
    if include_body:
        result["body_json"] = record.body_json
    return result
