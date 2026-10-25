"""Telegram 文件真实下载、入库、逐页读取和 v2 研究闭环。"""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx
import pytest
from pytest_mock import MockerFixture

from alpha.contracts.agent_execution import AgentInput
from alpha.contracts.events import AppEvent, AppEventType
from alpha.contracts.protocols import ToolExecutionContext
from alpha.host.executor import DefaultHostExecutor, _ReplayCapture
from alpha.telegram.client import TelegramClient
from alpha.telegram.main import build_daemon
from alpha.telegram.types import decode_incoming
from tests.telegram.fakes import TelegramServer, message
from tests.telegram.test_journey import _model


async def _material_model(self: DefaultHostExecutor, *, run_id: str, session_id: str | None, pending_turn_id: str | None,
    agent_input: AgentInput, replay_capture: _ReplayCapture | None = None) -> AsyncGenerator[AppEvent, None]:
    """使用实际作用域工具读取已接收文件。参数：真实模型准备输入。返回：最终事件。异常：断言失败。"""
    assert agent_input.tools is not None
    context = ToolExecutionContext(run_id=run_id, tool_call_id="list", cancellation_token=agent_input.cancellation_handle)
    listing = await asyncio.to_thread(agent_input.tools.execute, "research_list_materials", {}, context)
    assert listing["ok"]
    material_id = listing["value"]["materials"][0]["material_id"]
    text = await asyncio.to_thread(agent_input.tools.execute, "research_read_material", {"material_id": material_id}, context)
    assert text["ok"] and "收入" in text["value"]["content"]
    result = await asyncio.to_thread(agent_input.tools.execute, "research_submit_report", {"report_markdown": "# 材料更新\n" + text["value"]["content"]}, context)
    assert result["ok"]
    yield AppEvent(AppEventType.FINAL_ANSWER, {"content": "完成材料更新"})


@pytest.mark.asyncio
async def test_document_adds_new_revision_and_replay_never_adds_another_turn(tmp_path: Path, mocker: MockerFixture) -> None:
    """文件更新不覆盖 v1，重复更新只接受一次。参数：目录、mock。返回：无。异常：断言失败。"""
    server = TelegramServer(files={"financial-note": "收入：用户提供，尚需与原始财报核对。".encode()})
    client = TelegramClient("123:secret", transport=httpx.MockTransport(server))
    daemon = build_daemon(tmp_path, None, client, 123, frozenset({42}))
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", new=_model)
    incoming = decode_incoming(message(1, "/new 收入质量"))
    assert incoming is not None
    await daemon.controller.handle(incoming)
    record = daemon.controller.research.list_research("42")[0]
    await daemon.schedule_once()
    await asyncio.gather(*daemon._research_tasks.values())
    first = daemon.controller.research.overview(record.research_id, "42").revisions[0]
    original = daemon.controller.research.read_report(first.revision_id, "42")
    raw = message(2, "检查收入变化", thread_id=7)
    body = raw["message"]
    assert isinstance(body, dict)
    body["document"] = {"file_id": "financial-note", "file_unique_id": "unique", "file_name": "note.md", "file_size": 1}
    incoming = decode_incoming(raw)
    assert incoming is not None
    await daemon.controller.handle(incoming)
    await daemon.controller.handle(incoming)
    assert daemon.controller.research.overview(record.research_id, "42").queued_count == 1
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", new=_material_model)
    await daemon.schedule_once()
    await asyncio.gather(*daemon._research_tasks.values())
    versions = daemon.controller.research.overview(record.research_id, "42").revisions
    assert len(versions) == 2 and versions[1].parent_revision_id == first.revision_id
    assert "收入" in daemon.controller.research.read_report(versions[1].revision_id, "42")
    assert daemon.controller.research.read_report(first.revision_id, "42") == original
    await client.aclose()
