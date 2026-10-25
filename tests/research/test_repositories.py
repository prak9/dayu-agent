"""研究隔离、输入顺序和不可变报告的行为测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from alpha.contracts.research import (
    CreateResearchRequest,
    ResearchConflictError,
    ResearchState,
    ResearchTurnState,
    SubmitResearchTurnRequest,
    CommitResearchRevisionRequest,
)
from alpha.research.storage.artifacts import FsResearchArtifactStore
from alpha.research.storage.catalog import SQLiteResearchCatalog
from alpha.research.storage.revisions import SQLiteResearchRevisions
from alpha.research.storage.store import ResearchStore
from alpha.research.storage.turns import SQLiteResearchTurns
from tests.research.factories import TEST_METHOD_HASH, research_turn_preparation


def test_same_company_can_have_independent_research(tmp_path: Path) -> None:
    """同公司不同问题保持独立。参数：临时目录。返回：无。异常：断言失败。"""
    store = ResearchStore(tmp_path / "research.db")
    catalog = SQLiteResearchCatalog(store)
    first = catalog.create(CreateResearchRequest("owner", "first", "研究商业质量", subjects=("0700.HK",)))
    second = catalog.create(CreateResearchRequest("owner", "second", "研究资本开支", subjects=("0700.HK",)))
    assert first.research_id != second.research_id
    assert first.session_id != second.session_id
    assert len(catalog.list_research("owner")) == 2
    assert catalog.list_research("someone_else") == []
    with pytest.raises(PermissionError):
        catalog.get(first.research_id, "someone_else")
    assert SQLiteResearchCatalog(ResearchStore(tmp_path / "research.db")).get(first.research_id, "owner") == first


def test_creation_is_idempotent_and_rejects_changed_input(tmp_path: Path) -> None:
    """同受理键不创建第二项研究。参数：临时目录。返回：无。异常：断言失败。"""
    catalog = SQLiteResearchCatalog(ResearchStore(tmp_path / "research.db"))
    request = CreateResearchRequest("owner", "update1", "研究现金流")
    first = catalog.create(request)
    assert catalog.create(request) == first
    with pytest.raises(ResearchConflictError):
        catalog.create(CreateResearchRequest("owner", "update1", "研究另一个问题"))


def test_turns_are_fifo_and_duplicate_admission_reuses_cutoff(tmp_path: Path) -> None:
    """队列跨实例串行且重放不改截止时间。参数：临时目录。返回：无。异常：断言失败。"""
    path = tmp_path / "research.db"
    store = ResearchStore(path)
    research = SQLiteResearchCatalog(store).create(CreateResearchRequest("owner", "create", "研究质量"))
    turns = SQLiteResearchTurns(store)
    request = SubmitResearchTurnRequest(research.research_id, "owner", "input1", "先看现金流")
    first = turns.enqueue(request, research_turn_preparation())
    assert turns.enqueue(request, research_turn_preparation()) == first
    second = turns.enqueue(SubmitResearchTurnRequest(research.research_id, "owner", "input2", "再看资本开支"), research_turn_preparation())
    assert second.sequence > first.sequence
    claimed_first = turns.claim_next(research.research_id, "owner")
    assert claimed_first is not None and claimed_first.turn_id == first.turn_id
    assert claimed_first.state == ResearchTurnState.DISPATCHING
    other = SQLiteResearchTurns(ResearchStore(path))
    assert other.claim_next(research.research_id, "owner") is None
    turns.mark_submitted(first.turn_id, "run1")
    assert other.claim_next(research.research_id, "owner") is None
    turns.settle(first.turn_id, "run1")
    claimed = other.claim_next(research.research_id, "owner")
    assert claimed is not None and claimed.turn_id == second.turn_id
    with pytest.raises(ResearchConflictError):
        turns.enqueue(SubmitResearchTurnRequest(research.research_id, "owner", "input1", "修改同一受理键的内容"), research_turn_preparation())


def test_archive_requires_idle_and_reopen_keeps_session(tmp_path: Path) -> None:
    """归档不关闭或替换会话。参数：临时目录。返回：无。异常：断言失败。"""
    store = ResearchStore(tmp_path / "research.db")
    catalog = SQLiteResearchCatalog(store)
    turns = SQLiteResearchTurns(store)
    research = catalog.create(CreateResearchRequest("owner", "create", "研究质量"))
    turns.enqueue(SubmitResearchTurnRequest(research.research_id, "owner", "turn1", "检查证据"), research_turn_preparation())
    with pytest.raises(ResearchConflictError):
        catalog.archive(research.research_id, "owner")
    assert turns.cancel_queued(research.research_id, "owner") == 1
    archived = catalog.archive(research.research_id, "owner")
    assert archived.state == ResearchState.ARCHIVED
    with pytest.raises(ResearchConflictError):
        turns.enqueue(SubmitResearchTurnRequest(research.research_id, "owner", "turn2", "不允许写入"), research_turn_preparation())
    assert catalog.reopen(research.research_id, "owner").session_id == research.session_id


def test_historical_cutoff_and_naive_datetime_rejection(tmp_path: Path) -> None:
    """历史截止时间稳定且拒绝无时区时间。参数：临时目录。返回：无。异常：断言失败。"""
    store = ResearchStore(tmp_path / "research.db")
    cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)
    research = SQLiteResearchCatalog(store).create(CreateResearchRequest("owner", "create", "历史研究", as_of=cutoff))
    turn = SQLiteResearchTurns(store).enqueue(SubmitResearchTurnRequest(research.research_id, "owner", "turn", "核对原始判断"), research_turn_preparation())
    assert turn.as_of == cutoff
    with pytest.raises(ValueError):
        SQLiteResearchCatalog(store).create(CreateResearchRequest("owner", "bad", "历史研究", as_of=datetime(2025, 1, 1)))


def test_revision_is_immutable_and_survives_reopen(tmp_path: Path) -> None:
    """报告提交后不可覆写且可重新读取。参数：临时目录。返回：无。异常：断言失败。"""
    store = ResearchStore(tmp_path / "research.db")
    catalog = SQLiteResearchCatalog(store)
    turns = SQLiteResearchTurns(store)
    artifacts = FsResearchArtifactStore(tmp_path / "artifacts")
    revisions = SQLiteResearchRevisions(store, artifacts)
    research = catalog.create(CreateResearchRequest("owner", "create", "研究质量"))
    turn = turns.enqueue(SubmitResearchTurnRequest(research.research_id, "owner", "turn1", "开始"), research_turn_preparation())
    turns.claim_next(research.research_id, "owner")
    turns.mark_submitted(turn.turn_id, "run1")
    request = CommitResearchRevisionRequest(research.research_id, "owner", turn.turn_id, "run1", "# 判断\n\n证据不足，保留缺口。", TEST_METHOD_HASH)
    first = revisions.commit(request)
    assert revisions.commit(request) == first
    assert revisions.read_report(first.revision_id, "owner") == request.report_markdown
    assert revisions.list_revisions(research.research_id, "owner") == [first]
    with pytest.raises(ResearchConflictError):
        revisions.commit(CommitResearchRevisionRequest(research.research_id, "owner", turn.turn_id, "run1", "偷偷修改", TEST_METHOD_HASH))
    assert SQLiteResearchRevisions(ResearchStore(tmp_path / "research.db"), artifacts).read_report(first.revision_id, "owner") == request.report_markdown


def test_corrupt_artifact_does_not_fallback_to_older_report(tmp_path: Path) -> None:
    """已引用报告损坏时明确失败。参数：临时目录。返回：无。异常：断言失败。"""
    store = ResearchStore(tmp_path / "research.db")
    artifacts = FsResearchArtifactStore(tmp_path / "artifacts")
    revisions = SQLiteResearchRevisions(store, artifacts)
    research = SQLiteResearchCatalog(store).create(CreateResearchRequest("owner", "create", "研究质量"))
    turns = SQLiteResearchTurns(store)
    turn = turns.enqueue(SubmitResearchTurnRequest(research.research_id, "owner", "turn1", "开始"), research_turn_preparation())
    turns.claim_next(research.research_id, "owner")
    turns.mark_submitted(turn.turn_id, "run1")
    revision = revisions.commit(CommitResearchRevisionRequest(research.research_id, "owner", turn.turn_id, "run1", "原文", TEST_METHOD_HASH))
    report = tmp_path / "artifacts" / research.research_id / "revisions" / revision.revision_id / "report.md"
    report.write_text("被改写")
    with pytest.raises(ResearchConflictError, match="校验"):
        revisions.read_report(revision.revision_id, "owner")
