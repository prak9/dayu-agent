"""双研究、多话题、原始工具提交和报告交付的离线完整旅程。"""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

import httpx
import pytest
from pytest_mock import MockerFixture

from alpha.contracts.agent_execution import AgentInput
from alpha.contracts.agent_types import JsonValue
from alpha.contracts.events import AppEvent, AppEventType
from alpha.contracts.protocols import ToolExecutionContext
from alpha.host.executor import DefaultHostExecutor, _ReplayCapture
from alpha.telegram.client import TelegramClient
from alpha.telegram.main import build_daemon
from alpha.telegram.types import TelegramIncoming, decode_incoming, require_int, require_map, require_text
from tests.telegram.fakes import TelegramServer, callback, message


async def _model(
    self: DefaultHostExecutor, *, run_id: str, session_id: str | None, pending_turn_id: str | None,
    agent_input: AgentInput, replay_capture: _ReplayCapture | None = None,
) -> AsyncGenerator[AppEvent, None]:
    """仅替换模型，使用实际作用域工具提交报告。参数：执行器与真实准备输入。返回：事件流。异常：断言失败。"""
    assert agent_input.tools is not None
    result = await asyncio.to_thread(agent_input.tools.execute, "research_submit_report", {"report_markdown": f"# 研究报告\n\n会话 {session_id} 的结论、反证与缺口。"},
                                     ToolExecutionContext(run_id=run_id, tool_call_id="report", cancellation_token=agent_input.cancellation_handle))
    assert result["ok"] is True
    yield AppEvent(AppEventType.FINAL_ANSWER, {"content": "模型摘要"})


def _token(body: dict[str, JsonValue], label: str) -> str:
    """提取指定按钮。参数：消息、标签。返回：token。异常：不存在。"""
    rows = require_map(body["reply_markup"])["inline_keyboard"]
    assert isinstance(rows, list)
    for row in rows:
        assert isinstance(row, list)
        for raw in row:
            button = require_map(raw)
            if button.get("text") == label:
                return require_text(button.get("callback_data"))
    raise AssertionError(f"按钮不存在：{label}")


@pytest.mark.asyncio
async def test_two_research_topics_produce_isolated_reports_and_deduplicated_delivery(tmp_path: Path, mocker: MockerFixture) -> None:
    """同公司两个问题独立，旧报告按钮只发原版本。参数：目录、mock。返回：无。异常：断言失败。"""
    server = TelegramServer()
    client = TelegramClient("123:secret", transport=httpx.MockTransport(server))
    daemon = build_daemon(tmp_path, None, client, 123, frozenset({42}))
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", new=_model)
    updates = [message(1, "/new 腾讯资本开支"), message(2, "/new 腾讯股东回报"), message(3, "/new 非授权输入", user_id=43)]
    daemon.inbox.accept_batch(updates)
    while await daemon.dispatch_once():
        pass
    records = daemon.controller.research.list_research("42")
    assert len(records) == 2 and len(server.topics) == 2
    assert len({record.session_id for record in records}) == 2
    assert all(daemon.controller.research.overview(record.research_id, "42").queued_count == 1 for record in records)
    await daemon.schedule_once()
    await asyncio.gather(*daemon._research_tasks.values())
    await daemon.deliver_once()
    summaries = [body for body in server.messages if str(body.get("text", "")).startswith("研究完成")]
    assert len(summaries) == 2 and {require_int(body["message_thread_id"]) for body in summaries} == {7, 8}
    counts = len(server.messages)
    await daemon.deliver_once()
    assert len(server.messages) == counts
    report_token = _token(summaries[0], "完整报告")
    thread_id = cast(int, summaries[0]["message_thread_id"])
    for update_id in (10, 11):
        incoming = decode_incoming(callback(update_id, report_token, thread_id=thread_id))
        assert incoming is not None
        await daemon.controller.handle(incoming)
    assert server.documents == 1
    wrong_thread = decode_incoming(callback(12, report_token, thread_id=999))
    assert wrong_thread is not None
    with pytest.raises(PermissionError):
        await daemon.controller.handle(wrong_thread)
    for record in records:
        report = daemon.controller.research.overview(record.research_id, "42").revisions[0]
        assert record.session_id in daemon.controller.research.read_report(report.revision_id, "42")
    await client.aclose()


@pytest.mark.asyncio
async def test_unknown_topic_is_reconciled_by_marker_without_second_create(tmp_path: Path) -> None:
    """远端已建话题但响应丢失时，服务消息确认原操作。参数：目录。返回：无。异常：断言失败。"""
    server = TelegramServer(unknown_topic=True)
    client = TelegramClient("123:secret", transport=httpx.MockTransport(server))
    daemon = build_daemon(tmp_path, None, client, 123, frozenset({42}))
    daemon.inbox.accept_batch([message(1, "/new 腾讯研究")])
    await daemon.dispatch_once()
    assert len(server.topics) == 1 and not daemon._research_tasks
    daemon.inbox.recover_interrupted()
    daemon.inbox.accept_batch([message(1, "/new 腾讯研究")])
    assert not await daemon.dispatch_once()
    topic = server.topics[0]
    created: dict[str, JsonValue] = {"update_id": 2, "message": {"message_id": 2, "from": {"id": 123}, "chat": {"id": 42, "type": "private"},
        "message_thread_id": topic["message_thread_id"], "forum_topic_created": {"name": topic["name"]}}}
    daemon.inbox.accept_batch([created])
    await daemon.dispatch_once()
    record = daemon.controller.research.list_research("42")[0]
    binding = daemon.controller.topics.for_research(record.research_id, "42")
    assert binding is not None and binding.topic_id == "7" and len(server.topics) == 1
    other = build_daemon(tmp_path, None, client, 123, frozenset({42}))
    other.controller.topics.repair_ready_bindings()
    assert other.controller.topics.for_research(record.research_id, "42") == binding
    await client.aclose()


@pytest.mark.asyncio
async def test_management_pagination_stale_buttons_and_original_session_reopen(tmp_path: Path) -> None:
    """分页、检索、停止及归档按钮遵守原研究版本。参数：目录。返回：无。异常：断言失败。"""
    server = TelegramServer()
    client = TelegramClient("123:secret", transport=httpx.MockTransport(server))
    daemon = build_daemon(tmp_path, None, client, 123, frozenset({42}))
    for update_id in range(1, 7):
        incoming = decode_incoming(message(update_id, f"/new 公司问题 {update_id}"))
        assert incoming is not None
        await daemon.controller.handle(incoming)
    listing = decode_incoming(message(10, "/researches"))
    assert listing is not None
    await daemon.controller.handle(listing)
    next_page = _token(server.messages[-1], "下一页")
    incoming = decode_incoming(callback(11, next_page))
    assert incoming is not None
    await daemon.controller.handle(incoming)
    assert "公司问题 1" in require_text(server.messages[-1]["text"])
    record = daemon.controller.research.list_research("42")[0]
    binding = daemon.controller.topics.for_research(record.research_id, "42")
    assert binding is not None
    topic = int(binding.topic_id)
    incoming = decode_incoming(message(12, "/status", thread_id=topic))
    assert incoming is not None
    await daemon.controller.handle(incoming)
    old_stop = _token(server.messages[-1], "停止研究")
    followup = decode_incoming(message(13, "补充问题", thread_id=topic))
    assert followup is not None
    await daemon.controller.handle(followup)
    stale = decode_incoming(callback(14, old_stop, thread_id=topic))
    assert stale is not None
    with pytest.raises(RuntimeError, match="更新"):
        await daemon.controller.handle(stale)
    stop = decode_incoming(message(15, "/stop", thread_id=topic))
    assert stop is not None
    await daemon.controller.handle(stop)
    status = decode_incoming(message(16, "/status", thread_id=topic))
    assert status is not None
    await daemon.controller.handle(status)
    archive = decode_incoming(callback(17, _token(server.messages[-1], "归档"), thread_id=topic))
    assert archive is not None
    await daemon.controller.handle(archive)
    await daemon.controller.handle(decode_required(message(18, "/status", thread_id=topic)))
    reopen = decode_required(callback(19, _token(server.messages[-1], "重新打开"), thread_id=topic))
    await daemon.controller.handle(reopen)
    assert daemon.controller.research.overview(record.research_id, "42").research.session_id == record.session_id
    await daemon.controller.handle(decode_required(message(20, "/researches 不存在")))
    assert "尚无符合条件" in require_text(server.messages[-1]["text"])
    await daemon.controller.handle(decode_required(message(21, "/help")))
    assert "/new" in require_text(server.messages[-1]["text"])
    await daemon.controller.handle(decode_required(message(22, "根会话普通输入")))
    assert "原生话题" in require_text(server.messages[-1]["text"])
    await client.aclose()


def decode_required(update: dict[str, JsonValue]) -> TelegramIncoming:
    """取得必须支持的消息。参数：原始更新。返回：解码消息。异常：不支持时断言失败。"""
    incoming = decode_incoming(update)
    assert incoming is not None
    return incoming


@pytest.mark.asyncio
async def test_actual_daemon_lifecycle_polls_and_cleans_tasks(tmp_path: Path, mocker: MockerFixture) -> None:
    """完整四协程生命周期在取消后收敛任务。参数：目录、mock。返回：无。异常：断言失败。"""
    server = TelegramServer(updates=[message(1, "/new 生命周期验证")])
    client = TelegramClient("123:secret", transport=httpx.MockTransport(server))
    daemon = build_daemon(tmp_path, None, client, 123, frozenset({42}))
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", new=_model)
    running = asyncio.create_task(daemon.run())
    for _ in range(150):
        if any(str(item.get("text", "")).startswith("研究完成") for item in server.messages):
            break
        await asyncio.sleep(0.02)
    assert daemon.inbox.offset() == 2
    assert any(str(item.get("text", "")).startswith("研究完成") for item in server.messages)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert daemon._research_tasks == {}
    await client.aclose()


async def _broken_model(
    self: DefaultHostExecutor, *, run_id: str, session_id: str | None, pending_turn_id: str | None,
    agent_input: AgentInput, replay_capture: _ReplayCapture | None = None,
) -> AsyncGenerator[AppEvent, None]:
    """模拟连接中断。参数：真实执行上下文。返回：部分流。异常：确定的 RuntimeError。"""
    yield AppEvent(AppEventType.ITERATION_START, {"iteration": 1})
    raise RuntimeError("模拟模型连接中断")


@pytest.mark.asyncio
async def test_failed_research_waits_for_explicit_resume_and_does_not_block_inbox(tmp_path: Path, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """失败不自动重跑，显式恢复后能提交报告，收信仍可继续。参数：目录、mock、计时设置。返回：无。异常：断言失败。"""
    server = TelegramServer()
    client = TelegramClient("123:secret", transport=httpx.MockTransport(server))
    daemon = build_daemon(tmp_path, None, client, 123, frozenset({42}))
    monkeypatch.setattr("alpha.telegram.daemon._PROGRESS_INTERVAL_SECONDS", 0)
    await daemon.controller.handle(decode_required(message(1, "/new 故障恢复验证")))
    model = mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", new=_broken_model)
    await daemon.schedule_once()
    await asyncio.gather(*daemon._research_tasks.values())
    record = daemon.controller.research.list_research("42")[0]
    view = daemon.controller.research.overview(record.research_id, "42")
    assert view.latest_turn is not None and not view.revisions
    assert any("未完成" in require_text(item["text"]) for item in server.messages)
    await daemon.schedule_once()
    assert not daemon._research_tasks
    # 收信与恢复输入仍使用独立入口，失败版本不会触发自动重新执行。
    daemon.inbox.accept_batch([message(2, "/start"), {"update_id": 3, "message": {}}])
    server.limited_message = True
    assert await daemon.dispatch_once()
    assert await daemon.dispatch_once()
    assert await daemon.dispatch_once()
    assert not await daemon.dispatch_once()
    await daemon.controller.handle(decode_required(message(4, f"/resume {view.latest_turn.turn_id}")))
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", new=_model)
    await daemon.schedule_once()
    await asyncio.gather(*daemon._research_tasks.values())
    await daemon.deliver_once()
    assert len(daemon.controller.research.overview(record.research_id, "42").revisions) == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_report_buttons_route_updates_and_publish_the_bound_version(tmp_path: Path, mocker: MockerFixture) -> None:
    """新版本出现后旧按钮仍指向旧报告，不更换发布目标。参数：目录、mock。返回：无。异常：断言失败。"""
    from dataclasses import replace

    from alpha.contracts.publication import PublicationState, ResearchPublication

    server = TelegramServer()
    client = TelegramClient("123:secret", transport=httpx.MockTransport(server))
    daemon = build_daemon(tmp_path, None, client, 123, frozenset({42}))
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", new=_model)
    await daemon.controller.handle(decode_required(message(1, "/new 版本按钮验证")))
    await daemon.schedule_once()
    await asyncio.gather(*daemon._research_tasks.values())
    await daemon.deliver_once()
    card = next(item for item in server.messages if str(item.get("text", "")).startswith("研究完成"))
    record = daemon.controller.research.list_research("42")[0]
    first = daemon.controller.research.overview(record.research_id, "42").revisions[0]
    topic = cast(int, card["message_thread_id"])
    await daemon.controller.handle(decode_required(callback(2, _token(card, "更新研究"), thread_id=topic)))
    await daemon.controller.handle(decode_required(callback(3, _token(card, "检查反方"), thread_id=topic)))
    assert daemon.controller.research.overview(record.research_id, "42").queued_count == 2
    await daemon.schedule_once()
    await asyncio.gather(*daemon._research_tasks.values())
    assert len(daemon.controller.research.overview(record.research_id, "42").revisions) == 2
    publish = decode_required(callback(4, _token(card, "推送到 Invest"), thread_id=topic))
    with pytest.raises(ValueError, match="Notion"):
        await daemon.controller.handle(publish)
    gateway = mocker.Mock()
    gateway.request_publish.return_value = ResearchPublication("publication", first.revision_id, "target", first.content_hash,
                                                               PublicationState.PENDING, None, None, None, None, None)
    controller = replace(daemon.controller, publication=gateway)
    await controller.handle(publish)
    assert gateway.request_publish.call_args.args[0].revision_id == first.revision_id
    await daemon.controller.handle(decode_required(message(5, f"/bind {record.research_id}", thread_id=topic)))
    for command in ("/new", "/bind", "/resume", "/unknown"):
        with pytest.raises(ValueError):
            await daemon.controller.handle(decode_required(message(10, command)))
    await client.aclose()
