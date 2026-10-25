"""独立宿主操作规格的严格 JSON 快照编码。"""

import json
from typing import Literal, cast

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.execution_metadata import normalize_execution_delivery_context
from alpha.contracts.host_execution import ConcurrencyAcquirePolicy, HostedRunSpec

_POLICY_MODES = ("host_default", "timeout", "unbounded")


def serialize_hosted_operation(spec: HostedRunSpec) -> str:
    """编码独立操作。参数：已接受规格。返回：确定 JSON。异常：规格不能序列化。"""
    payload: dict[str, JsonValue] = {
        "operation_name": spec.operation_name, "session_id": spec.session_id, "scene_name": spec.scene_name,
        "metadata": cast(dict[str, JsonValue], spec.metadata), "business_concurrency_lane": spec.business_concurrency_lane,
        "timeout_ms": spec.timeout_ms, "publish_events": spec.publish_events, "error_summary_limit": spec.error_summary_limit,
        "concurrency_acquire_policy": {"mode": spec.concurrency_acquire_policy.mode, "timeout_seconds": spec.concurrency_acquire_policy.timeout_seconds},
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _optional_text(value: JsonValue) -> str | None:
    """解码可空文本。参数：JSON。返回：文本或空。异常：类型非法。"""
    if value is not None and not isinstance(value, str):
        raise ValueError("宿主操作快照文本字段损坏")
    return value


def _integer(value: JsonValue) -> int:
    """解码整数。参数：JSON。返回：整数。异常：类型非法。"""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("宿主操作快照整数损坏")
    return value


def deserialize_hosted_operation(encoded: str) -> HostedRunSpec:
    """恢复原操作规格。参数：已保存 JSON。返回：规格。异常：快照字段损坏。"""
    payload = cast(JsonValue, json.loads(encoded))
    if not isinstance(payload, dict):
        raise ValueError("宿主操作快照不是对象")
    policy = payload.get("concurrency_acquire_policy")
    metadata = payload.get("metadata")
    if not isinstance(policy, dict) or not isinstance(metadata, dict) or not isinstance(payload.get("publish_events"), bool):
        raise ValueError("宿主操作快照配置损坏")
    mode = policy.get("mode")
    timeout = policy.get("timeout_seconds")
    if mode not in _POLICY_MODES or not isinstance(mode, str) or (timeout is not None and (not isinstance(timeout, (int, float)) or isinstance(timeout, bool))):
        raise ValueError("宿主操作并发策略损坏")
    name = _optional_text(payload.get("operation_name"))
    if not name:
        raise ValueError("宿主操作名称缺失")
    return HostedRunSpec(
        operation_name=name, session_id=_optional_text(payload.get("session_id")), scene_name=_optional_text(payload.get("scene_name")),
        metadata=normalize_execution_delivery_context(metadata), business_concurrency_lane=_optional_text(payload.get("business_concurrency_lane")),
        concurrency_acquire_policy=ConcurrencyAcquirePolicy(cast(Literal["host_default", "timeout", "unbounded"], mode), float(timeout) if timeout is not None else None),
        timeout_ms=_integer(payload["timeout_ms"]) if payload.get("timeout_ms") is not None else None,
        publish_events=cast(bool, payload["publish_events"]), error_summary_limit=_integer(payload.get("error_summary_limit")),
    )
