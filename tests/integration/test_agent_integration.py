"""
AsyncAgent 集成测试 - 使用真实 ToolRegistry 和文件系统

测试策略：
- 使用真实 ToolRegistry + 文档工具
- 使用自定义 Runner 产出事件流，驱动 Agent 工具回填逻辑
"""
import json
from unittest.mock import Mock

import pytest

from alpha.engine import AsyncAgent
from alpha.engine import register_doc_tools
from alpha.engine import (
    content_complete,
    content_delta,
    done_event,
    tool_call_dispatched,
    tool_call_result,
    tool_calls_batch_done,
    tool_calls_batch_ready,
)
from alpha.engine import ToolRegistry


class ToolFlowRunner:
    def __init__(self, tool_executor, file_path: str):
        self.tool_executor = tool_executor
        self.file_path = file_path
        self.calls = []
        self.iteration = 0

    def is_supports_tool_calling(self):
        return False

    def set_tools(self, *args, **kwargs):
        return None

    async def close(self) -> None:
        """关闭 Runner（桩实现，无操作）。"""
        return None

    async def call(self, messages, stream=True, **extra_payloads):
        self.calls.append(messages)
        if self.iteration == 0:
            tool_name = "read_file"
            tool_call_id = "call_1"
            tool_args = {
                "file_path": self.file_path,
                "start_line": 1,
                "end_line": 5,
            }
            yield content_complete("")
            yield tool_call_dispatched(
                tool_call_id=tool_call_id,
                name=tool_name,
                arguments=json.dumps(tool_args),
                index_in_iteration=0,
            )
            yield tool_calls_batch_ready([tool_call_id])
            result = self.tool_executor.execute(tool_name, tool_args)
            yield tool_call_result(
                tool_call_id,
                result,
                name=tool_name,
                arguments=json.dumps(tool_args),
                index_in_iteration=0,
            )
            yield tool_calls_batch_done([tool_call_id], ok=1, error=0, timeout=0, cancelled=0)
            yield done_event(summary={"tool_calls": 1})
        else:
            yield content_delta("done")
            yield content_complete("done")
            yield done_event(summary={"tool_calls": 0})
        self.iteration += 1


class MultiToolRunner:
    def __init__(self, tool_executor, directory: str, file_path: str):
        self.tool_executor = tool_executor
        self.directory = directory
        self.file_path = file_path
        self.calls = []
        self.iteration = 0

    def supports_tools(self):
        return self.is_supports_tool_calling()

    def is_supports_tool_calling(self):
        return False

    def set_tools(self, *args, **kwargs):
        return None

    async def close(self) -> None:
        """关闭 Runner（桩实现，无操作）。"""
        return None

    async def call(self, messages, stream=True, **extra_payloads):
        self.calls.append(messages)
        if self.iteration == 0:
            tool_calls = [
                ("call_1", "list_files", {"directory": self.directory, "pattern": "*.txt", "recursive": False}),
                (
                    "call_2",
                    "read_file",
                    {
                        "file_path": self.file_path,
                        "start_line": 1,
                        "end_line": 5,
                    },
                ),
            ]
            yield content_complete("")
            for index_in_iteration, (tool_call_id, tool_name, tool_args) in enumerate(tool_calls):
                yield tool_call_dispatched(
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    arguments=json.dumps(tool_args),
                    index_in_iteration=index_in_iteration,
                )
            yield tool_calls_batch_ready([tool_call_id for tool_call_id, _, _ in tool_calls])
            for index_in_iteration, (tool_call_id, tool_name, tool_args) in enumerate(tool_calls):
                result = self.tool_executor.execute(tool_name, tool_args)
                yield tool_call_result(
                    tool_call_id,
                    result,
                    name=tool_name,
                    arguments=json.dumps(tool_args),
                    index_in_iteration=index_in_iteration,
                )
            yield tool_calls_batch_done(
                [tool_call_id for tool_call_id, _, _ in tool_calls],
                ok=2,
                error=0,
                timeout=0,
                cancelled=0,
            )
            yield done_event(summary={"tool_calls": 2})
        else:
            yield content_delta("all done")
            yield content_complete("all done")
            yield done_event(summary={"tool_calls": 0})
        self.iteration += 1


@pytest.mark.integration
class TestAsyncAgentWithRealTools:
    """测试 AsyncAgent 与真实工具集成"""

    @pytest.mark.asyncio
    async def test_agent_reads_real_file_successfully(self, tmp_path):
        """集成场景1：Agent 通过工具读取真实文件"""
        test_file = tmp_path / "data.txt"
        test_file.write_text("Important data: 12345", encoding="utf-8")

        registry = ToolRegistry()
        registry.register_allowed_paths([tmp_path])
        register_doc_tools(registry)

        runner = ToolFlowRunner(registry, str(test_file))
        from alpha.engine.async_agent import AgentRunningConfig
        config = AgentRunningConfig(max_iterations=3)
        agent = AsyncAgent(runner=runner, tool_executor=registry, running_config=config)

        events = []
        async for event in agent.run("What's in data.txt?"):
            events.append(event)

        assert runner.calls
        assert len(runner.calls) == 2
        tool_messages = [m for m in runner.calls[1] if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        assert "12345" in tool_messages[0].get("content", "")

    @pytest.mark.asyncio
    async def test_agent_multiple_tool_calls_workflow(self, tmp_path):
        """集成场景2：Agent 一轮内多次工具调用"""
        (tmp_path / "file1.txt").write_text("Content 1", encoding="utf-8")
        (tmp_path / "file2.txt").write_text("Content 2", encoding="utf-8")

        registry = ToolRegistry()
        registry.register_allowed_paths([tmp_path])
        register_doc_tools(registry)

        runner = MultiToolRunner(registry, str(tmp_path), str(tmp_path / "file1.txt"))
        from alpha.engine.async_agent import AgentRunningConfig
        config = AgentRunningConfig(max_iterations=3)
        agent = AsyncAgent(runner=runner, tool_executor=registry, running_config=config)

        async for _ in agent.run("List and read files"):
            pass

        tool_messages = [m for m in runner.calls[1] if m.get("role") == "tool"]
        assert len(tool_messages) == 2
        assert any("file1.txt" in m.get("content", "") for m in tool_messages)

    @pytest.mark.asyncio
    async def test_agent_handles_file_access_error(self, tmp_path):
        """集成场景3：Agent 处理文件访问错误"""
        registry = ToolRegistry()
        registry.register_allowed_paths([tmp_path])
        register_doc_tools(registry)

        missing_path = str(tmp_path / "missing.txt")
        runner = ToolFlowRunner(registry, missing_path)
        from alpha.engine.async_agent import AgentRunningConfig
        config = AgentRunningConfig(max_iterations=2, max_compactions=2)
        agent = AsyncAgent(runner=runner, tool_executor=registry, running_config=config)

        async for _ in agent.run("Read missing file"):
            pass

        tool_messages = [m for m in runner.calls[1] if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        # project_for_llm 将错误投影为 {"error": ..., "message": ...}
        content = tool_messages[0].get("content", "")
        assert "error" in content.lower()
