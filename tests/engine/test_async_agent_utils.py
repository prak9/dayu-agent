# -*- coding: utf-8 -*-
"""AsyncAgent 辅助方法测试"""

from typing import Any, AsyncIterator

from alpha.contracts.agent_types import AgentMessage
from alpha.engine.async_agent import AsyncAgent, AgentRunningConfig
from alpha.engine.duplicate_call_guard import _make_tool_signature
from alpha.engine.events import StreamEvent, EventType


class _DummyRunner:
    def is_supports_tool_calling(self) -> bool:
        return True

    def set_tools(self, executor):
        return None

    async def close(self) -> None:
        return None

    async def call(
        self,
        messages: list[AgentMessage],
        *,
        stream: bool = True,
        **extra_payloads: Any,
    ) -> AsyncIterator[StreamEvent]:
        _ = (messages, stream, extra_payloads)
        if False:
            yield StreamEvent(type=EventType.DONE, data=None)


def test_make_tool_signature_dict():
    sig = _make_tool_signature("tool", {"b": 2, "a": 1})
    assert sig.startswith("tool:")
    assert "\"a\": 1" in sig


def test_make_tool_signature_string():
    sig = _make_tool_signature("tool", "x=1")
    assert sig == "tool:x=1"


def test_make_tool_signature_empty_name():
    sig = _make_tool_signature("", {"a": 1})
    assert sig == ""


def test_annotate_event_adds_tool_call_id():
    agent = AsyncAgent(_DummyRunner(), running_config=AgentRunningConfig())
    event = StreamEvent(type=EventType.TOOL_CALL_RESULT, data={"id": "tc_1"})
    annotated = agent._annotate_event(event, run_id="run1", iteration_id="iter1")
    assert annotated.metadata["run_id"] == "run1"
    assert annotated.metadata["iteration_id"] == "iter1"
    assert annotated.metadata["tool_call_id"] == "tc_1"
