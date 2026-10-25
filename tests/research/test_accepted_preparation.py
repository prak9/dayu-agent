"""首次接受的研究方法、模型及显式选项的持久性测试。"""

from dataclasses import replace
from pathlib import Path

import pytest

from alpha.contracts.agent_execution import AcceptedExecutionSpec, AcceptedModelSpec
from alpha.contracts.execution_options import ExecutionOptions
from alpha.contracts.research import CreateResearchRequest, ResearchConflictError, SubmitResearchTurnRequest
from alpha.research.storage.catalog import SQLiteResearchCatalog
from alpha.research.storage.store import ResearchStore
from alpha.research.storage.turns import SQLiteResearchTurns
from tests.research.factories import research_turn_preparation


def test_first_preparation_is_pinned_across_restart_and_current_config_change(tmp_path: Path) -> None:
    """重试不随当前方法或模型配置漂移。参数：目录。返回：无。异常：断言失败。"""
    path = tmp_path / "research.db"
    store = ResearchStore(path)
    research = SQLiteResearchCatalog(store).create(CreateResearchRequest("owner", "create", "研究"))
    turns = SQLiteResearchTurns(store)
    request = SubmitResearchTurnRequest(research.research_id, "owner", "turn", "问题")
    preparation = research_turn_preparation()
    assert turns.find(request) is None
    first = turns.enqueue(request, preparation)
    assert turns.find(request) == first
    with pytest.raises(ResearchConflictError):
        turns.find(replace(request, user_text="同键改变内容"))
    changed = replace(preparation, method_hash="1" * 64, accepted_spec=AcceptedExecutionSpec(AcceptedModelSpec("new-model")))
    assert turns.enqueue(request, changed) == first
    assert SQLiteResearchTurns(ResearchStore(path)).get(first.turn_id, "owner").preparation == preparation


def test_explicit_execution_options_are_replayed_and_part_of_request_identity(tmp_path: Path) -> None:
    """同键修改显式模型被拒绝，原选项可回读。参数：目录。返回：无。异常：断言失败。"""
    store = ResearchStore(tmp_path / "research.db")
    research = SQLiteResearchCatalog(store).create(CreateResearchRequest("owner", "create", "研究"))
    turns = SQLiteResearchTurns(store)
    request = SubmitResearchTurnRequest(research.research_id, "owner", "turn", "问题", execution_options=ExecutionOptions(model_name="test-model"))
    first = turns.enqueue(request, research_turn_preparation())
    assert turns.get(first.turn_id, "owner").execution_options == request.execution_options
    with pytest.raises(ResearchConflictError):
        turns.enqueue(replace(request, execution_options=ExecutionOptions(model_name="different-model")), research_turn_preparation())


def test_invalid_preparation_is_not_accepted(tmp_path: Path) -> None:
    """无效方法或模型不会留下可派发输入。参数：目录。返回：无。异常：断言失败。"""
    store = ResearchStore(tmp_path / "research.db")
    research = SQLiteResearchCatalog(store).create(CreateResearchRequest("owner", "create", "研究"))
    turns = SQLiteResearchTurns(store)
    request = SubmitResearchTurnRequest(research.research_id, "owner", "turn", "问题")
    for invalid in (replace(research_turn_preparation(), method_hash="invalid"),
                    replace(research_turn_preparation(), accepted_spec=AcceptedExecutionSpec(AcceptedModelSpec("")))):
        with pytest.raises(ValueError):
            turns.enqueue(request, invalid)
    assert turns.claim_next(research.research_id, "owner") is None


@pytest.mark.parametrize("field,value", [("accepted_spec_json", "[]"), ("execution_options_json", "[]")])
def test_corrupt_pinned_preparation_does_not_fallback(tmp_path: Path, field: str, value: str) -> None:
    """损坏原规格不以新配置兜底。参数：目录、字段、内容。返回：无。异常：断言失败。"""
    store = ResearchStore(tmp_path / "research.db")
    research = SQLiteResearchCatalog(store).create(CreateResearchRequest("owner", "create", "研究"))
    turns = SQLiteResearchTurns(store)
    turn = turns.enqueue(SubmitResearchTurnRequest(research.research_id, "owner", "turn", "问题"), research_turn_preparation())
    with store.connection(write=True) as conn:
        conn.execute(f"UPDATE research_turns SET {field}=? WHERE turn_id=?", (value, turn.turn_id))
    with pytest.raises(ValueError, match="损坏"):
        turns.get(turn.turn_id, "owner")
