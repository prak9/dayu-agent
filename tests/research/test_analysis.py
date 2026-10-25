"""候选稿、财报覆盖和跨 Run 恢复的行为验证。"""

from dataclasses import replace
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pytest

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.cancellation import CancellationToken
from alpha.contracts.protocols import ToolExecutionContext
from alpha.contracts.research import CreateResearchRequest, ResearchConflictError, SubmitResearchTurnRequest
from alpha.contracts.research_financials import FinancialRequirement, decode_financial_requirements, encode_financial_requirements
from alpha.contracts.research_working import ResearchReportContent, ResearchWorkScope
from alpha.engine.tool_registry import ToolRegistry
from alpha.research.analysis_tools import register_analysis_tools
from alpha.research.candidates import ResearchCandidates, patch_json
from alpha.research.methods.resources import read_packaged_method_files
from alpha.research.storage.analysis import SQLiteResearchAnalysis
from alpha.research.storage.catalog import SQLiteResearchCatalog
from alpha.research.storage.methods import FsResearchMethodStore
from alpha.research.storage.store import ResearchStore
from alpha.research.storage.turns import SQLiteResearchTurns
from alpha.research.storage.working import SQLiteResearchWorkingRecords
from tests.research.factories import research_turn_preparation

_CUTOFF = datetime(2026, 10, 25, tzinfo=timezone.utc)


def _setup(tmp_path: Path, *, financial: bool = False) -> tuple[ResearchStore, ResearchCandidates, ResearchWorkScope]:
    """装配真实仓储。参数：目录、是否强制财报。返回：库、服务、作用域。异常：装配失败。"""
    store = ResearchStore(tmp_path / "research.db")
    methods = FsResearchMethodStore(tmp_path / "methods")
    bundle = methods.pin(read_packaged_method_files())
    research = SQLiteResearchCatalog(store).create(CreateResearchRequest("owner", "create", "研究", as_of=_CUTOFF))
    turns = SQLiteResearchTurns(store)
    requirement = (FinancialRequirement("BABA", ("fil_annual",)),) if financial else ()
    turn = turns.enqueue(SubmitResearchTurnRequest(research.research_id, "owner", "turn", "研究", financial_requirements=requirement),
                         replace(research_turn_preparation(), method_hash=bundle.method_hash))
    turns.claim_next(research.research_id, "owner")
    turns.mark_submitted(turn.turn_id, "run")
    working = SQLiteResearchWorkingRecords(store)
    return store, ResearchCandidates(SQLiteResearchAnalysis(store), working, methods), working.scope_for_run("run")


def _receipt(kind: str, *, empty: bool = False, future: bool = False) -> dict[str, JsonValue]:
    """构造端口实际读取的确定结果。参数：报表、空值、未来来源。返回：读取记录。异常：无。"""
    return {"ticker": "BABA", "document_id": "fil_annual", "statement_type": kind,
            "snapshot": {"source_hash": "source", "processed_hash": "processed", "source_meta": {"filing_date": "2027-01-01" if future else "2026-05-20"}},
            "result": {"periods": [{"period_end": "2026-03-31"}], "rows": [{"values": [] if empty else [100]}], "currency": "CNY", "units": "RMB millions"}}


def test_requirements_are_pinned_and_part_of_request_identity(tmp_path: Path) -> None:
    """修改同键的财报要求必须冲突。参数：目录。返回：无。异常：断言失败。"""
    store, candidates, scope = _setup(tmp_path, financial=True)
    requirement = candidates.analysis.requirements(scope)
    assert decode_financial_requirements(encode_financial_requirements(requirement)) == requirement
    turn = SQLiteResearchTurns(store).get(scope.turn_id, "owner")
    assert turn.financial_requirements == requirement
    with pytest.raises(ResearchConflictError):
        SQLiteResearchTurns(store).find(SubmitResearchTurnRequest(scope.research_id, "owner", "turn", "研究", financial_requirements=(FinancialRequirement("OTHER"),)))


@pytest.mark.parametrize("value", [None, {}, [1], [{"ticker": 1}], [{"ticker": "A", "document_ids": [2], "statement_types": [], "minimum_periods": 1}]])
def test_invalid_requirements_are_rejected(value: JsonValue) -> None:
    """损坏契约不能静默降级。参数：JSON。返回：无。异常：断言失败。"""
    with pytest.raises(ValueError):
        decode_financial_requirements(value)


@pytest.mark.parametrize("requirement", [lambda: FinancialRequirement(""), lambda: FinancialRequirement("A", minimum_periods=0),
                                          lambda: FinancialRequirement("A", statement_types=("other",)), lambda: FinancialRequirement("A", ("",))])
def test_invalid_requirement_values(requirement: Callable[[], FinancialRequirement]) -> None:
    """非法覆盖值必须拒绝。参数：构造器。返回：无。异常：断言失败。"""
    with pytest.raises(ValueError):
        requirement()


def test_empty_or_future_financial_reads_cannot_complete(tmp_path: Path) -> None:
    """有读取调用但没有数值也不能完成研究。参数：目录。返回：无。异常：断言失败。"""
    _, candidates, scope = _setup(tmp_path, financial=True)
    assert len(candidates.analysis.coverage_errors(scope)) == 3
    candidates.analysis.save_read(scope, "empty", _receipt("income", empty=True))
    candidates.analysis.save_read(scope, "future", _receipt("cash_flow", future=True))
    assert len(candidates.analysis.coverage_errors(scope)) == 3
    with pytest.raises(ValueError, match="financial_coverage_errors"):
        candidates.working.append_report(scope, "report", ResearchReportContent("不得冒充已完成"))
    for kind in ("income", "balance_sheet", "cash_flow"):
        saved = candidates.analysis.save_read(scope, kind, _receipt(kind))
        assert saved["receipt_id"]
    assert candidates.analysis.coverage_errors(scope) == []
    with pytest.raises(ValueError, match="数据核验契约"):
        candidates.working.append_report(scope, "report", ResearchReportContent("仍缺数据契约"))


def test_precise_errors_patch_hash_commit_and_immutability(tmp_path: Path) -> None:
    """修复一个时间字段无需重传大稿。参数：目录。返回：无。异常：断言失败。"""
    _, candidates, scope = _setup(tmp_path)
    body: dict[str, JsonValue] = {"report_markdown": "# 结论", "evidence": [{"evidence_id": "e1", "source_ref": "https://example.com",
        "document_type": "20-F", "excerpt": "原文", "classification": "reported_fact", "accessed_at": _CUTOFF.isoformat(),
        "published_at": {"earliest": "2026-01-01"}}]}
    original = candidates.analysis.save_candidate(scope, "draft", body)
    candidate_id = str(original["candidate_id"])
    context = ToolExecutionContext(run_id=scope.run_id, tool_call_id="validate")
    invalid = candidates.validate(scope, candidate_id, context)
    assert invalid["valid"] is False and "/evidence/0/published_at" in str(invalid["errors"])
    assert candidates.commit(scope, candidate_id, str(original["content_hash"]), "invalid-commit", context)["valid"] is False
    patched = patch_json(body, "/evidence/0/published_at", "2026-05-20T00:00:00+00:00")
    updated = candidates.analysis.save_candidate(scope, "patch", patched)
    assert original["body"] == body and updated["content_hash"] != original["content_hash"]
    with pytest.raises(ValueError, match="hash"):
        candidates.commit(scope, str(updated["candidate_id"]), "wrong", "commit", context)
    submitted = candidates.commit(scope, str(updated["candidate_id"]), str(updated["content_hash"]), "commit", context)
    assert submitted["submitted"] is True
    assert candidates.working.latest_report(scope) is not None
    assert candidates.analysis.save_candidate(scope, "draft", body) == original
    with pytest.raises(ResearchConflictError):
        candidates.analysis.save_candidate(scope, "draft", patched)


def test_checkpoint_restoration_does_not_erase_sources_or_allow_late_writes(tmp_path: Path) -> None:
    """下一轮可见原稿来源，结束的 Run 无法写入。参数：目录。返回：无。异常：断言失败。"""
    store, candidates, scope = _setup(tmp_path)
    saved = candidates.analysis.save_candidate(scope, "draft", {"report_markdown": "阶段稿"})
    note = candidates.working.append_note(scope, "note", title="阶段", content="来源和推算")
    SQLiteResearchTurns(store).settle(scope.turn_id, scope.run_id)
    with pytest.raises(ResearchConflictError, match="迟到"):
        candidates.analysis.save_candidate(scope, "late", {"report_markdown": "迟到"})
    next_turn = SQLiteResearchTurns(store).enqueue(SubmitResearchTurnRequest(scope.research_id, "owner", "next", "继续"),
                                                   replace(research_turn_preparation(), method_hash=scope.method_hash))
    SQLiteResearchTurns(store).claim_next(scope.research_id, "owner")
    SQLiteResearchTurns(store).mark_submitted(next_turn.turn_id, "next-run")
    next_scope = candidates.working.scope_for_run("next-run")
    restored = candidates.analysis.get_candidate(next_scope, str(saved["candidate_id"]))
    assert restored["source_run_id"] == scope.run_id
    checkpoint_record = candidates.working.read_checkpoint(next_scope, note.record_id)
    assert checkpoint_record["source_run_id"] == scope.run_id and checkpoint_record["as_of"] == scope.as_of.isoformat()
    assert candidates.working.list_checkpoints(next_scope)[0]["record_id"] == note.record_id
    with pytest.raises(KeyError):
        candidates.working.read_checkpoint(next_scope, "other")
    with pytest.raises(ValueError):
        candidates.working.list_checkpoints(next_scope, limit=0)
    with pytest.raises(ResearchConflictError):
        candidates.working.list_checkpoints(replace(next_scope, owner_id="other"))
    checkpoint = candidates.analysis.checkpoints(next_scope)[0]
    assert isinstance(checkpoint, dict) and checkpoint["as_of"] == scope.as_of.isoformat()
    with pytest.raises(KeyError):
        candidates.analysis.get_candidate(next_scope, "not-found")
    with pytest.raises(ResearchConflictError):
        candidates.analysis.checkpoints(replace(next_scope, owner_id="other"))


class _Reader:
    """测试端口保存真实传入参数，不替代研究仓储。"""

    def download(self, ticker: str, form_types: tuple[str, ...], start_date: str | None, end_date: str | None, token: CancellationToken | None) -> dict[str, JsonValue]:
        """返回选定下载范围。参数：公司、表单、日期、取消。返回：范围。异常：无。"""
        return {"ticker": ticker, "form_types": list(form_types)}

    def prepare(self, ticker: str, document_id: str, token: CancellationToken | None) -> dict[str, JsonValue]:
        """返回处理身份。参数：公司、文档、取消。返回：身份。异常：无。"""
        return {"ticker": ticker, "document_id": document_id}

    def read(self, ticker: str, document_id: str, *, statement_type: str | None, table_ref: str | None, token: CancellationToken | None) -> dict[str, JsonValue]:
        """返回确定读取。参数：公司、文档、定位、取消。返回：实际结果。异常：无。"""
        return {**_receipt(statement_type or "table"), "ticker": ticker, "document_id": document_id, "table_ref": table_ref}


def test_tools_expose_one_shared_candidate_and_financial_journey(tmp_path: Path) -> None:
    """公开工具完成保存、修订、校验、提交和财报读取。参数：目录。返回：无。异常：断言失败。"""
    _, candidates, _ = _setup(tmp_path)
    registry = ToolRegistry()
    assert register_analysis_tools(registry, candidates, _Reader()) == 9
    context = ToolExecutionContext(run_id="run", tool_call_id="draft")
    draft = registry.execute("research_draft_report", {"report_markdown": "原稿"}, context)["value"]
    patch = registry.execute("research_patch_candidate", {"candidate_id": draft["candidate_id"], "path": "/report_markdown", "value": "修订"}, replace(context, tool_call_id="patch"))["value"]
    assert registry.execute("research_validate_candidate", {"candidate_id": patch["candidate_id"]}, context)["value"]["valid"] is True
    assert registry.execute("research_commit_candidate", {"candidate_id": patch["candidate_id"], "content_hash": patch["content_hash"]}, replace(context, tool_call_id="commit"))["value"]["submitted"] is True
    assert registry.execute("research_checkpoints", {}, context)["value"]["checkpoints"]
    assert registry.execute("research_read_checkpoint", {"candidate_id": draft["candidate_id"]}, context)["value"]["content"]
    assert registry.execute("research_read_checkpoint", {}, context)["ok"] is False
    record = candidates.working.append_note(candidates.working.scope_for_run("run"), "note", title="阶段", content="记录")
    assert registry.execute("research_read_checkpoint", {"record_id": record.record_id}, context)["value"]["content"]
    assert registry.execute("research_prepare_source", {"ticker": "BABA", "document_id": "fil_annual"}, context)["ok"] is True
    assert registry.execute("research_download_filings", {"ticker": "BABA", "form_types": ["20-F", "6-K"]}, context)["value"]["form_types"] == ["20-F", "6-K"]
    assert registry.execute("research_read_financial", {"ticker": "BABA", "document_id": "fil_annual", "statement_type": "income"}, replace(context, tool_call_id="read"))["value"]["receipt_id"]


def test_candidate_tools_accept_full_report_and_nested_data_contract(tmp_path: Path) -> None:
    """实际注册边界允许长报告及嵌套契约，字段错误留待校验。参数：目录。返回：无。异常：断言失败。"""
    _, candidates, _ = _setup(tmp_path)
    registry = ToolRegistry()
    register_analysis_tools(registry, candidates, _Reader())
    context = ToolExecutionContext(run_id="run", tool_call_id="full-draft")
    report = "财务证据与判断。" * 1000
    contract: dict[str, JsonValue] = {"schema_version": 2, "metrics": [{"id": "revenue", "value": 100}], "checks": {"sums": []}}
    saved = registry.execute("research_draft_report", {"report_markdown": report, "data_contract": contract}, context)
    assert saved["ok"] is True, saved
    candidate = saved["value"]
    assert isinstance(candidate, dict)
    patched = registry.execute("research_patch_candidate", {"candidate_id": candidate["candidate_id"], "path": "/report_markdown", "value": report + "补充"}, replace(context, tool_call_id="full-patch"))
    assert patched["ok"] is True, patched


@pytest.mark.parametrize("path", ["", "/", "/missing/field", "/items/text", "/items/4"])
def test_invalid_patch_paths(path: str) -> None:
    """错误路径不能修订其他位置。参数：路径。返回：无。异常：断言失败。"""
    with pytest.raises((ValueError, KeyError)):
        patch_json({"items": [1]}, path, 2)


def _valid_contract() -> dict[str, JsonValue]:
    """构造可复核的数据口径。参数：无。返回：契约。异常：无。"""
    return {"schema_version": 1, "decision_time": _CUTOFF.isoformat(), "metrics": [{
        "id": "revenue", "name": "Revenue", "value": 100, "unit": "CNY million", "currency": "CNY", "period": "FY2026", "basis": "GAAP",
        "classification": "reported_fact", "missing_reason": None, "source": {"reference": "https://example.com/annual", "document_type": "20-F",
        "published_at": "2026-05-20T00:00:00+00:00", "available_at": "2026-05-20T00:00:00+00:00", "locator": "income"}}]}


def test_financial_candidate_requires_contract_and_validates_calculation_errors(tmp_path: Path) -> None:
    """财报覆盖与计算校验同时通过才可提交。参数：目录。返回：无。异常：断言失败。"""
    _, candidates, scope = _setup(tmp_path, financial=True)
    for kind in ("income", "balance_sheet", "cash_flow"):
        candidates.analysis.save_read(scope, kind, _receipt(kind))
    draft = candidates.analysis.save_candidate(scope, "no-contract", {"report_markdown": "结论"})
    context = ToolExecutionContext(run_id=scope.run_id, tool_call_id="validate")
    assert "/data_contract" in str(candidates.validate(scope, str(draft["candidate_id"]), context)["errors"])
    invalid = candidates.analysis.save_candidate(scope, "invalid-contract", {"report_markdown": "结论", "data_contract": {"metrics": []}})
    assert "/data_contract/metrics" in str(candidates.validate(scope, str(invalid["candidate_id"]), replace(context, tool_call_id="invalid-contract"))["errors"])
    wrong_type = candidates.analysis.save_candidate(scope, "type", {"report_markdown": "结论", "data_contract": []})
    assert candidates.validate(scope, str(wrong_type["candidate_id"]), replace(context, tool_call_id="wrong-type"))["valid"] is False
    valid = candidates.analysis.save_candidate(scope, "valid", {"report_markdown": "结论", "data_contract": _valid_contract()})
    assert candidates.commit(scope, str(valid["candidate_id"]), str(valid["content_hash"]), "commit", context)["submitted"] is True


@pytest.mark.parametrize("evidence", [[1], {}, [{"evidence_id": ""}], [{"evidence_id": "same", "source_ref": "ref", "document_type": "20-F",
        "excerpt": "原文", "classification": "not-supported", "accessed_at": "2026-01-01T00:00:00+00:00"}],
        [{"evidence_id": "future", "source_ref": "ref", "document_type": "20-F", "excerpt": "原文", "classification": "reported_fact",
          "accessed_at": "2026-01-01T00:00:00", "published_at": "2027-01-01T00:00:00+00:00"}]])
def test_all_evidence_errors_are_repairable_field_results(tmp_path: Path, evidence: JsonValue) -> None:
    """证据格式与时间错误不消耗模型失败重试。参数：目录、错误证据。返回：无。异常：断言失败。"""
    _, candidates, scope = _setup(tmp_path)
    saved = candidates.analysis.save_candidate(scope, "draft", {"report_markdown": "报告", "evidence": evidence})
    checked = candidates.validate(scope, str(saved["candidate_id"]), ToolExecutionContext())
    assert checked["valid"] is False and checked["errors"]


def test_patch_list_and_invalid_intermediate_scalar() -> None:
    """局部修订支持数组元素，拒绝标量内部路径。参数：无。返回：无。异常：断言失败。"""
    assert patch_json({"items": [1]}, "/items/0", 2) == {"items": [2]}
    with pytest.raises(ValueError):
        patch_json({"item": 1}, "/item/inside/value", None)
