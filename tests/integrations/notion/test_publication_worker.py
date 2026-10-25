"""发布线程取消、已知远端身份保留和 Host 资源收尾测试。"""

import asyncio
from pathlib import Path
from threading import Event
from typing import cast

import pytest
from pytest_mock import MockerFixture

from alpha.contracts.publication import PublicationState, PublishResearchRequest
from alpha.contracts.run import RunState
from alpha.contracts.cancellation import CancellationToken
from alpha.services.publication_worker import PublicationWorker
from tests.integrations.notion.fakes import NotionServer
from tests.integrations.notion.test_publication_service import _make_due, _service


@pytest.mark.asyncio
async def test_worker_cancellation_waits_for_http_and_preserves_known_page(tmp_path: Path, mocker: MockerFixture) -> None:
    """退出不能留下无人持有的同步 HTTP 线程，已知页面先持久保存。参数：目录。返回：无。异常：断言失败。"""
    entered, release = Event(), Event()
    server = NotionServer(create_entered=entered, create_release=release)
    service, store, revision, client = _service(tmp_path, server)
    creating = mocker.spy(client, "create_page")
    intent = service.request_publish(PublishResearchRequest(revision.revision_id, "owner", "publish"))
    running = asyncio.create_task(PublicationWorker(service).process_once())
    assert await asyncio.to_thread(entered.wait, 2)
    host_token = cast(CancellationToken, creating.call_args.args[3])
    running.cancel()
    # Host 取消桥为协作轮询；等实际令牌触发再释放 HTTP，避免把 20ms 当成取消完成证明。
    assert await asyncio.to_thread(host_token.wait, 2)
    assert not running.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await running
    interrupted = service.get(intent.publication_id, "owner")
    assert interrupted.state == PublicationState.RECONCILING and interrupted.page_id is not None
    assert interrupted.run_id is not None
    run = service.host.get_run(interrupted.run_id)
    assert run is not None and run.state == RunState.CANCELLED
    _make_due(store)
    recovered = service.process_next()
    assert recovered is not None and recovered.state == PublicationState.PUBLISHED and server.created == 1
    client.close()
