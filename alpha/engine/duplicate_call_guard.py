"""重复工具调用保护组件。

该模块负责封装跨轮次重复调用检测逻辑，避免把 signature / fingerprint /
streak / polling 特化策略全部堆在 ``AsyncAgent`` 主循环中。

职责边界：
- 输入：工具名、参数、结构化结果、可选 ``DupCallSpec``。
- 输出：结构化决策（继续 / 注入提示 / 提前停止）。
- 不负责：warning event 产出、消息注入、fallback orchestration。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .tool_contracts import DupCallSpec


@dataclass
class DuplicateCallDecision:
    """重复调用判定结果。

    Args:
        emit_hint: 是否应向模型注入“复用已有结果”的软提醒。
        hint_tool_name: 触发提示的工具名。
        hard_stop: 是否应触发提前停止。
        reason: 提前停止原因。

    Returns:
        无。

    Raises:
        无。
    """

    emit_hint: bool = False
    hint_tool_name: Optional[str] = None
    hard_stop: bool = False
    reason: Optional[str] = None


@dataclass
class DuplicateCallGuard:
    """重复调用保护状态机。

    Args:
        max_duplicate_tool_calls: 连续“无信息增量重复”允许次数上限。

    Returns:
        无。

    Raises:
        无。
    """

    max_duplicate_tool_calls: int
    _tool_result_fingerprints: dict[str, set[str]] = field(default_factory=dict)
    _duplicate_no_gain_streaks: dict[str, int] = field(default_factory=dict)
    _duplicate_hint_sent_signatures: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        """保护重复调用阈值下界。"""

        self.max_duplicate_tool_calls = max(1, int(self.max_duplicate_tool_calls or 1))

    def evaluate(
        self,
        *,
        tool_name: str,
        arguments: Any,
        result: Any,
        spec: Optional[DupCallSpec],
    ) -> DuplicateCallDecision:
        """评估单次工具结果是否触发重复调用保护。

        Args:
            tool_name: 工具名称。
            arguments: 工具参数。
            result: 结构化工具结果。
            spec: 可选重复调用策略声明。

        Returns:
            判定结果。

        Raises:
            无。
        """

        signature = _make_tool_signature(tool_name, arguments)
        if not signature:
            return DuplicateCallDecision()

        stable_result = _extract_stable_tool_result(result)
        result_fingerprint = _make_result_fingerprint(stable_result)
        fingerprints = self._tool_result_fingerprints.setdefault(signature, set())
        duplicated_without_gain = result_fingerprint in fingerprints
        fingerprints.add(result_fingerprint)

        if _is_polling_in_non_terminal_state(spec=spec, result=result):
            self._duplicate_no_gain_streaks[signature] = 0
            self._duplicate_hint_sent_signatures.discard(signature)
            return DuplicateCallDecision()

        if duplicated_without_gain:
            next_streak = self._duplicate_no_gain_streaks.get(signature, 0) + 1
            self._duplicate_no_gain_streaks[signature] = next_streak
        else:
            self._duplicate_no_gain_streaks[signature] = 0
            self._duplicate_hint_sent_signatures.discard(signature)
            return DuplicateCallDecision()

        decision = DuplicateCallDecision()
        streak = self._duplicate_no_gain_streaks[signature]
        if streak == 1 and signature not in self._duplicate_hint_sent_signatures:
            decision.emit_hint = True
            decision.hint_tool_name = tool_name
            self._duplicate_hint_sent_signatures.add(signature)

        if streak >= self.max_duplicate_tool_calls:
            decision.hard_stop = True
            decision.reason = (
                f"检测到重复的工具调用且无信息增量: {tool_name} "
                f"(连续 {streak} 次)"
            )
        return decision


def _make_tool_signature(name: str, arguments: Any) -> str:
    """构造工具调用签名。

    Args:
        name: 工具名称。
        arguments: 工具参数。

    Returns:
        规范化签名；工具名为空时返回空字符串。

    Raises:
        无。
    """

    if not name:
        return ""
    if isinstance(arguments, str):
        args_text = arguments
    else:
        try:
            args_text = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            args_text = str(arguments)
    return f"{name}:{args_text}"


def _extract_stable_tool_result(result: object) -> object:
    """提取用于“信息增量判断”的稳定结果结构。

    Args:
        result: 工具调用结果原始对象。

    Returns:
        仅包含稳定语义字段的结构。

    Raises:
        无。
    """

    if not isinstance(result, dict):
        return result
    return {
        "ok": result.get("ok"),
        "value": result.get("value"),
        "error": result.get("error"),
        "message": result.get("message"),
        "truncation": result.get("truncation"),
    }


def _make_result_fingerprint(result: Any) -> str:
    """生成工具结果指纹。

    Args:
        result: 需要计算指纹的对象。

    Returns:
        SHA256 十六进制摘要字符串。

    Raises:
        无。
    """

    try:
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        payload = str(result)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_polling_in_non_terminal_state(*, spec: Optional[DupCallSpec], result: Any) -> bool:
    """判断轮询型工具当前是否处于未终态。

    Args:
        spec: 可选重复调用策略声明。
        result: 结构化工具结果。

    Returns:
        当前调用是否应被视为“允许重复轮询”。

    Raises:
        无。
    """

    if spec is None or spec.mode != "poll_until_terminal":
        return False
    payload = _extract_business_payload(result)
    status_value = _get_value_by_path(payload, spec.status_path or "")
    if status_value is None:
        return False
    normalized_status = str(status_value).strip()
    if not normalized_status:
        return False
    return normalized_status not in set(spec.terminal_values or [])


def _extract_business_payload(result: object) -> object:
    """从结构化工具结果中提取业务载荷。

    Args:
        result: 工具结果。

    Returns:
        优先返回 ``data.value``；无法提取时返回原对象。

    Raises:
        无。
    """

    if not isinstance(result, dict):
        return result
    if "value" in result:
        return result["value"]
    return result


def _get_value_by_path(payload: object, path: str) -> object | None:
    """按点路径读取嵌套字段。

    Args:
        payload: 原始载荷。
        path: 点路径，例如 ``"job.status"``。

    Returns:
        命中的字段值；任一路径缺失时返回 ``None``。

    Raises:
        无。
    """

    normalized_path = str(path or "").strip()
    if not normalized_path:
        return None
    current = payload
    for part in normalized_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current.get(part)
    return current
