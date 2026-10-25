"""Invest/研究主题/版本的实际发布及主题未知结果恢复。"""

from dataclasses import replace
from pathlib import Path

import pytest

from alpha.contracts.cancellation import CancellationToken
from alpha.contracts.host_execution import HostedRunContext
from alpha.contracts.publication import PublicationState, PublishResearchRequest
from alpha.contracts.research import CommitResearchRevisionRequest, ResearchConflictError, SubmitResearchTurnRequest
from alpha.integrations.notion.decoding import require_map
from alpha.research.storage.notion_topics import SQLiteResearchTopics
from alpha.research.storage.turns import SQLiteResearchTurns
from alpha.services.notion_topic_service import NotionTopicService
from tests.integrations.notion.fakes import NotionServer
from tests.integrations.notion.test_client import PARENT_ID
from tests.integrations.notion.test_publication_service import _make_due, _service
from tests.research.factories import research_turn_preparation


@pytest.mark.parametrize("asynchronous", [False, True])
def test_two_versions_share_one_stable_topic_even_when_title_changes(tmp_path: Path, asynchronous: bool) -> None:
    """标题不参与主题身份，所有版本只挂同一个主题。参数：目录、异步模式。返回：无。异常：断言失败。"""
    server = NotionServer(async_create=asynchronous)
    service, store, revision, client = _service(tmp_path, server)
    topics = NotionTopicService(SQLiteResearchTopics(store), client)
    service = replace(service, topics=topics)
    service.request_publish(PublishResearchRequest(revision.revision_id, "owner", "first"))
    published = service.process_next()
    assert published is not None and published.state == PublicationState.PUBLISHED and published.page_id
    assert server.created == 2
    first_parent = require_map(server.pages[published.page_id]["parent"])["page_id"]
    assert first_parent != PARENT_ID
    assert require_map(server.pages[str(first_parent)]["parent"])["page_id"] == PARENT_ID
    # 显示标题和研究业务标题都变化；绑定仍按 research_id 复用。
    server.pages[str(first_parent)]["properties"] = {"title": {"type": "title", "title": [{"type": "text", "text": {"content": "用户改过标题"}}]}}
    with store.connection(write=True) as conn:
        conn.execute("UPDATE research_catalog SET title='新显示名' WHERE research_id=?", (revision.research_id,))
    turns = SQLiteResearchTurns(store)
    turns.settle(revision.source_turn_id, revision.source_run_id)
    turn = turns.enqueue(SubmitResearchTurnRequest(revision.research_id, "owner", "next", "增量研究"), research_turn_preparation())
    turns.claim_next(revision.research_id, "owner")
    turns.mark_submitted(turn.turn_id, "run-next")
    second = service._revisions.commit(CommitResearchRevisionRequest(revision.research_id, "owner", turn.turn_id, "run-next", "# 第二版", revision.skill_hash))
    service.request_publish(PublishResearchRequest(second.revision_id, "owner", "second"))
    later = service.process_next()
    assert later is not None and later.state == PublicationState.PUBLISHED and later.page_id != published.page_id
    assert require_map(server.pages[str(later.page_id)]["parent"])["page_id"] == first_parent
    assert server.created == 3
    assert service.request_publish(PublishResearchRequest(revision.revision_id, "owner", "old-button")).page_id == published.page_id
    client.close()


def test_unknown_topic_creation_is_reconciled_without_duplicate_topic(tmp_path: Path) -> None:
    """主题 POST 生效丢响应后只读找回，再创建版本。参数：目录。返回：无。异常：断言失败。"""
    server = NotionServer(unknown_create=True)
    service, store, revision, client = _service(tmp_path, server)
    service = replace(service, topics=NotionTopicService(SQLiteResearchTopics(store), client))
    service.request_publish(PublishResearchRequest(revision.revision_id, "owner", "publish"))
    first = service.process_next()
    assert first is not None and first.state == PublicationState.RECONCILING and first.page_id is None and server.created == 1
    _make_due(store)
    recovered = service.process_next()
    assert recovered is not None and recovered.state == PublicationState.PUBLISHED and server.created == 2
    client.close()


@pytest.mark.parametrize("committed_number", [1, 2])
def test_503_committed_topic_or_revision_uses_saved_identity(tmp_path: Path, committed_number: int) -> None:
    """主题或版本创建503返回身份后，重启只回读该页。参数：目录、创建序号。返回：无。异常：断言失败。"""
    server = NotionServer(committed_create_number=committed_number)
    service, store, revision, client = _service(tmp_path, server)
    service = replace(service, topics=NotionTopicService(SQLiteResearchTopics(store), client))
    service.request_publish(PublishResearchRequest(revision.revision_id, "owner", "publish"))
    first = service.process_next()
    assert first is not None and first.state == PublicationState.RECONCILING
    if committed_number == 1:
        with store.connection() as conn:
            assert conn.execute("SELECT page_id FROM research_notion_topics").fetchone()[0] is not None
    else:
        assert first.page_id is not None
    _make_due(store)
    recovered = service.process_next()
    assert recovered is not None and recovered.state == PublicationState.PUBLISHED
    assert server.create_attempts == 2
    client.close()


def test_unknown_topic_without_candidates_never_recreates(tmp_path: Path) -> None:
    """未找到不代表未创建。参数：目录。返回：无。异常：断言失败。"""
    server = NotionServer(unknown_create=True)
    service, store, revision, client = _service(tmp_path, server)
    service = replace(service, topics=NotionTopicService(SQLiteResearchTopics(store), client))
    service.request_publish(PublishResearchRequest(revision.revision_id, "owner", "publish"))
    service.process_next()
    server.pages.clear()
    server.markdown.clear()
    for _ in range(2):
        _make_due(store)
        result = service.process_next()
        assert result is not None and result.state == PublicationState.RECONCILING
    assert server.create_attempts == 1
    client.close()


def test_topic_store_fences_late_results_and_preserves_binding(tmp_path: Path) -> None:
    """接管后旧执行者不能改变主题页；活跃租约保持排他。参数：目录。返回：无。异常：断言失败。"""
    server = NotionServer()
    _, store, revision, client = _service(tmp_path, server)
    records = SQLiteResearchTopics(store)
    with pytest.raises(KeyError):
        records.claim(revision.research_id, PARENT_ID)
    with pytest.raises(PermissionError):
        records.reserve(revision.research_id, "other", PARENT_ID, "主题")
    records.reserve(revision.research_id, "owner", PARENT_ID, "主题")
    first = records.claim(revision.research_id, PARENT_ID)
    with pytest.raises(ResearchConflictError):
        records.claim(revision.research_id, PARENT_ID)
    records.mark_started(first)
    with pytest.raises(ResearchConflictError):
        records.mark_started(first)
    with store.connection(write=True) as conn:
        conn.execute("UPDATE research_notion_topics SET owner_pid=99999999,owner_start_time=NULL,owner_boot_id=NULL")
    second = records.claim(revision.research_id, PARENT_ID)
    assert second.creation_started
    with pytest.raises(ResearchConflictError):
        records.save_page(first, "late")
    records.release(first)
    records.save_task(second, "task")
    with pytest.raises(ResearchConflictError):
        records.mark_rejected(second)
    with pytest.raises(ResearchConflictError):
        records.save_task(second, "changed")
    records.save_page(second, "page")
    with pytest.raises(ResearchConflictError):
        records.save_page(second, "changed")
    records.release(second)
    assert records.claim(revision.research_id, PARENT_ID).page_id == "page"
    client.close()


def test_known_topic_moved_or_missing_marker_cannot_be_recreated(tmp_path: Path) -> None:
    """远端人工更改不能触发另建同名主题。参数：目录。返回：无。异常：断言失败。"""
    server = NotionServer()
    _, store, revision, client = _service(tmp_path, server)
    service = NotionTopicService(SQLiteResearchTopics(store), client)
    service.reserve(revision.research_id, "owner", PARENT_ID, "主题")
    context = HostedRunContext("run", CancellationToken())
    page = service.resolve(revision.research_id, PARENT_ID, context)
    server.markdown[page] = "用户删除了标记"
    with pytest.raises(ValueError, match="标记"):
        service.resolve(revision.research_id, PARENT_ID, context)
    assert server.created == 1
    client.close()
