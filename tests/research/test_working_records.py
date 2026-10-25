"""研究工作日志的工具身份、顺序、隔离、草稿和原子事务测试。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from alpha.contracts.research import CreateResearchRequest, EvidenceClassification, ResearchConflictError, ResearchEvidence, SubmitResearchTurnRequest
from alpha.contracts.research_working import ResearchReportContent, ResearchWorkingKind, ResearchWorkScope
from alpha.research.storage.catalog import SQLiteResearchCatalog
from alpha.research.storage.store import ResearchStore
from alpha.research.storage.turns import SQLiteResearchTurns
from alpha.research.storage.working import SQLiteResearchWorkingRecords
from tests.research.factories import research_turn_preparation


def _ready(tmp_path: Path) -> tuple[ResearchStore, SQLiteResearchWorkingRecords, ResearchWorkScope]:
    """准备已受理输入。参数：目录。返回：库、工作日志及作用域。异常：存储错误。"""
    store = ResearchStore(tmp_path / "research.db")
    research = SQLiteResearchCatalog(store).create(CreateResearchRequest("owner", "create", "研究"))
    turns = SQLiteResearchTurns(store)
    turn = turns.enqueue(SubmitResearchTurnRequest(research.research_id, "owner", "turn", "开始"), research_turn_preparation())
    turns.claim_next(research.research_id, "owner")
    turns.mark_submitted(turn.turn_id, "run")
    records = SQLiteResearchWorkingRecords(store)
    return store, records, records.scope_for_run("run")


def test_note_replay_order_and_changed_call_rejection(tmp_path: Path) -> None:
    """同调用记录不变，重放不占新序号。参数：目录。返回：无。异常：断言失败。"""
    store, records, scope = _ready(tmp_path)
    first = records.append_note(scope, "call1", title="原始问题", content="原始来源与待核验缺口")
    assert records.append_note(scope, "call1", title="原始问题", content="原始来源与待核验缺口") == first
    second = records.append_calculation(scope, "call2", method="validate_data", inputs={"metrics": []}, result={"status": "fail"}, accepted=False)
    assert first.sequence < second.sequence
    assert json.loads(second.body_json)["accepted"] is False
    assert records.list_records(scope, after_sequence=first.sequence) == [second]
    assert records.get_record(scope, first.record_id) == first
    with pytest.raises(ResearchConflictError):
        records.append_note(scope, "call1", title="原始问题", content="修改已接受记录")
    assert SQLiteResearchWorkingRecords(ResearchStore(tmp_path / "research.db")).list_records(scope) == [first, second]
    assert store is not None


def test_older_report_replay_cannot_replace_newer_report(tmp_path: Path) -> None:
    """旧工具调用重试不覆盖后来草稿。参数：目录。返回：无。异常：断言失败。"""
    _, records, scope = _ready(tmp_path)
    assert records.latest_report(scope) is None
    first = records.append_report(scope, "report1", ResearchReportContent("草稿一"))
    second = records.append_report(scope, "report2", ResearchReportContent("草稿二", data_contract_json='{"metrics":[]}'))
    assert records.append_report(scope, "report1", ResearchReportContent("草稿一")) == first
    assert records.latest_report(scope) == ResearchReportContent("草稿二", data_contract_json='{"metrics":[]}')
    assert second.kind == ResearchWorkingKind.REPORT


def test_scope_is_derived_from_run_and_cannot_be_forged(tmp_path: Path) -> None:
    """模型不能指定另一项研究身份写入。参数：目录。返回：无。异常：断言失败。"""
    _, records, scope = _ready(tmp_path)
    with pytest.raises(KeyError):
        records.scope_for_run("unrelated-run")
    forged = replace(scope, research_id="research_" + "1" * 32)
    with pytest.raises(ResearchConflictError):
        records.append_note(forged, "call", title="伪造", content="不允许")
    with pytest.raises(ResearchConflictError):
        records.list_records(forged)
    with pytest.raises(ResearchConflictError):
        records.get_record(forged, "unknown")
    with pytest.raises(ResearchConflictError):
        records.latest_report(forged)
    with pytest.raises(KeyError):
        records.get_record(scope, "another-research-record")


def test_settled_turn_rejects_late_writes_but_confirms_existing_call(tmp_path: Path) -> None:
    """业务输入已结束后只确认已有结果。参数：目录。返回：无。异常：断言失败。"""
    store, records, scope = _ready(tmp_path)
    note = records.append_note(scope, "call1", title="笔记", content="内容")
    SQLiteResearchTurns(store).settle(scope.turn_id, scope.run_id)
    assert records.append_note(scope, "call1", title="笔记", content="内容") == note
    with pytest.raises(ResearchConflictError, match="迟到"):
        records.append_note(scope, "call2", title="笔记", content="新内容")


def test_recovery_run_reads_old_notes_and_does_not_claim_old_report(tmp_path: Path) -> None:
    """恢复 Run 可追溯旧笔记，正式草稿仍需当前 Run 提交。参数：目录。返回：无。异常：断言失败。"""
    store, records, scope = _ready(tmp_path)
    first = records.append_report(scope, "report1", ResearchReportContent("旧 Run 草稿"))
    with store.connection(write=True) as conn:
        conn.execute("UPDATE research_turns SET run_id='recovery-run' WHERE turn_id=?", (scope.turn_id,))
    recovered = records.scope_for_run("recovery-run")
    assert records.get_record(recovered, first.record_id) == first
    assert records.latest_report(recovered) is None
    with pytest.raises(KeyError):
        records.append_note(scope, "late-call", title="旧执行", content="不应写入")


def test_corrupt_latest_report_fails_without_falling_back(tmp_path: Path) -> None:
    """最新草稿损坏时不返回旧内容。参数：目录。返回：无。异常：断言失败。"""
    store, records, scope = _ready(tmp_path)
    records.append_report(scope, "report1", ResearchReportContent("旧草稿"))
    latest = records.append_report(scope, "report2", ResearchReportContent("新草稿"))
    with store.connection(write=True) as conn:
        conn.execute("UPDATE research_working_records SET body_json='{}' WHERE record_id=?", (latest.record_id,))
    with pytest.raises(ResearchConflictError, match="校验"):
        records.latest_report(scope)


def test_insert_failure_rolls_back_record_and_sequence(tmp_path: Path) -> None:
    """写入失败没有半条记录或丢失序号。参数：目录。返回：无。异常：断言失败。"""
    store, records, scope = _ready(tmp_path)
    with store.connection() as conn:
        conn.execute("CREATE TRIGGER reject_record BEFORE INSERT ON research_working_records BEGIN SELECT RAISE(ABORT,'模拟失败'); END")
    with pytest.raises(sqlite3.IntegrityError, match="模拟"):
        records.append_note(scope, "call", title="笔记", content="内容")
    assert records.list_records(scope) == []
    with store.connection() as conn:
        conn.execute("DROP TRIGGER reject_record")
    assert records.append_note(scope, "call", title="笔记", content="内容").sequence == 1


def test_report_evidence_round_trip_and_time_gate(tmp_path: Path) -> None:
    """草稿保留完整证据且排除截止后材料。参数：目录。返回：无。异常：断言失败。"""
    _, records, scope = _ready(tmp_path)
    evidence = ResearchEvidence("e1", "https://example.com/report", "filing", "原文摘录", EvidenceClassification.REPORTED_FACT,
                                datetime.now(timezone.utc), locator="p. 1", time_missing_reason="未提供精确公开时间")
    report = ResearchReportContent("结论与缺口", (evidence,))
    records.append_report(scope, "report", report)
    assert records.latest_report(scope) == report
    with pytest.raises(ValueError, match="晚于"):
        records.append_report(scope, "future", replace(report, evidence=(replace(evidence, available_at=datetime(2099, 1, 1, tzinfo=timezone.utc)),)))


def test_empty_records_and_invalid_pagination_are_rejected(tmp_path: Path) -> None:
    """输入与分页有明确边界。参数：目录。返回：无。异常：断言失败。"""
    _, records, scope = _ready(tmp_path)
    with pytest.raises(ValueError):
        records.append_note(scope, "call", title="", content="内容")
    with pytest.raises(ValueError):
        records.append_note(scope, "", title="标题", content="内容")
    with pytest.raises(ValueError):
        records.append_report(scope, "call", ResearchReportContent(" "))
    with pytest.raises(ValueError):
        records.list_records(scope, limit=0)
    with pytest.raises(ValueError):
        records.list_records(scope, after_sequence=-1)
