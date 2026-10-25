"""工具结果 contract 辅助模块。

该模块是 Engine 内部关于工具结果信封的 **唯一真源**，负责三件事：

1. **装信封** — 构造单层 ``ok / value / error`` 结果。
2. **拆信封** — 统一解释"真正成功 / 失败"的语义。
3. **LLM 投影** — 将内部信封投影为 LLM 最优的扁平 JSON。

内部信封格式（Engine 内部流通）::

    成功: {"ok": True, "value": <any>, "truncation": {...}|None, "meta": {...}|None}
    失败: {"ok": False, "error": "<code>", "message": "...", "hint": "...", "meta": {...}|None}

LLM-facing 格式（``project_for_llm`` 输出）::

    成功 dict:  {**value, "truncation"?: ..., "tool_calls_remaining"?: N}
    成功 text:  {"content": "...", "truncation"?: ..., "tool_calls_remaining"?: N}
    失败:       {"error": "<code>", "message": "...", "hint": "..."}

设计目标：
- ToolRegistry / Runner / Agent / ToolTrace 对工具结果的理解完全一致；
- LLM 零嵌套、零冗余字段即可区分成功 / 失败 / 截断；
- 所有信封逻辑集中在本模块，避免后续漂移。
"""

from __future__ import annotations

import base64
import json
from typing import Any, Optional, TypeAlias


JsonSafeScalar: TypeAlias = str | int | float | bool | None
JsonSafeValue: TypeAlias = (
    JsonSafeScalar
    | list["JsonSafeValue"]
    | dict[str, "JsonSafeValue"]
)


# ---------------------------------------------------------------------------
# 装信封
# ---------------------------------------------------------------------------

def build_success(
    value: Any,
    *,
    truncation: Optional[dict[str, Any]] = None,
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """构建统一的工具成功结果信封。

    Args:
        value: 工具返回的业务数据（dict / str / list / ...）。
        truncation: 可选截断信息字典。
        meta: 可选元信息字典。

    Returns:
        ``{"ok": True, "value": value, ...}``。
    """
    result: dict[str, Any] = {
        "ok": True,
        "value": value,
    }
    if truncation:
        result["truncation"] = truncation
    if meta:
        result["meta"] = meta
    return result


def build_error(
    code: str,
    message: str,
    *,
    hint: str = "",
    meta: Optional[dict[str, Any]] = None,
    **extra: Any,
) -> dict[str, Any]:
    """构建统一的工具失败结果信封。

    Args:
        code: 错误码（对应 ``ErrorCode`` 枚举值或大写基础设施码）。
        message: 人类可读的错误说明。
        hint: LLM 可执行的恢复建议（可选）。
        meta: 可选元信息字典。
        **extra: 附加上下文（如 ``retryable``、``detail``），合并到顶层。

    Returns:
        ``{"ok": False, "error": code, "message": message, ...}``。
    """
    result: dict[str, Any] = {
        "ok": False,
        "error": code,
        "message": message,
    }
    if hint:
        result["hint"] = hint
    if extra:
        result.update(extra)
    if meta:
        result["meta"] = meta
    return result


# ---------------------------------------------------------------------------
# 拆信封
# ---------------------------------------------------------------------------

def is_tool_success(result: Any) -> bool:
    """按统一口径判断工具结果是否真正成功。

    规则：``result.get("ok") is True`` 即为成功。

    Args:
        result: 工具结果对象。

    Returns:
        统一语义下的成功布尔值。
    """
    if not isinstance(result, dict):
        return False
    if result.get("ok") is not True:
        return False
    return "value" in result


def get_error_code(result: Any) -> Optional[str]:
    """提取错误码。

    Args:
        result: 工具结果对象。

    Returns:
        ``result["error"]`` 字符串；成功结果返回 ``None``。
    """
    if not isinstance(result, dict):
        return None
    if result.get("ok") is not False:
        return None
    code = result.get("error")
    if isinstance(code, str) and code.strip():
        return code.strip()
    return None


def get_error_message(result: Any) -> Optional[str]:
    """提取错误消息。

    Args:
        result: 工具结果对象。

    Returns:
        ``result["message"]`` 字符串；成功结果返回 ``None``。
    """
    if not isinstance(result, dict):
        return None
    if result.get("ok") is not False:
        return None
    message = result.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return None


def get_value(result: object) -> object | None:
    """提取成功结果的业务数据。

    Args:
        result: 工具结果对象。

    Returns:
        ``result["value"]``；失败或非法结果返回 ``None``。
    """
    if not isinstance(result, dict):
        return None
    if result.get("ok") is not True or "value" not in result:
        return None
    return result.get("value")


def validate_tool_result_contract(result: Any) -> Optional[str]:
    """校验工具结果是否符合 Engine 唯一合法信封格式。

    Args:
        result: 待校验的工具结果对象。

    Returns:
        ``None`` 表示合法；否则返回错误说明字符串。
    """
    if not isinstance(result, dict):
        return "tool result must be dict"
    ok = result.get("ok")
    if not isinstance(ok, bool):
        return 'tool result must contain boolean field "ok"'

    meta = result.get("meta")
    if meta is not None and not isinstance(meta, dict):
        return 'tool result field "meta" must be dict'

    truncation = result.get("truncation")
    if truncation is not None and not isinstance(truncation, dict):
        return 'tool result field "truncation" must be dict'

    if ok:
        if "value" not in result:
            return 'successful tool result must contain field "value"'
        return None

    error = result.get("error")
    if not isinstance(error, str) or not error.strip():
        return 'failed tool result must contain non-empty string field "error"'
    message = result.get("message")
    if not isinstance(message, str) or not message.strip():
        return 'failed tool result must contain non-empty string field "message"'
    hint = result.get("hint")
    if hint is not None and not isinstance(hint, str):
        return 'tool result field "hint" must be string'
    return None


# ---------------------------------------------------------------------------
# LLM 投影
# ---------------------------------------------------------------------------

_LLM_TRUNCATION_KEYS = ("next_action", "fetch_more_args")


def _encode_binary_value(value: bytes | bytearray) -> dict[str, Any]:
    """将二进制值编码为 LLM 可消费的 base64 结构。"""
    return {
        "content_base64": base64.b64encode(bytes(value)).decode("ascii"),
        "content_encoding": "base64",
    }


def _sort_set_items(value: set[Any]) -> list[Any]:
    """对集合进行稳定排序，避免投影输出不稳定。"""
    normalized = [_make_json_safe(item) for item in value]
    return sorted(
        normalized,
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str),
    )


def _make_json_safe(value: object) -> JsonSafeValue:
    """递归将任意值转换为 JSON-safe 结构。

    Args:
        value: 原始值。

    Returns:
        仅由 JSON 标量、列表和对象组成的安全结构。

    Raises:
        无。
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return _encode_binary_value(value)
    if isinstance(value, tuple):
        return [_make_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_make_json_safe(item) for item in value]
    if isinstance(value, set):
        return _sort_set_items(value)
    if isinstance(value, dict):
        normalized: dict[str, JsonSafeValue] = {}
        for key, item in value.items():
            normalized[str(key)] = _make_json_safe(item)
        return normalized
    return str(value)


def project_for_llm(
    result: dict[str, Any],
    *,
    budget: Optional[int] = None,
) -> dict[str, Any]:
    """将内部信封投影为 LLM 最优的扁平 JSON。

    投影规则：

    1. ``ok=False`` → ``{"error": code, "message": msg, "hint": hint}``
    2. ``ok=True, value is dict`` → ``{**value}``
    3. ``ok=True, value is non-dict`` → ``{"content": value}``
    4. 有 truncation → 追加 ``{"truncation": {"next_action": ..., "fetch_more_args": ...}}``
    5. budget 非 None → 追加 ``{"tool_calls_remaining": budget}``

    Args:
        result: 内部信封字典。
        budget: 剩余工具调用轮次（可选）。

    Returns:
        扁平化的 LLM-facing 字典。
    """
    if contract_error := validate_tool_result_contract(result):
        proj: dict[str, Any] = {
            "error": "invalid_result",
            "message": contract_error,
        }
        if budget is not None:
            proj["tool_calls_remaining"] = budget
        return proj

    if result.get("ok") is not True:
        # 错误投影
        proj: dict[str, Any] = {"error": result.get("error", "UNKNOWN")}
        if msg := result.get("message"):
            proj["message"] = msg
        if hint := result.get("hint"):
            proj["hint"] = hint
        if budget is not None:
            proj["tool_calls_remaining"] = budget
        return proj

    # 成功投影
    value = result.get("value")
    if isinstance(value, dict):
        safe_value = _make_json_safe(value)
        if isinstance(safe_value, dict):
            proj = safe_value
        else:
            proj = {"content": safe_value}
    elif isinstance(value, (bytes, bytearray)):
        proj = _encode_binary_value(value)
    else:
        proj = {"content": _make_json_safe(value)}

    # 截断投影：仅保留 LLM 可执行字段
    truncation = result.get("truncation")
    if isinstance(truncation, dict):
        llm_trunc = {k: truncation[k] for k in _LLM_TRUNCATION_KEYS if k in truncation}
        if llm_trunc:
            proj["truncation"] = llm_trunc

    if budget is not None:
        proj["tool_calls_remaining"] = budget
    return proj
