"""指定版本发布意图、租约 fencing、未知恢复和正文冻结测试。"""

from dataclasses import replace
from pathlib import Path

import pytest

from alpha.contracts.publication import PublicationState, PublishResearchRequest
from alpha.contracts.research import CommitResearchRevisionRequest, CreateResearchRequest, ResearchConflictError, ResearchRevision, SubmitResearchTurnRequest
from alpha.research.storage.artifacts import FsResearchArtifactStore
from alpha.research.storage.catalog import SQLiteResearchCatalog
from alpha.research.storage.publications import SQLiteResearchPublications
from alpha.research.storage.revisions import SQLiteResearchRevisions
from alpha.research.storage.store import ResearchStore
from alpha.research.storage.turns import SQLiteResearchTurns
from tests.research.factories import TEST_METHOD_HASH, research_turn_preparation


def _ready(tmp_path: Path) -> tuple[ResearchStore, SQLiteResearchPublications, ResearchRevision]:
    """准备正式版本与发布仓储。参数：目录。返回：库、发布端口、正式版本。异常：存储错误。"""
    store = ResearchStore(tmp_path / "research.db")
    research = SQLiteResearchCatalog(store).create(CreateResearchRequest("owner", "new", "研究"))
    turns = SQLiteResearchTurns(store)
    turn = turns.enqueue(SubmitResearchTurnRequest(research.research_id, "owner", "turn", "开始"), research_turn_preparation())
    turns.claim_next(research.research_id, "owner")
    turns.mark_submitted(turn.turn_id, "run")
    revision = SQLiteResearchRevisions(store, FsResearchArtifactStore(tmp_path / "artifacts")).commit(
        CommitResearchRevisionRequest(research.research_id, "owner", turn.turn_id, "run", "# 报告", TEST_METHOD_HASH))
    return store, SQLiteResearchPublications(store), revision


def test_publication_is_unique_for_revision_target_and_request_identity(tmp_path: Path) -> None:
    """不同按钮复用同一版本页面意图，键重用改变目标拒绝。参数：目录。返回：无。异常：断言失败。"""
    _, publications, revision = _ready(tmp_path)
    request = PublishResearchRequest(revision.revision_id, "owner", "publish")
    first = publications.request(request, target_id="invest", title="原标题", markdown="# 原正文")
    assert publications.request(request, target_id="invest", title="新渲染标题", markdown="# 后来的渲染") == first
    assert publications.request(replace(request, request_key="other-button"), target_id="invest", title="title", markdown="body") == first
    claim = publications.claim_next()
    assert claim is not None and claim.payload.markdown == "# 原正文"
    assert publications.claim_next() is None
    with pytest.raises(ResearchConflictError):
        publications.request(request, target_id="different", title="title", markdown="body")
    with pytest.raises(PermissionError):
        publications.get(first.publication_id, "stranger")
    with pytest.raises(PermissionError):
        publications.request(replace(request, owner_id="stranger"), target_id="invest", title="title", markdown="body")
    with pytest.raises(KeyError):
        publications.request(replace(request, revision_id="missing"), target_id="invest", title="title", markdown="body")
    publications.release(claim)


def test_remote_task_is_not_published_and_finished_page_is_immutable(tmp_path: Path) -> None:
    """task 身份不是完成；发布后不能重新进入写状态。参数：目录。返回：无。异常：断言失败。"""
    _, publications, revision = _ready(tmp_path)
    original = publications.request(PublishResearchRequest(revision.revision_id, "owner", "publish"), target_id="invest", title="title", markdown="body")
    claim = publications.claim_next()
    assert claim is not None
    with pytest.raises(ResearchConflictError):
        publications.mark_published(claim)
    publications.link_run(claim, "run-1")
    publications.link_run(claim, "run-1")
    with pytest.raises(ResearchConflictError):
        publications.link_run(claim, "other-run")
    publications.save_task(claim, "task")
    with pytest.raises(ResearchConflictError):
        publications.mark_published(claim)
    publications.save_page(claim, "page", "https://www.notion.so/page")
    with pytest.raises(ResearchConflictError):
        publications.save_page(claim, "different-page", "url")
    with pytest.raises(ResearchConflictError, match="分段"):
        publications.mark_published(claim)
    publications.record_progress(claim, 1)
    result = publications.mark_published(claim)
    assert result.state == PublicationState.PUBLISHED and result.remote_task_id is None and result.page_id == "page"
    with pytest.raises(ResearchConflictError):
        publications.defer(claim, PublicationState.RECONCILING, "late")
    publications.release(claim)
    assert publications.claim_next() is None
    assert publications.get(original.publication_id, "owner") == result


def test_failed_retry_and_interrupted_lease_keep_original_payload(tmp_path: Path) -> None:
    """重试尝试与执行租约分开，接管未知副作用不能默认重建。参数：目录。返回：无。异常：断言失败。"""
    store, publications, revision = _ready(tmp_path)
    publications.request(PublishResearchRequest(revision.revision_id, "owner", "publish"), target_id="invest", title="title", markdown="body")
    claim = publications.claim_next()
    assert claim is not None
    publications.defer(claim, PublicationState.FAILED_RETRYABLE, "limited")
    publications.release(claim)
    retry = publications.claim_next()
    assert retry is not None and not retry.interrupted
    next_attempt = publications.advance_attempt(retry)
    assert next_attempt.attempt == 2 and next_attempt.payload == retry.payload
    publications.link_run(next_attempt, "run-2")
    with store.connection(write=True) as conn:
        conn.execute("UPDATE research_publications SET owner_pid=99999999,owner_start_time=NULL,owner_boot_id=NULL")
    other = SQLiteResearchPublications(ResearchStore(tmp_path / "research.db"))
    recovered = other.claim_next()
    assert recovered is not None and recovered.interrupted and recovered.publication.state == PublicationState.RECONCILING
    with pytest.raises(ResearchConflictError, match="过期"):
        publications.save_page(next_attempt, "late", "url")
    publications.release(next_attempt)
    assert other.claim_next() is None
    other.defer(recovered, PublicationState.RECONCILING, "not found", retry_after=60)
    other.release(recovered)
    assert other.claim_next() is None


def test_publication_payload_damage_rolls_back_claim(tmp_path: Path) -> None:
    """冻结正文损坏时不能发布，也不留资源领取。参数：目录。返回：无。异常：断言失败。"""
    store, publications, revision = _ready(tmp_path)
    record = publications.request(PublishResearchRequest(revision.revision_id, "owner", "publish"), target_id="invest", title="title", markdown="body")
    with store.connection(write=True) as conn:
        conn.execute("UPDATE research_publications SET markdown='changed'")
    with pytest.raises(ResearchConflictError, match="完整性"):
        publications.get(record.publication_id, "owner")
    with pytest.raises(ResearchConflictError, match="完整性"):
        publications.claim_next()
    with store.connection() as conn:
        assert conn.execute("SELECT lease_id FROM research_publications").fetchone()[0] is None
