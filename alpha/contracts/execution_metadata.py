"""执行交付上下文公共契约。

该模块定义 Service -> Host -> UI 恢复链路里会跨层传播的最小交付上下文，
避免在 ExecutionContract.metadata 与 pending turn 元数据上继续使用无约束字典袋子。
"""

from __future__ import annotations

from typing import Mapping, cast

from typing_extensions import TypedDict


class ExecutionDeliveryContext(TypedDict, total=False):
    """跨层传播的交付上下文。"""

    delivery_channel: str
    delivery_target: str
    delivery_thread_id: str
    delivery_group_id: str
    interactive_key: str
    chat_key: str
    wechat_runtime_identity: str
    filtered: bool


def empty_execution_delivery_context() -> ExecutionDeliveryContext:
    """返回空的交付上下文。

    Args:
        无。

    Returns:
        空的交付上下文字典。

    Raises:
        无。
    """

    return cast(ExecutionDeliveryContext, {})


def normalize_execution_delivery_context(
    context: Mapping[str, object] | None,
) -> ExecutionDeliveryContext:
    """规范化执行交付上下文。

    Args:
        context: 原始交付上下文。

    Returns:
        仅保留稳定键且值为非空字符串的交付上下文。

    Raises:
        无。
    """

    if context is None:
        return {}

    normalized: ExecutionDeliveryContext = {}
    delivery_channel = _normalize_context_value(context.get("delivery_channel"))
    if delivery_channel:
        normalized["delivery_channel"] = delivery_channel

    delivery_target = _normalize_context_value(context.get("delivery_target"))
    if delivery_target:
        normalized["delivery_target"] = delivery_target

    delivery_thread_id = _normalize_context_value(context.get("delivery_thread_id"))
    if delivery_thread_id:
        normalized["delivery_thread_id"] = delivery_thread_id

    delivery_group_id = _normalize_context_value(context.get("delivery_group_id"))
    if delivery_group_id:
        normalized["delivery_group_id"] = delivery_group_id

    interactive_key = _normalize_context_value(context.get("interactive_key"))
    if interactive_key:
        normalized["interactive_key"] = interactive_key

    chat_key = _normalize_context_value(context.get("chat_key"))
    if chat_key:
        normalized["chat_key"] = chat_key

    wechat_runtime_identity = _normalize_context_value(context.get("wechat_runtime_identity"))
    if wechat_runtime_identity:
        normalized["wechat_runtime_identity"] = wechat_runtime_identity

    filtered = context.get("filtered")
    if isinstance(filtered, bool):
        normalized["filtered"] = filtered

    return normalized


def _normalize_context_value(value: object) -> str:
    """规范化单个上下文字段值。

    Args:
        value: 原始字段值。

    Returns:
        去除首尾空白后的字符串；空值返回空字符串。

    Raises:
        无。
    """

    return str(value or "").strip()


__all__ = [
    "ExecutionDeliveryContext",
    "empty_execution_delivery_context",
    "normalize_execution_delivery_context",
]