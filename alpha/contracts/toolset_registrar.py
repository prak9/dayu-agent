"""Toolset registrar 跨层稳定契约。

该模块定义 Host 与各 toolset adapter 之间的稳定调用边界：
- Host 只负责计算本次最终启用哪些 toolset。
- Host 只把通用执行上下文传给 adapter。
- 各 toolset adapter 负责把通用上下文适配成底层 ``register_xxx_tools``
  所需的具体参数。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol, runtime_checkable

from alpha.contracts.agent_execution import ExecutionPermissions
from alpha.contracts.infrastructure import WorkspaceResourcesProtocol
from alpha.contracts.toolset_config import ToolsetConfigSnapshot


@runtime_checkable
class ToolRegistryProtocol(Protocol):
    """Tool 注册表最小协议。"""

    @property
    def tools(self) -> Mapping[str, Callable[..., object]]:
        """返回当前已注册工具映射。"""

        ...

    def register_allowed_paths(self, paths: list[Path]) -> None:
        """注册文件访问白名单。"""

        ...

    def register(self, name: str, func: Callable[..., object], schema: object) -> None:
        """注册单个工具。"""

        ...


@dataclass(frozen=True)
class ToolsetRegistrationContext:
    """Toolset adapter 注册上下文。

    Args:
        toolset_name: 本次要注册的 toolset 名称。
        registry: 目标工具注册表。
        workspace: 工作区稳定资源。
        toolset_config: 当前 toolset 生效的通用配置快照。
        execution_permissions: 当前执行的动态权限。
        tool_timeout_seconds: 当前工具调用预算秒数。

    Returns:
        无。

    Raises:
        无。
    """

    toolset_name: str
    registry: ToolRegistryProtocol
    workspace: WorkspaceResourcesProtocol
    toolset_config: ToolsetConfigSnapshot | None
    execution_permissions: ExecutionPermissions
    tool_timeout_seconds: float | None


@runtime_checkable
class ToolsetRegistrarProtocol(Protocol):
    """Toolset adapter 协议。"""

    def __call__(self, context: ToolsetRegistrationContext) -> int:
        """按上下文注册一个 toolset。

        Args:
            context: 当前 toolset 注册上下文。

        Returns:
            实际注册的工具数量。

        Raises:
            Exception: 当 toolset 注册失败时，由实现方抛出具体异常。
        """

        ...


__all__ = [
    "ToolRegistryProtocol",
    "ToolsetRegistrarProtocol",
    "ToolsetRegistrationContext",
]