"""报告卡到指定 Invest 页的完整离线旅程，远端与模型以外均使用真实实现。"""

import asyncio
from pathlib import Path

import httpx
import pytest
from pytest_mock import MockerFixture

from alpha.contracts.publication import PublicationState
from alpha.integrations.notion.client import NotionClient
from alpha.services.publication_preparation import PublicationConnection
from alpha.telegram.client import TelegramClient
from alpha.telegram.main import build_daemon
from alpha.telegram.types import require_int
from tests.integrations.notion.fakes import NotionServer
from tests.integrations.notion.test_client import PARENT_ID
from tests.telegram.fakes import TelegramServer, callback, message
from tests.telegram.test_journey import _model, _token, decode_required


@pytest.mark.asyncio
async def test_old_report_card_publishes_old_version_after_new_research(tmp_path: Path, mocker: MockerFixture) -> None:
    """v2 出现后旧按钮发布 v1，并把链接发回原话题。参数：目录、mock。返回：无。异常：断言失败。"""
    telegram = TelegramServer()
    notion = NotionServer(async_create=True)
    client = TelegramClient("123:secret", transport=httpx.MockTransport(telegram))
    notion_client = NotionClient("secret", transport=httpx.MockTransport(notion))
    daemon = build_daemon(tmp_path, None, client, 123, frozenset({42}), publication_connection=PublicationConnection(notion_client, PARENT_ID))
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", new=_model)
    await daemon.controller.handle(decode_required(message(1, "/new 版本推送研究")))
    await daemon.schedule_once()
    await asyncio.gather(*daemon._research_tasks.values())
    await daemon.deliver_once()
    card = next(item for item in telegram.messages if str(item.get("text", "")).startswith("研究完成"))
    topic = require_int(card["message_thread_id"])
    record = daemon.controller.research.list_research("42")[0]
    v1 = daemon.controller.research.overview(record.research_id, "42").revisions[0]
    await daemon.controller.handle(decode_required(callback(2, _token(card, "推送到 Invest"), thread_id=topic)))
    assert notion.created == 0
    await daemon.controller.handle(decode_required(callback(3, _token(card, "更新研究"), thread_id=topic)))
    await daemon.schedule_once()
    await asyncio.gather(*daemon._research_tasks.values())
    v2 = daemon.controller.research.overview(record.research_id, "42").revisions[1]
    await daemon.publish_once()
    assert daemon.publication_worker is not None
    published = daemon.publication_worker.service.list_for_owner("42")[0]
    assert published.state == PublicationState.PUBLISHED and published.revision_id == v1.revision_id
    assert published.page_url is not None
    assert published.page_id is not None
    remote = notion.markdown[published.page_id]
    assert v1.revision_id in remote and v2.revision_id not in remote
    notifications = [item for item in telegram.messages if "已推送到 Invest" in str(item.get("text", ""))]
    assert len(notifications) == 1 and notifications[0]["message_thread_id"] == topic
    await daemon.controller.handle(decode_required(message(4, f"/publication {published.publication_id}", thread_id=topic)))
    assert published.page_url in str(telegram.messages[-1]["text"])
    await daemon.controller.handle(decode_required(callback(5, _token(card, "推送到 Invest"), thread_id=topic)))
    await daemon.publish_once()
    assert notion.created == 2
    await client.aclose()
    notion_client.close()


@pytest.mark.asyncio
async def test_permission_failure_retry_button_is_new_authorization(tmp_path: Path, mocker: MockerFixture) -> None:
    """修复权限后点击明确重试按钮能继续，重复旧请求不自行再发布。参数：目录、mock。返回：无。异常：断言失败。"""
    telegram, notion = TelegramServer(), NotionServer(deny_parent=True)
    client = TelegramClient("123:secret", transport=httpx.MockTransport(telegram))
    notion_client = NotionClient("secret", transport=httpx.MockTransport(notion))
    daemon = build_daemon(tmp_path, None, client, 123, frozenset({42}), publication_connection=PublicationConnection(notion_client, PARENT_ID))
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", new=_model)
    await daemon.controller.handle(decode_required(message(1, "/new 权限修复验证")))
    await daemon.schedule_once()
    await asyncio.gather(*daemon._research_tasks.values())
    await daemon.deliver_once()
    card = next(item for item in telegram.messages if str(item.get("text", "")).startswith("研究完成"))
    topic = require_int(card["message_thread_id"])
    await daemon.controller.handle(decode_required(callback(2, _token(card, "推送到 Invest"), thread_id=topic)))
    await daemon.publish_once()
    failure = next(item for item in telegram.messages if "推送失败" in str(item.get("text", "")))
    assert notion.created == 0
    notion.deny_parent = False
    await daemon.controller.handle(decode_required(callback(3, _token(failure, "重试推送"), thread_id=topic)))
    await daemon.publish_once()
    assert notion.created == 2 and any("已推送到 Invest" in str(item.get("text", "")) for item in telegram.messages)
    await daemon.controller.handle(decode_required(callback(4, _token(failure, "重试推送"), thread_id=topic)))
    await daemon.publish_once()
    assert notion.created == 2
    await client.aclose()
    notion_client.close()
