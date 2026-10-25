"""真实 Host 与业务仓储上的 Notion 指定版本发布及未知创建调和测试。"""

from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from alpha.contracts.publication import PublicationState, PublishResearchRequest
from alpha.contracts.research import ResearchRevision
from alpha.contracts.host_execution import HostedRunContext
from alpha.host.host import Host
from alpha.integrations.notion.client import NotionClient
from alpha.research.storage.artifacts import FsResearchArtifactStore
from alpha.research.storage.catalog import SQLiteResearchCatalog
from alpha.research.storage.publications import SQLiteResearchPublications
from alpha.research.storage.revisions import SQLiteResearchRevisions
from alpha.research.storage.store import ResearchStore
from alpha.services.publication_service import PublicationService
from tests.integrations.notion.fakes import NotionServer
from tests.integrations.notion.test_client import PARENT_ID
from tests.research.test_publications import _ready


class _ExistingTopic:
    """版本发布测试固定已存在的主题，主题创建/调和在独立测试中验证。"""

    def reserve(self, research_id: str, owner_id: str, root_id: str, title: str) -> None:
        """接收固定目标。参数：研究、用户、根、标题。返回：无。异常：无。"""

    def resolve(self, research_id: str, root_id: str, context: HostedRunContext) -> str:
        """模拟已存在的主题身份。参数：研究、根、上下文。返回：主题。异常：取消。"""
        context.cancellation_token.raise_if_cancelled()
        return root_id


def _service(tmp_path: Path, server: NotionServer) -> tuple[PublicationService, ResearchStore, ResearchRevision, NotionClient]:
    """装配真实发布路径。参数：目录、远端模拟。返回：服务、库、版本、客户端。异常：装配错误。"""
    store, records, revision = _ready(tmp_path)
    client = NotionClient("secret-token", transport=httpx.MockTransport(server))
    service = PublicationService(Host(host_store_path=tmp_path / "host.db", lane_config={"publication": 1}), records,
                                  SQLiteResearchCatalog(store), SQLiteResearchRevisions(store, FsResearchArtifactStore(tmp_path / "artifacts")), client, PARENT_ID, _ExistingTopic())
    return service, store, revision, client


def _make_due(store: ResearchStore) -> None:
    """故障探针推进到期，不依赖真实等待。参数：研究库。返回：无。异常：数据库错误。"""
    with store.connection(write=True) as conn:
        conn.execute("UPDATE research_publications SET retry_at=0")


@pytest.mark.parametrize("asynchronous", [False, True])
def test_exact_revision_is_published_once_and_complete_readback_is_required(tmp_path: Path, asynchronous: bool) -> None:
    """同步与异步都回读后确认，重复按钮不再创建。参数：目录、异步模式。返回：无。异常：断言失败。"""
    server = NotionServer(async_create=asynchronous)
    service, _, revision, client = _service(tmp_path, server)
    request = PublishResearchRequest(revision.revision_id, "owner", "publish")
    intent = service.request_publish(request)
    assert intent.state == PublicationState.PENDING and server.created == 0
    result = service.process_next()
    assert result is not None and result.state == PublicationState.PUBLISHED and result.page_url
    assert result.run_id is not None
    run = service.host.get_run(result.run_id)
    assert run is not None and run.session_id is None
    assert service.request_publish(replace(request, request_key="second-button")) == result
    assert service.process_next() is None and server.created == 1
    assert service.get(intent.publication_id, "owner") == result
    with pytest.raises(PermissionError):
        service.request_publish(replace(request, owner_id="stranger"))
    client.close()


def test_created_page_lost_response_is_found_without_second_create(tmp_path: Path) -> None:
    """创建已生效但响应丢失后，通过固定父页和标记关联原页。参数：目录。返回：无。异常：断言失败。"""
    server = NotionServer(unknown_create=True)
    service, store, revision, client = _service(tmp_path, server)
    service.request_publish(PublishResearchRequest(revision.revision_id, "owner", "publish"))
    first = service.process_next()
    assert first is not None and first.state == PublicationState.RECONCILING and first.page_id is None
    _make_due(store)
    recovered = service.process_next()
    assert recovered is not None and recovered.state == PublicationState.PUBLISHED
    assert server.created == 1 and server.create_attempts == 1
    client.close()


def test_unknown_create_with_no_candidate_stays_reconciling(tmp_path: Path) -> None:
    """未找到远端页面不作为创建未发生的证明。参数：目录。返回：无。异常：断言失败。"""
    server = NotionServer(unknown_create=True)
    service, store, revision, client = _service(tmp_path, server)
    service.request_publish(PublishResearchRequest(revision.revision_id, "owner", "publish"))
    service.process_next()
    server.pages.clear()
    server.markdown.clear()
    _make_due(store)
    result = service.process_next()
    assert result is not None and result.state == PublicationState.RECONCILING and server.created == 1
    _make_due(store)
    still_unknown = service.process_next()
    assert still_unknown is not None and still_unknown.state == PublicationState.RECONCILING
    assert server.create_attempts == 1
    client.close()


def test_explicit_rate_limit_retries_but_permissions_and_failed_tasks_do_not_publish(tmp_path: Path) -> None:
    """明确限流可重试；权限或异步失败保持未发布。参数：目录。返回：无。异常：断言失败。"""
    server = NotionServer(limited_create=True)
    service, _, revision, client = _service(tmp_path, server)
    service.request_publish(PublishResearchRequest(revision.revision_id, "owner", "publish"))
    rejected = service.process_next()
    assert rejected is not None and rejected.state == PublicationState.FAILED_RETRYABLE
    published = service.process_next()
    assert published is not None and published.state == PublicationState.PUBLISHED
    assert server.created == 1 and server.create_attempts == 2
    client.close()
    for name, denied in (("denied", True), ("async-fail", False)):
        directory = tmp_path / name
        directory.mkdir()
        server = NotionServer(deny_parent=denied, async_create=not denied, failed_task=not denied)
        service, _, revision, client = _service(directory, server)
        service.request_publish(PublishResearchRequest(revision.revision_id, "owner", "publish"))
        result = service.process_next()
        assert result is not None and result.state == PublicationState.FAILED_TERMINAL
        assert server.created == (0 if denied else 1)
        client.close()


def test_fixed_permission_failure_needs_new_explicit_request_key(tmp_path: Path) -> None:
    """修复权限后新授权可重试，重放旧失败键不自动再执行。参数：目录。返回：无。异常：断言失败。"""
    server = NotionServer(deny_parent=True)
    service, _, revision, client = _service(tmp_path, server)
    request = PublishResearchRequest(revision.revision_id, "owner", "publish")
    service.request_publish(request)
    failed = service.process_next()
    assert failed is not None and failed.state == PublicationState.FAILED_TERMINAL and server.created == 0
    server.deny_parent = False
    assert service.request_publish(request).state == PublicationState.FAILED_TERMINAL
    assert service.process_next() is None
    assert service.request_publish(replace(request, request_key="explicit-retry")).state == PublicationState.PENDING
    finished = service.process_next()
    assert finished is not None and finished.state == PublicationState.PUBLISHED and server.created == 1
    client.close()


@pytest.mark.parametrize("truncated", [False, True])
def test_bad_readback_does_not_publish_or_overwrite_remote_page(tmp_path: Path, truncated: bool) -> None:
    """正文不完整或数值变化必须待核对，不能当成发布成功。参数：目录、截断模式。返回：无。异常：断言失败。"""
    server = NotionServer(corrupt_readback=not truncated, truncated=truncated)
    service, store, revision, client = _service(tmp_path, server)
    service.request_publish(PublishResearchRequest(revision.revision_id, "owner", "publish"))
    first = service.process_next()
    assert first is not None and first.state == PublicationState.RECONCILING and first.page_id is not None
    server.corrupt_readback = False
    server.truncated = False
    _make_due(store)
    second = service.process_next()
    assert second is not None and second.state == PublicationState.PUBLISHED and server.created == 1
    client.close()
