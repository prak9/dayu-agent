"""原生 Codex 动态工具适配的真实作用域、事件与旁路拒绝测试。"""

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from alpha.contracts.agent_types import AgentMessage, JsonValue, build_user_chat_message
from alpha.contracts.cancellation import CancellationToken, CancelledError
from alpha.engine.async_codex_runner import AsyncCodexRunner
from alpha.engine.events import EventType
from alpha.integrations.codex.client import require_map
from tests.research.test_tools import _registered

_TRACE: dict[str, JsonValue] = {"run_id": "run", "iteration_id": "iteration"}


@dataclass
class _Rpc:
    """保留实际动态工具交互顺序的原生协议模拟。"""

    events: list[dict[str, JsonValue]]
    requests: list[tuple[str, dict[str, JsonValue]]] = field(default_factory=list)
    sent: list[dict[str, JsonValue]] = field(default_factory=list)
    closed: bool = False

    async def start(self) -> None:
        """模拟已登录的握手。参数：无。返回：无。异常：无。"""

    async def request(self, method: str, params: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """返回最小真实协议形状。参数：方法、参数。返回：配置或身份。异常：未知方法。"""
        self.requests.append((method, params))
        if method == "config/read":
            return {"config": {"mcp_servers": {"notion": {"env": {"NOTION_TOKEN": "never-copy"}}}}}
        if method == "thread/start":
            return {"thread": {"id": "native-thread"}}
        if method == "turn/start":
            return {"turn": {"id": "native-turn"}}
        raise AssertionError(method)

    async def receive(self) -> dict[str, JsonValue]:
        """按序送出事件。参数：无。返回：事件。异常：无事件。"""
        assert self.events
        return self.events.pop(0)

    async def send(self, message: dict[str, JsonValue]) -> None:
        """保存应答，不自动推进模型。参数：应答。返回：无。异常：无。"""
        self.sent.append(message)

    async def close(self) -> None:
        """标记回收。参数：无。返回：无。异常：无。"""
        self.closed = True


def _tool(name: str = "research_save_note") -> dict[str, JsonValue]:
    """构造原生工具请求。参数：名称。返回：请求。异常：无。"""
    return {"id": 900, "method": "item/tool/call", "params": {"callId": "native-call", "threadId": "native-thread",
        "turnId": "native-turn", "tool": name, "arguments": {"title": "来源", "content": "原文待核对"}}}


def _done(status: str = "completed") -> dict[str, JsonValue]:
    """构造终态。参数：状态。返回：通知。异常：无。"""
    return {"method": "turn/completed", "params": {"turn": {"id": "native-turn", "status": status}}}


@pytest.mark.asyncio
async def test_native_tool_yields_to_host_before_reply_and_preserves_context(tmp_path: Path, mocker: MockerFixture) -> None:
    """工具结果落入 alpha 后才交回原生推理，Host 可在两次 call 间停止。参数：目录、mock。返回：无。异常：断言失败。"""
    rpc = _Rpc([_tool(), {"method": "item/completed", "params": {"item": {"type": "agentMessage", "phase": "final_answer", "text": "研究完成"}}}, _done()])
    mocker.patch("alpha.engine.async_codex_runner.CodexRpcClient", return_value=rpc)
    registry, records, scope = _registered(tmp_path)
    runner = AsyncCodexRunner(working_dir=tmp_path)
    runner.set_tools(registry)
    messages: list[AgentMessage] = [build_user_chat_message("研究")]
    first = [event async for event in runner.call(messages, trace_context=_TRACE)]
    assert len(records.list_records(scope)) == 1
    assert [event.type for event in first] == [EventType.TOOL_CALL_DISPATCHED, EventType.TOOL_CALLS_BATCH_READY,
        EventType.TOOL_CALL_RESULT, EventType.TOOL_CALLS_BATCH_DONE, EventType.CONTENT_COMPLETE, EventType.DONE]
    assert not rpc.sent
    second = [event async for event in runner.call(messages, trace_context=_TRACE)]
    assert second[0].data == "研究完成" and len(rpc.sent) == 1
    start = next(params for method, params in rpc.requests if method == "thread/start")
    assert "never-copy" not in str(start)
    config = require_map(start["config"])
    assert require_map(require_map(config["mcp_servers"])["notion"])["enabled"] is False
    assert require_map(config["features"])["shell_tool"] is False
    await runner.close()
    assert rpc.closed


@pytest.mark.parametrize("notification", [
    {"method": "error", "params": {}}, _done("failed"), _tool("unaccepted_tool"),
    {"id": 90, "method": "item/commandExecution/requestApproval", "params": {}},
    {"method": "item/started", "params": {"item": {"type": "commandExecution"}}},
])
@pytest.mark.asyncio
async def test_native_failure_or_bypass_fails_closed(tmp_path: Path, mocker: MockerFixture, notification: dict[str, JsonValue]) -> None:
    """旁路工具、权限与远端失败不形成成功报告。参数：目录、mock、事件。返回：无。异常：断言失败。"""
    rpc = _Rpc([notification])
    mocker.patch("alpha.engine.async_codex_runner.CodexRpcClient", return_value=rpc)
    runner = AsyncCodexRunner(working_dir=tmp_path)
    with pytest.raises(RuntimeError):
        _ = [event async for event in runner.call([build_user_chat_message("研究")], trace_context=_TRACE)]
    assert rpc.closed


@pytest.mark.asyncio
async def test_pre_cancel_and_private_payload_never_start_native_process(tmp_path: Path, mocker: MockerFixture) -> None:
    """取消和不支持的 API 参数在进程启动前拒绝。参数：目录、mock。返回：无。异常：断言失败。"""
    constructor = mocker.patch("alpha.engine.async_codex_runner.CodexRpcClient")
    token = CancellationToken()
    token.cancel()
    runner = AsyncCodexRunner(working_dir=tmp_path, cancellation_token=token)
    with pytest.raises(CancelledError):
        _ = [event async for event in runner.call([])]
    with pytest.raises(ValueError):
        _ = [event async for event in runner.call([], unsupported=True)]
    constructor.assert_not_called()
    with pytest.raises(ValueError):
        AsyncCodexRunner(working_dir=tmp_path, timeout=0)
