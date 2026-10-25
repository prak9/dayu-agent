"""真实工具注册表中的研究作用域、计算失败及报告提交测试。"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from alpha.contracts.cancellation import CancellationToken
from alpha.contracts.protocols import ToolExecutionContext
from alpha.contracts.research import CreateResearchRequest, SubmitResearchTurnRequest
from alpha.contracts.research_working import ResearchWorkingKind, ResearchWorkScope
from alpha.engine.tool_registry import ToolRegistry
from alpha.research.methods.resources import read_packaged_method_files
from alpha.research.storage.catalog import SQLiteResearchCatalog
from alpha.research.storage.methods import FsResearchMethodStore
from alpha.research.storage.store import ResearchStore
from alpha.research.storage.turns import SQLiteResearchTurns
from alpha.research.storage.working import SQLiteResearchWorkingRecords
from alpha.research.storage.artifacts import FsResearchArtifactStore
from alpha.research.storage.revisions import SQLiteResearchRevisions
from alpha.research.tools import register_research_tools
from tests.research.factories import research_turn_preparation


def _registered(tmp_path: Path, *, cutoff: datetime | None = None) -> tuple[ToolRegistry, SQLiteResearchWorkingRecords, ResearchWorkScope]:
    """装配真实工具及作用域。参数：目录、历史截止日。返回：注册表、工作端口、作用域。异常：存储错误。"""
    methods = FsResearchMethodStore(tmp_path / "methods")
    bundle = methods.pin(read_packaged_method_files())
    store = ResearchStore(tmp_path / "research.db")
    research = SQLiteResearchCatalog(store).create(CreateResearchRequest("owner", "create", "研究", as_of=cutoff))
    turns = SQLiteResearchTurns(store)
    turn = turns.enqueue(SubmitResearchTurnRequest(research.research_id, "owner", "turn", "开始"),
                         replace(research_turn_preparation(), method_hash=bundle.method_hash))
    turns.claim_next(research.research_id, "owner")
    turns.mark_submitted(turn.turn_id, "run")
    records = SQLiteResearchWorkingRecords(store)
    registry = ToolRegistry()
    assert register_research_tools(registry, records, methods, SQLiteResearchRevisions(store, FsResearchArtifactStore(tmp_path / "artifacts"))) == 7
    return registry, records, records.scope_for_run("run")


def test_note_list_and_read_follow_host_scope(tmp_path: Path) -> None:
    """工具索引和正文使用 Host 作用域。参数：目录。返回：无。异常：断言失败。"""
    registry, records, scope = _registered(tmp_path)
    note = registry.execute("research_save_note", {"title": "来源", "content": "原文与缺口"}, ToolExecutionContext(run_id="run", tool_call_id="note"))
    assert note["ok"] is True
    listing = registry.execute("research_list_records", {}, ToolExecutionContext(run_id="run", tool_call_id="list"))
    assert listing["ok"] is True and len(listing["value"]["records"]) == 1
    loaded = registry.execute("research_read_record", {"record_id": note["value"]["record_id"]}, ToolExecutionContext(run_id="run", tool_call_id="read"))
    assert loaded["ok"] is True and json.loads(loaded["value"]["body_json"])["content"] == "原文与缺口"
    assert records.list_records(scope)[0].tool_call_id == "note"


def test_missing_and_cancelled_context_do_not_write(tmp_path: Path) -> None:
    """缺少上下文或已经取消均拒绝写入。参数：目录。返回：无。异常：断言失败。"""
    registry, records, scope = _registered(tmp_path)
    arguments = {"title": "笔记", "content": "内容"}
    assert registry.execute("research_save_note", arguments)["ok"] is False
    assert registry.execute("research_save_note", arguments, ToolExecutionContext(run_id="not-owned", tool_call_id="call"))["ok"] is False
    token = CancellationToken()
    token.cancel()
    cancelled = registry.execute("research_save_note", arguments, ToolExecutionContext(run_id="run", tool_call_id="call", cancellation_token=token))
    assert cancelled["error"] == "cancelled"
    assert records.list_records(scope) == []


def test_failed_validator_is_tool_failure_and_findings_are_saved(tmp_path: Path) -> None:
    """退出码零但校验失败时工具不能返回成功。参数：目录。返回：无。异常：断言失败。"""
    registry, records, scope = _registered(tmp_path)
    result = registry.execute("research_calculate", {"method": "validate_data", "data": {"metrics": []}},
                              ToolExecutionContext(run_id="run", tool_call_id="calc"))
    assert result["ok"] is False and result["error"] == "research_calculation_rejected"
    saved = records.list_records(scope)[0]
    assert saved.record_id in result["hint"]
    body = json.loads(saved.body_json)
    assert saved.kind == ResearchWorkingKind.CALCULATION and body["accepted"] is False
    assert body["result"]["status"] == "fail"


def test_successful_calculation_is_reproducible_from_record(tmp_path: Path) -> None:
    """确定计算返回对应日志身份。参数：目录。返回：无。异常：断言失败。"""
    registry, records, scope = _registered(tmp_path)
    result = registry.execute("research_calculate", {"method": "gf_dma", "data": {}}, ToolExecutionContext(run_id="run", tool_call_id="calc"))
    assert result["ok"] is True and result["value"]["aggregate_enabled"] is False
    record = records.get_record(scope, result["value"]["record_id"])
    assert json.loads(record.body_json)["result"]["heuristic_version"] == "gf-dma-v1"


def test_report_submission_and_long_record_truncation(tmp_path: Path) -> None:
    """报告保存并为大记录提供续读。参数：目录。返回：无。异常：断言失败。"""
    registry, records, scope = _registered(tmp_path)
    result = registry.execute("research_submit_report", {"report_markdown": "研究结论与证据缺口"},
                              ToolExecutionContext(run_id="run", tool_call_id="report"))
    assert result["ok"] is True and result["value"]["data_contract_validated"] is False
    report = records.latest_report(scope)
    assert report is not None and report.report_markdown == "研究结论与证据缺口"
    note = records.append_note(scope, "long", title="长记录", content="x" * 8000)
    loaded = registry.execute("research_read_record", {"record_id": note.record_id}, ToolExecutionContext(run_id="run", tool_call_id="read"))
    assert loaded["ok"] is True and loaded.get("truncation")


def test_historical_report_cannot_choose_a_later_validation_cutoff(tmp_path: Path) -> None:
    """模型不能扩大用户的历史信息集合。参数：目录。返回：无。异常：断言失败。"""
    registry, records, scope = _registered(tmp_path, cutoff=datetime(2025, 1, 1, tzinfo=timezone.utc))
    contract = {"schema_version": 1, "as_of": "2027-01-01T00:00:00Z", "decision_time": "2027-01-01T00:00:00Z", "metrics": [{
        "id": "revenue", "name": "Revenue", "value": 100, "unit": "USD million", "currency": "USD", "period": "FY2025", "basis": "GAAP",
        "classification": "reported_fact", "missing_reason": None,
        "source": {"reference": "https://example.com/report", "document_type": "10-K", "published_at": "2026-03-01T00:00:00Z",
                   "available_at": "2026-03-01T00:00:00Z", "locator": "p. 1"},
    }]}
    result = registry.execute("research_submit_report", {"report_markdown": "使用之后才公开的信息", "data_contract": contract},
                              ToolExecutionContext(run_id="run", tool_call_id="report"))
    assert result["ok"] is False and result["error"] == "research_calculation_rejected"
    assert records.latest_report(scope) is None


def test_method_reference_is_pinned_and_cannot_escape(tmp_path: Path) -> None:
    """方法文档按哈希读取且不开放任意文件。参数：目录。返回：无。异常：断言失败。"""
    registry, _, _ = _registered(tmp_path)
    context = ToolExecutionContext(run_id="run", tool_call_id="reference")
    reference = registry.execute("research_read_method", {"path": "skills/writing/SKILL.md"}, context)
    assert reference["ok"] is True and reference["value"]["content"]
    assert registry.execute("research_read_method", {"path": "../secret.md"}, context)["ok"] is False
    assert registry.execute("research_read_method", {"path": "alpha_invest/__main__.py"}, context)["ok"] is False


def test_history_tool_returns_only_current_research_and_handles_long_report(tmp_path: Path) -> None:
    """读取历史正文必须匹配当前研究；大报告由续读承接。参数：目录。返回：无。异常：断言失败。"""
    from alpha.contracts.research import CommitResearchRevisionRequest

    registry, _, scope = _registered(tmp_path)
    context = ToolExecutionContext(run_id="run", tool_call_id="history")
    assert registry.execute("research_read_report", {}, context)["value"]["versions"] == []
    revisions = SQLiteResearchRevisions(ResearchStore(tmp_path / "research.db"), FsResearchArtifactStore(tmp_path / "artifacts"))
    revision = revisions.commit(CommitResearchRevisionRequest(scope.research_id, "owner", scope.turn_id, scope.run_id,
                                                              "结论" * 4000, scope.method_hash))
    loaded = registry.execute("research_read_report", {"revision_id": revision.revision_id}, context)
    assert loaded["ok"] is True and loaded.get("truncation")
    submitted = registry.execute("research_submit_report", {"report_markdown": "报告" * 3000},
                                 ToolExecutionContext(run_id="run", tool_call_id="long-report"))
    assert submitted["ok"] is True
    store = ResearchStore(tmp_path / "research.db")
    other = SQLiteResearchCatalog(store).create(CreateResearchRequest("owner", "other", "另一个问题"))
    turns = SQLiteResearchTurns(store)
    turn = turns.enqueue(SubmitResearchTurnRequest(other.research_id, "owner", "input", "开始"),
                         replace(research_turn_preparation(), method_hash=scope.method_hash))
    turns.claim_next(other.research_id, "owner")
    turns.mark_submitted(turn.turn_id, "other-run")
    foreign = revisions.commit(CommitResearchRevisionRequest(other.research_id, "owner", turn.turn_id, "other-run", "别的报告", scope.method_hash))
    assert registry.execute("research_read_report", {"revision_id": foreign.revision_id}, context)["ok"] is False
