"""不可变候选稿与真实财报读取记录；所有写入受当前研究输入约束。"""

import json
import sqlite3
from datetime import datetime
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research import ResearchConflictError, ResearchTurnState
from alpha.contracts.research_financials import FinancialRequirement, decode_financial_requirements
from alpha.contracts.research_working import ResearchWorkScope
from alpha.research.storage.encoding import canonical_json, content_hash, utc_now
from alpha.research.storage.store import ResearchStore
from alpha.research.storage.scope import scope_for_run

_MAX_BODY_BYTES = 20 * 1024 * 1024
_CANDIDATE_TABLE = "research_candidates"
_READ_TABLE = "research_financial_reads"
_HISTORY_LIMIT = 50
_VALIDATION_HISTORY_LIMIT = 5


def _require_scope(conn: sqlite3.Connection, scope: ResearchWorkScope, *, writable: bool) -> None:
    """核验来源与迟到写入。参数：连接、作用域、是否写入。返回：无。异常：冲突。"""
    if scope_for_run(conn, scope.run_id) != scope:
        raise ResearchConflictError("分析作用域与受理不一致")
    if writable:
        row = conn.execute("SELECT state,run_id FROM research_turns WHERE turn_id=?", (scope.turn_id,)).fetchone()
        if str(row["state"]) != ResearchTurnState.SUBMITTED.value or str(row["run_id"]) != scope.run_id:
            raise ResearchConflictError("原执行已结束，拒绝迟到提交")


def _body(row: sqlite3.Row) -> dict[str, JsonValue]:
    """校验不可变正文。参数：行。返回：JSON 对象。异常：完整性损坏。"""
    encoded = str(row["body_json"])
    value = cast(JsonValue, json.loads(encoded))
    if content_hash(encoded) != str(row["content_hash"]) or not isinstance(value, dict):
        raise ResearchConflictError("分析记录已损坏")
    return value


def _candidate(row: sqlite3.Row) -> dict[str, JsonValue]:
    """投影候选稿及完整来源。参数：行。返回：候选稿。异常：完整性损坏。"""
    return {"candidate_id": str(row["candidate_id"]), "content_hash": str(row["content_hash"]),
            "source_turn_id": str(row["turn_id"]), "source_run_id": str(row["source_run_id"]),
            "created_at": str(row["created_at"]), "body": _body(row)}


def _usable_periods(result: dict[str, JsonValue]) -> int:
    """统计有数值的期间，空行不冒充有效财报。参数：实际结果。返回：有效期间数。异常：无。"""
    periods, rows = result.get("periods"), result.get("rows")
    if not isinstance(periods, list) or not isinstance(rows, list):
        return 0
    populated: set[int] = set()
    for row in rows:
        values = row.get("values") if isinstance(row, dict) else None
        if isinstance(values, list):
            populated.update(index for index, value in enumerate(values) if index < len(periods) and isinstance(value, (int, float)) and not isinstance(value, bool))
    identities: set[str] = set()
    for index in populated:
        period = periods[index]
        if isinstance(period, dict) and isinstance(period.get("period_end"), str):
            identities.add(str(period["period_end"]))
    return len(identities)


def _source_available(value: JsonValue, as_of: datetime) -> bool:
    """不把仅有日期的来源假定为当天零点公开。参数：公开日期或时间、截止。返回：能否确认已可用。异常：无。"""
    if not isinstance(value, str):
        return False
    try:
        if len(value) == len("YYYY-MM-DD"):
            return datetime.fromisoformat(value).date() < as_of.date()
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return timestamp.tzinfo is not None and timestamp <= as_of
    except ValueError:
        return False


class SQLiteResearchAnalysis:
    """保存原始候选稿和工具读取快照；读取跨 Run 历史，写入仅限本轮。"""

    def __init__(self, store: ResearchStore) -> None:
        """注入事务基础设施。参数：研究库。返回：无。异常：无。"""
        self._store = store

    def _append(self, scope: ResearchWorkScope, call_id: str, body: dict[str, JsonValue], *, financial: bool) -> sqlite3.Row:
        """原子保存工具结果。参数：作用域、调用、正文、是否读取记录。返回：行。异常：超限或冲突。"""
        if not call_id.strip():
            raise ValueError("调用 ID 不能为空")
        encoded = canonical_json(body)
        if len(encoded.encode()) > _MAX_BODY_BYTES:
            raise ValueError("分析记录超过 20 MiB")
        table = _READ_TABLE if financial else _CANDIDATE_TABLE
        id_column = "receipt_id" if financial else "candidate_id"
        record_id = ("financial_" if financial else "candidate_") + uuid5(NAMESPACE_URL, f"alpha:{scope.run_id}:{call_id}").hex
        with self._store.connection(write=True) as conn:
            _require_scope(conn, scope, writable=True)
            existing = conn.execute(f"SELECT * FROM {table} WHERE {id_column}=?", (record_id,)).fetchone()
            if existing is not None:
                if _body(existing) != body:
                    raise ResearchConflictError("同一分析调用的内容发生变化")
                return existing
            conn.execute(f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?)",
                         (record_id, scope.turn_id, scope.run_id, call_id, content_hash(encoded), encoded, utc_now().isoformat()))
            return conn.execute(f"SELECT * FROM {table} WHERE {id_column}=?", (record_id,)).fetchone()

    def save_candidate(self, scope: ResearchWorkScope, call_id: str, body: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """保存尚未验证的候选稿。参数：作用域、调用、正文。返回：固定 ID/hash。异常：迟到或冲突。"""
        return _candidate(self._append(scope, call_id, body, financial=False))

    def get_candidate(self, scope: ResearchWorkScope, candidate_id: str) -> dict[str, JsonValue]:
        """读取同研究且不晚于截止的候选稿。参数：作用域、ID。返回：稿件及原始来源。异常：越界或损坏。"""
        with self._store.connection() as conn:
            _require_scope(conn, scope, writable=False)
            row = conn.execute("SELECT c.* FROM research_candidates c JOIN research_turns t ON t.turn_id=c.turn_id "
                               "WHERE c.candidate_id=? AND t.research_id=? AND t.as_of<=?",
                               (candidate_id, scope.research_id, scope.as_of.isoformat())).fetchone()
            if row is None:
                raise KeyError("候选稿不存在或不属于当前信息集合")
            candidate = _candidate(row)
            validations: list[JsonValue] = []
            for validation in conn.execute("SELECT v.* FROM research_candidate_validations v JOIN research_turns t ON t.turn_id=v.turn_id "
                    "WHERE v.candidate_id=? AND t.research_id=? AND t.as_of<=? ORDER BY v.created_at DESC LIMIT ?",
                    (candidate_id, scope.research_id, scope.as_of.isoformat(), _VALIDATION_HISTORY_LIMIT)).fetchall():
                encoded = str(validation["result_json"])
                if content_hash(encoded) != str(validation["content_hash"]):
                    raise ResearchConflictError("候选校验报告已损坏")
                validations.append({"source_run_id": str(validation["source_run_id"]), "call_id": str(validation["call_id"]),
                    "created_at": str(validation["created_at"]), "result": cast(JsonValue, json.loads(encoded))})
            candidate["validations"] = validations
            return candidate

    def save_read(self, scope: ResearchWorkScope, call_id: str, body: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """保存服务实际读取的快照。参数：作用域、调用、可信结果。返回：带读取凭据的结果。异常：迟到或冲突。"""
        row = self._append(scope, call_id, body, financial=True)
        return {**_body(row), "receipt_id": str(row["receipt_id"]), "content_hash": str(row["content_hash"])}

    def requirements(self, scope: ResearchWorkScope) -> tuple[FinancialRequirement, ...]:
        """读取受理时固定的要求。参数：作用域。返回：要求。异常：来源冲突。"""
        with self._store.connection() as conn:
            _require_scope(conn, scope, writable=False)
            row = conn.execute("SELECT financial_requirements_json FROM research_turns WHERE turn_id=?", (scope.turn_id,)).fetchone()
            return decode_financial_requirements(cast(JsonValue, json.loads(str(row[0]))))

    def coverage_errors(self, scope: ResearchWorkScope) -> list[JsonValue]:
        """检查每个明确要求是否有实际数值读取。参数：作用域。返回：字段级缺口。异常：记录损坏。"""
        with self._store.connection() as conn:
            _require_scope(conn, scope, writable=False)
            reads = [_body(row) for row in conn.execute("SELECT * FROM research_financial_reads WHERE turn_id=?", (scope.turn_id,)).fetchall()]
        errors: list[JsonValue] = []
        for requirement in self.requirements(scope):
            for document_id in requirement.document_ids or (None,):
                for kind in requirement.statement_types:
                    matched = False
                    for read in reads:
                        result, snapshot = read.get("result"), read.get("snapshot")
                        if read.get("ticker") != requirement.ticker or read.get("statement_type") != kind:
                            continue
                        if document_id is not None and read.get("document_id") != document_id:
                            continue
                        if not isinstance(result, dict) or not isinstance(snapshot, dict) or not snapshot.get("source_hash") or not snapshot.get("processed_hash"):
                            continue
                        if not result.get("currency") or not result.get("units"):
                            continue
                        meta = snapshot.get("source_meta")
                        filing_date = meta.get("filing_date") if isinstance(meta, dict) else None
                        if not _source_available(filing_date, scope.as_of):
                            continue
                        if _usable_periods(result) >= requirement.minimum_periods:
                            matched = True
                            break
                    if not matched:
                        errors.append({"path": f"/financial/{requirement.ticker}/{document_id or '*'}/{kind}",
                                       "message": f"缺少截至本轮截止日可用、含至少 {requirement.minimum_periods} 个数值期间的实际财报读取"})
        return errors

    def checkpoints(self, scope: ResearchWorkScope) -> list[JsonValue]:
        """提供跨 Run 的有界恢复索引，不扩大资料截止时间。参数：作用域。返回：索引。异常：来源冲突。"""
        with self._store.connection() as conn:
            _require_scope(conn, scope, writable=False)
            rows = conn.execute("SELECT c.*,t.as_of,t.method_hash FROM research_candidates c JOIN research_turns t ON t.turn_id=c.turn_id "
                                "WHERE t.research_id=? AND t.as_of<=? ORDER BY c.created_at DESC LIMIT ?",
                                (scope.research_id, scope.as_of.isoformat(), _HISTORY_LIMIT)).fetchall()
            return [{"candidate_id": str(row["candidate_id"]), "content_hash": str(row["content_hash"]),
                     "source_run_id": str(row["source_run_id"]), "source_turn_id": str(row["turn_id"]),
                     "as_of": str(row["as_of"]), "method_hash": str(row["method_hash"]), "created_at": str(row["created_at"])} for row in rows]

    def financial_reads(self, scope: ResearchWorkScope) -> list[JsonValue]:
        """列出本轮及原输入恢复前的读取凭据。参数：作用域。返回：来源、定位及内容摘要。异常：作用域或完整性冲突。"""
        with self._store.connection() as conn:
            _require_scope(conn, scope, writable=False)
            result: list[JsonValue] = []
            for row in conn.execute("SELECT * FROM research_financial_reads WHERE turn_id=? ORDER BY created_at", (scope.turn_id,)).fetchall():
                body = _body(row)
                result.append({"receipt_id": str(row["receipt_id"]), "content_hash": str(row["content_hash"]), "source_run_id": str(row["source_run_id"]),
                    "ticker": body.get("ticker"), "document_id": body.get("document_id"), "statement_type": body.get("statement_type"), "table_ref": body.get("table_ref")})
            return result

    def save_validation(self, scope: ResearchWorkScope, call_id: str, candidate_id: str, result: dict[str, JsonValue]) -> None:
        """持久保存完整校验结果并绑定原调用。参数：作用域、调用、候选、结果。返回：无。异常：冲突或迟到。"""
        self.get_candidate(scope, candidate_id)
        encoded = canonical_json(result)
        with self._store.connection(write=True) as conn:
            _require_scope(conn, scope, writable=True)
            existing = conn.execute("SELECT * FROM research_candidate_validations WHERE source_run_id=? AND call_id=?", (scope.run_id, call_id)).fetchone()
            if existing is not None:
                if str(existing["candidate_id"]) != candidate_id or str(existing["result_json"]) != encoded or str(existing["content_hash"]) != content_hash(encoded):
                    raise ResearchConflictError("同一校验调用的候选或结果发生变化")
                return
            conn.execute("INSERT INTO research_candidate_validations VALUES (?,?,?,?,?,?,?)",
                (scope.run_id, call_id, scope.turn_id, candidate_id, content_hash(encoded), encoded, utc_now().isoformat()))
