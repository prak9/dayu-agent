"""Prompt 装配阶段可见的工具快照模型。"""

from __future__ import annotations

from dataclasses import dataclass

from alpha.contracts.protocols import PromptToolCatalogProtocol


@dataclass(frozen=True)
class PromptToolSnapshot:
    """Prompt 装配所需的工具与环境快照。

    Args:
        tool_names: 当前已注册工具名集合。
        tool_tags: 当前已注册工具标签集合。
        allowed_paths: 工具允许访问的路径列表。
        supports_tool_calling: 当前模型是否支持工具调用。
    """

    tool_names: frozenset[str] = frozenset()
    tool_tags: frozenset[str] = frozenset()
    allowed_paths: tuple[str, ...] = ()
    supports_tool_calling: bool = False


def build_prompt_tool_snapshot(
    registry: PromptToolCatalogProtocol,
    *,
    supports_tool_calling: bool,
) -> PromptToolSnapshot:
    """根据 ToolRegistry 构建 prompt 工具快照。

    Args:
        registry: 工具注册表。
        supports_tool_calling: 当前模型是否支持工具调用。

    Returns:
        ``PromptToolSnapshot``。

    Raises:
        无。
    """

    return PromptToolSnapshot(
        tool_names=frozenset(registry.get_tool_names()),
        tool_tags=frozenset(registry.get_tool_tags()),
        allowed_paths=tuple(registry.get_allowed_paths()),
        supports_tool_calling=supports_tool_calling,
    )


__all__ = [
    "PromptToolSnapshot",
    "build_prompt_tool_snapshot",
]
