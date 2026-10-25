"""Prompt Contributions slot 收口辅助。

该模块提供 Service 与 Host 共用的纯函数，用于按 scene manifest
声明的 ``context_slots`` 收口动态 prompt 片段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class PromptContributionSelection:
    """按 scene manifest 收口后的 Prompt Contributions。

    Args:
        selected_contributions: 当前 scene 允许进入 prompt 组装的动态片段。
        ignored_slots: 当前 scene 未声明、因此被忽略的 slot 名称。

    Returns:
        无。

    Raises:
        无。
    """

    selected_contributions: dict[str, str] = field(default_factory=dict)
    ignored_slots: tuple[str, ...] = ()


def select_prompt_contributions(
    *,
    prompt_contributions: Mapping[str, str] | None,
    context_slots: tuple[str, ...],
) -> PromptContributionSelection:
    """按 scene manifest 声明筛选动态 prompt 片段。

    Args:
        prompt_contributions: 候选动态 prompt 片段。
        context_slots: scene manifest 声明允许的 slot 顺序。

    Returns:
        收口后的动态片段，以及被忽略的冗余 slot 列表。

    Raises:
        无。
    """

    if not prompt_contributions:
        return PromptContributionSelection()
    allowed_slots = set(context_slots)
    selected_contributions: dict[str, str] = {}
    for slot_name in context_slots:
        raw = prompt_contributions.get(slot_name)
        if raw is None:
            continue
        selected_contributions[slot_name] = str(raw)
    ignored_slots = tuple(sorted(slot_name for slot_name in prompt_contributions if slot_name not in allowed_slots))
    return PromptContributionSelection(
        selected_contributions=selected_contributions,
        ignored_slots=ignored_slots,
    )


__all__ = [
    "PromptContributionSelection",
    "select_prompt_contributions",
]