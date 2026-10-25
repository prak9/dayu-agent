"""Alpha 公共契约层。

该包导出跨层稳定契约，但不在包导入时急切加载所有子模块，
避免 `contracts <-> execution` 这类包级循环导入。
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alpha.contracts.cancellation import CancelledError, CancellationToken
    from alpha.contracts.agent_execution import (
        AcceptedExecutionSpec,
        AgentCreateArgs,
        AgentInput,
        ExecutionContract,
        ExecutionHostPolicy,
        ExecutionMessageInputs,
        ExecutionPermissions,
        ScenePreparationSpec,
    )
    from alpha.contracts.agent_types import AgentMessage, AgentRuntimeLimits, AgentTraceIdentity
    from alpha.contracts.events import AppEvent, AppEventType, AppResult
    from alpha.contracts.execution_metadata import ExecutionDeliveryContext
    from alpha.contracts.fins import FinsCommand, FinsEvent, FinsEventType, FinsResult
    from alpha.contracts.model_config import ModelConfig, RunnerParams
    from alpha.contracts.protocols import (
        DupCallSpecProtocol,
        ToolExecutor,
        ToolTraceRecorder,
        ToolTraceRecorderFactory,
    )
    from alpha.contracts.reply_outbox import ReplyOutboxRecord, ReplyOutboxState, ReplyOutboxSubmitRequest
    from alpha.contracts.run import RunRecord, RunState
    from alpha.contracts.session import SessionRecord, SessionSource, SessionState


_EXPORT_MAP: dict[str, tuple[str, str]] = {
    "CancelledError": ("alpha.contracts.cancellation", "CancelledError"),
    "CancellationToken": ("alpha.contracts.cancellation", "CancellationToken"),
    "AcceptedExecutionSpec": ("alpha.contracts.agent_execution", "AcceptedExecutionSpec"),
    "AgentCreateArgs": ("alpha.contracts.agent_execution", "AgentCreateArgs"),
    "AgentInput": ("alpha.contracts.agent_execution", "AgentInput"),
    "ExecutionContract": ("alpha.contracts.agent_execution", "ExecutionContract"),
    "ExecutionHostPolicy": ("alpha.contracts.agent_execution", "ExecutionHostPolicy"),
    "ExecutionMessageInputs": ("alpha.contracts.agent_execution", "ExecutionMessageInputs"),
    "ExecutionPermissions": ("alpha.contracts.agent_execution", "ExecutionPermissions"),
    "ScenePreparationSpec": ("alpha.contracts.agent_execution", "ScenePreparationSpec"),
    "AgentMessage": ("alpha.contracts.agent_types", "AgentMessage"),
    "AgentRuntimeLimits": ("alpha.contracts.agent_types", "AgentRuntimeLimits"),
    "AgentTraceIdentity": ("alpha.contracts.agent_types", "AgentTraceIdentity"),
    "ExecutionDeliveryContext": ("alpha.contracts.execution_metadata", "ExecutionDeliveryContext"),
    "ModelConfig": ("alpha.contracts.model_config", "ModelConfig"),
    "RunnerParams": ("alpha.contracts.model_config", "RunnerParams"),
    "DupCallSpecProtocol": ("alpha.contracts.protocols", "DupCallSpecProtocol"),
    "ToolExecutor": ("alpha.contracts.protocols", "ToolExecutor"),
    "ToolTraceRecorder": ("alpha.contracts.protocols", "ToolTraceRecorder"),
    "ToolTraceRecorderFactory": ("alpha.contracts.protocols", "ToolTraceRecorderFactory"),
    "AppEvent": ("alpha.contracts.events", "AppEvent"),
    "AppEventType": ("alpha.contracts.events", "AppEventType"),
    "AppResult": ("alpha.contracts.events", "AppResult"),
    "FinsCommand": ("alpha.contracts.fins", "FinsCommand"),
    "FinsEvent": ("alpha.contracts.fins", "FinsEvent"),
    "FinsEventType": ("alpha.contracts.fins", "FinsEventType"),
    "FinsResult": ("alpha.contracts.fins", "FinsResult"),
    "ReplyOutboxRecord": ("alpha.contracts.reply_outbox", "ReplyOutboxRecord"),
    "ReplyOutboxState": ("alpha.contracts.reply_outbox", "ReplyOutboxState"),
    "ReplyOutboxSubmitRequest": ("alpha.contracts.reply_outbox", "ReplyOutboxSubmitRequest"),
    "RunRecord": ("alpha.contracts.run", "RunRecord"),
    "RunState": ("alpha.contracts.run", "RunState"),
    "SessionRecord": ("alpha.contracts.session", "SessionRecord"),
    "SessionSource": ("alpha.contracts.session", "SessionSource"),
    "SessionState": ("alpha.contracts.session", "SessionState"),
}


def __getattr__(name: str) -> object:
    """按需加载公共契约导出。

    Args:
        name: 导出名称。

    Returns:
        对应的导出对象。

    Raises:
        AttributeError: 名称不存在时抛出。
    """

    export = _EXPORT_MAP.get(name)
    if export is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = export
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """返回模块可见导出列表。

    Args:
        无。

    Returns:
        排序后的名称列表。

    Raises:
        无。
    """

    return sorted(list(globals().keys()) + list(__all__))

__all__ = [
    "CancelledError",
    "CancellationToken",
    "AgentCreateArgs",
    "AgentInput",
    "AgentMessage",
    "AgentRuntimeLimits",
    "AgentTraceIdentity",
    "AcceptedExecutionSpec",
    "ExecutionDeliveryContext",
    "ModelConfig",
    "RunnerParams",
    "DupCallSpecProtocol",
    "ToolExecutor",
    "ToolTraceRecorder",
    "ToolTraceRecorderFactory",
    "AppEvent",
    "AppEventType",
    "AppResult",
    "ExecutionContract",
    "ExecutionHostPolicy",
    "ExecutionMessageInputs",
    "ExecutionPermissions",
    "ScenePreparationSpec",
    "FinsCommand",
    "FinsEvent",
    "FinsEventType",
    "FinsResult",
    "ReplyOutboxRecord",
    "ReplyOutboxState",
    "ReplyOutboxSubmitRequest",
    # Run / Session 数据模型
    "RunRecord",
    "RunState",
    "SessionRecord",
    "SessionSource",
    "SessionState",
]
