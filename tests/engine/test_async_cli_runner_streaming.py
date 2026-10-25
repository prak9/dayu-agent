"""
AsyncCliRunner 流处理额外测试 - 提升覆盖率
"""
import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from alpha.contracts.agent_types import AgentMessage
from alpha.engine.async_cli_runner import AsyncCliRunner
from alpha.engine import EventType


def _messages(*contents: str) -> list[AgentMessage]:
    """构造强类型消息列表。"""

    return [{"role": "user", "content": content} for content in contents]


class FakeStdout:
    def __init__(self, lines):
        self._lines = [line.encode("utf-8") for line in lines]

    async def readline(self):
        if not self._lines:
            return b""
        return self._lines.pop(0)


class FakeStdin:
    def __init__(self):
        self.buffer = b""

    def write(self, data):
        self.buffer += data

    async def drain(self):
        return None

    def close(self):
        return None


class FakeStderr:
    def __init__(self, payload=b""):
        self._payload = payload

    async def read(self):
        return self._payload


class FakeProcess:
    def __init__(self, lines, returncode=0, stderr=b""):
        self.stdin = FakeStdin()
        self.stdout = FakeStdout(lines)
        self.stderr = FakeStderr(stderr)
        self.returncode = returncode
        self.killed = False

    async def wait(self):
        return self.returncode

    def kill(self):
        self.killed = True


@pytest.mark.asyncio
class TestAsyncCliRunnerStreamingEdgeCases:
    """测试 AsyncCliRunner 流处理的边缘情况"""

    async def test_run_streaming_timeout_error(self):
        """测试 CLI 超时错误处理（覆盖行541-556）"""
        runner = AsyncCliRunner(command=["codex", "exec"], timeout=1)
        
        # 创建一个永不返回的 readline mock
        class SlowFakeProcess:
            def __init__(self):
                self.stdin = FakeStdin()
                self.stdout = self
                self.stderr = FakeStderr()
                self.killed = False

            async def readline(self):
                # 模拟超时：等待超过设定的 timeout
                await asyncio.sleep(10)
                return b""

            def kill(self):
                self.killed = True

            async def wait(self):
                return 0
        
        fake_process = SlowFakeProcess()

        with patch("asyncio.create_subprocess_exec", return_value=fake_process):
            events = []
            async for event in runner._run_streaming(["codex", "exec"], "prompt"):
                events.append(event)

        # 验证超时错误事件
        assert len(events) == 1
        assert events[0].type == EventType.ERROR
        assert "timeout" in str(events[0].data).lower()
        # 验证进程被 kill
        assert fake_process.killed is True

    async def test_run_streaming_generic_exception(self):
        """测试通用异常处理（覆盖行557-568）"""
        runner = AsyncCliRunner(command=["codex", "exec"])
        
        class ExceptionFakeProcess:
            def __init__(self):
                self.stdin = FakeStdin()
                self.stdout = self
                self.stderr = FakeStderr()
                self.killed = False

            async def readline(self):
                # 抛出一个通用异常
                raise ValueError("Unexpected error during readline")

            def kill(self):
                self.killed = True

            async def wait(self):
                return 0
        
        fake_process = ExceptionFakeProcess()

        with patch("asyncio.create_subprocess_exec", return_value=fake_process):
            events = []
            async for event in runner._run_streaming(["codex", "exec"], "prompt"):
                events.append(event)

        # 验证错误事件
        assert len(events) == 1
        assert events[0].type == EventType.ERROR
        assert "execution error" in str(events[0].data).lower()
        # 验证进程被 kill
        assert fake_process.killed is True

    async def test_run_streaming_ignores_lifecycle_events(self):
        """测试忽略生命周期事件（覆盖行341-343, 375-377）"""
        runner = AsyncCliRunner(command=["codex", "exec"])
        lines = [
            '{"type":"thread.started","thread_id":"abc"}\n',  # 应被忽略
            '{"type":"turn.started"}\n',  # 应被忽略
            '{"type":"item.started","item":{"id":"123","type":"agent_message"}}\n',  # 应被忽略
            '{"type":"item.completed","item":{"type":"agent_message","text":"Hello"}}\n',
            '{"type":"turn.completed","usage":{"total_tokens":3}}\n',
        ]
        fake_process = FakeProcess(lines)

        with patch("asyncio.create_subprocess_exec", return_value=fake_process):
            events = []
            async for event in runner._run_streaming(["codex", "exec"], "prompt"):
                events.append(event)

        # 验证只有实际有效的事件被产生
        assert [e.type for e in events] == [
            EventType.CONTENT_DELTA,
            EventType.CONTENT_COMPLETE,
            EventType.DONE,
        ]
        assert events[0].data == "Hello"

    async def test_call_agents_md_write_failure_emits_error_event(self, tmp_path):
        """测试 call() 在 AGENTS.md 写入失败时产生 error_event"""
        runner = AsyncCliRunner(command=["echo"], working_dir=tmp_path)
        messages: list[AgentMessage] = [
            {"role": "system", "content": "You are a helper"},
            *_messages("hello"),
        ]

        # mock _format_messages 返回失败标志
        def mock_format_failure(msgs):
            return "test", False

        with patch.object(runner, "_format_messages", side_effect=mock_format_failure):
            events = []
            async for event in runner.call(messages):
                events.append(event)

        # 验证产生 error_event
        assert len(events) == 1
        assert events[0].type == EventType.ERROR
        assert "AGENTS.md" in str(events[0].data)
