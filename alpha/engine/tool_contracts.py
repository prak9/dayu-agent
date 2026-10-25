"""工具契约与截断策略真源模块。

该模块承载 Engine 级中性工具契约，避免核心运行时依赖
``alpha.engine.tools`` 命名空间中的实现目录。职责包括：

- ``ToolSchema`` / ``ToolFunctionSchema``：OpenAI tools schema 的结构化契约。
- ``ToolTruncateSpec``：工具结果截断声明。
- ``DupCallSpec``：重复调用策略声明。
- ``TRUNCATION_STRATEGIES`` / ``get_strategy_spec``：截断策略元数据真源。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .exceptions import ConfigError

# Strategy -> required limit key, truncation unit, and reason label.
TRUNCATION_STRATEGIES: Dict[str, Dict[str, str]] = {
    "text_chars": {
        "limit_key": "max_chars",
        "unit": "chars",
        "reason": "max_chars",
    },
    "text_lines": {
        "limit_key": "max_lines",
        "unit": "lines",
        # Keep reason aligned with existing protocol vocabulary.
        "reason": "max_items",
    },
    "list_items": {
        "limit_key": "max_items",
        "unit": "items",
        "reason": "max_items",
    },
    "binary_bytes": {
        "limit_key": "max_bytes",
        "unit": "bytes",
        "reason": "max_bytes",
    },
}


def get_strategy_spec(strategy: str) -> Dict[str, str]:
    """返回指定截断策略的元数据。

    Args:
        strategy: 截断策略名称。

    Returns:
        包含 ``limit_key`` / ``unit`` / ``reason`` 的字典；未知策略返回空字典。

    Raises:
        无。
    """

    return TRUNCATION_STRATEGIES.get(strategy, {})


@dataclass
class ToolTruncateSpec:
    """工具截断策略声明。

    Rules:
    - enabled=False means truncation is disabled.
    - enabled=True requires strategy + limits to be fully specified.
    - Each strategy allows exactly one limit key.
    """

    enabled: bool = False
    strategy: Optional[str] = None
    limits: Optional[Dict[str, int]] = None
    target_field: Optional[str] = None
    continuation_hint: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        """校验截断配置是否合法。

        Args:
            无。

        Returns:
            无。

        Raises:
            ConfigError: 配置不满足策略约束时抛出。
        """

        if not self.enabled:
            return
        if not self.strategy:
            raise ConfigError("tool_schema", None, "truncate.strategy is required when enabled")
        if self.strategy not in TRUNCATION_STRATEGIES:
            raise ConfigError("tool_schema", None, f"unsupported truncate.strategy: {self.strategy}")
        if not isinstance(self.limits, dict) or not self.limits:
            raise ConfigError("tool_schema", None, "truncate.limits must be a non-empty dict when enabled")

        limit_key = TRUNCATION_STRATEGIES[self.strategy]["limit_key"]
        if set(self.limits.keys()) != {limit_key}:
            raise ConfigError(
                "tool_schema",
                None,
                f"truncate.limits must contain only '{limit_key}' for strategy '{self.strategy}'",
            )
        limit_value = self.limits.get(limit_key)
        if not isinstance(limit_value, int) or limit_value <= 0:
            raise ConfigError(
                "tool_schema",
                None,
                f"truncate.limits.{limit_key} must be a positive integer",
            )


@dataclass
class DupCallSpec:
    """重复调用策略声明。

    用于描述某个工具在 Agent 侧重复调用保护中的特化行为。该声明
    不进入 OpenAI schema，仅供运行时框架在跨轮推理时消费。

    Args:
        mode: 重复调用策略模式。当前仅支持 ``poll_until_terminal``。
        status_path: 状态字段路径，使用点路径语法，例如 ``"job.status"``。
        terminal_values: 终态枚举值列表，例如 ``["succeeded", "failed"]``。

    Returns:
        无。

    Raises:
        ConfigError: 配置非法时抛出。
    """

    mode: str
    status_path: Optional[str] = None
    terminal_values: Optional[list[str]] = None

    def __post_init__(self) -> None:
        """校验重复调用策略配置。

        Args:
            无。

        Returns:
            无。

        Raises:
            ConfigError: 配置不满足协议要求时抛出。
        """

        normalized_mode = str(self.mode or "").strip()
        if normalized_mode != "poll_until_terminal":
            raise ConfigError(
                "tool_schema",
                None,
                f"unsupported dup_call.mode: {self.mode}",
            )
        self.mode = normalized_mode

        normalized_status_path = str(self.status_path or "").strip()
        if not normalized_status_path:
            raise ConfigError(
                "tool_schema",
                None,
                "dup_call.status_path is required when mode=poll_until_terminal",
            )
        self.status_path = normalized_status_path

        if not isinstance(self.terminal_values, list) or not self.terminal_values:
            raise ConfigError(
                "tool_schema",
                None,
                "dup_call.terminal_values must be a non-empty list when mode=poll_until_terminal",
            )

        normalized_terminal_values: list[str] = []
        for value in self.terminal_values:
            normalized_value = str(value or "").strip()
            if not normalized_value:
                raise ConfigError(
                    "tool_schema",
                    None,
                    "dup_call.terminal_values cannot contain blank values",
                )
            normalized_terminal_values.append(normalized_value)
        self.terminal_values = normalized_terminal_values


@dataclass
class ToolFunctionSchema:
    """OpenAI tool function schema."""

    name: str
    description: str
    parameters: Dict[str, Any]


@dataclass
class ToolSchema:
    """完整工具 schema。

    Attributes:
        function: OpenAI function schema fields.
        type: Tool type, defaults to ``function``.
    """

    function: ToolFunctionSchema
    type: str = "function"

    def to_openai(self) -> Dict[str, Any]:
        """转换为 OpenAI tools schema dict。

        Args:
            无。

        Returns:
            OpenAI tools schema 字典。

        Raises:
            无。
        """

        return {
            "type": self.type,
            "function": {
                "name": self.function.name,
                "description": self.function.description,
                "parameters": self.function.parameters,
            },
        }
