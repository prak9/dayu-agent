"""Prompt 纯装配模块。

该模块只负责基于上层已经准备好的 `PromptAssemblyPlan` 装配最终的
system prompt，不负责读取 prompt 资产，也不负责解析 scene manifest。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .prompt_contribution_slots import select_prompt_contributions
from .prompt_plan import PromptAssemblyPlan, PromptFragmentPlan
from .prompt_renderer import load_prompt
from .tool_snapshot import PromptToolSnapshot


@dataclass(frozen=True)
class PromptComposeContext:
    """Prompt 运行时上下文容器。"""

    values: dict[str, Any] = field(default_factory=dict)

    def select(self, keys: tuple[str, ...]) -> dict[str, Any]:
        """按白名单提取上下文字段。

        Args:
            keys: 允许读取的上下文字段集合。

        Returns:
            过滤后的上下文字典。

        Raises:
            无。
        """

        if not keys:
            return dict(self.values)
        return {key: self.values[key] for key in keys if key in self.values}

    def has_any(self, keys: tuple[str, ...]) -> bool:
        """判断给定上下文字段中是否至少存在一个可用值。

        Args:
            keys: 待检查的上下文字段集合。

        Returns:
            若至少存在一个非空字段则返回 ``True``；空白字符串与 ``None`` 视为不存在。

        Raises:
            无。
        """

        if not keys:
            return True
        for key in keys:
            if key not in self.values:
                continue
            value = self.values[key]
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return True
        return False


@dataclass(frozen=True)
class ComposedPrompt:
    """PromptComposer 输出对象。"""

    name: str
    version: str
    system_message: str
    fragment_ids: tuple[str, ...] = ()
    skipped_fragments: tuple[str, ...] = ()


class PromptRenderer:
    """Prompt 模板纯渲染器。"""

    def render(
        self,
        *,
        template: str,
        variables: Optional[dict[str, Any]] = None,
        tool_snapshot: Optional[PromptToolSnapshot] = None,
    ) -> str:
        """渲染单个模板文本。

        Args:
            template: 模板原文。
            variables: 模板变量。
            tool_snapshot: 工具快照，用于条件块过滤。

        Returns:
            渲染后的文本。

        Raises:
            PromptParseError: 条件块解析失败时抛出。
        """

        snapshot = tool_snapshot or PromptToolSnapshot()
        return load_prompt(
            template,
            variables=variables,
            tool_names=set(snapshot.tool_names),
            tag_names=set(snapshot.tool_tags),
        )


class PromptComposer:
    """基于装配计划组合最终 system message。"""

    def __init__(self, renderer: Optional[PromptRenderer] = None):
        """初始化 PromptComposer。

        Args:
            renderer: 可选渲染器；未提供时使用默认 PromptRenderer。

        Returns:
            无。

        Raises:
            无。
        """

        self._renderer = renderer or PromptRenderer()

    def compose(
        self,
        *,
        plan: PromptAssemblyPlan,
        context: PromptComposeContext,
        tool_snapshot: Optional[PromptToolSnapshot] = None,
        prompt_contributions: Optional[dict[str, str]] = None,
        context_slots: tuple[str, ...] = (),
    ) -> ComposedPrompt:
        """装配最终 system message。

        Args:
            plan: 上层准备好的 prompt 装配计划。
            context: 运行时上下文。
            tool_snapshot: 工具快照。
            prompt_contributions: Service 提供的动态 prompt 片段。
            context_slots: scene manifest 声明允许填充的 slot 顺序。

        Returns:
            组合后的 Prompt 对象。

        Raises:
            无。
        """

        snapshot = tool_snapshot or PromptToolSnapshot()
        pieces: list[str] = []
        fragment_ids: list[str] = []
        skipped_fragments: list[str] = []
        for fragment in sorted(plan.fragments, key=lambda item: item.order):
            if not self._matches_tool_filters(fragment, snapshot):
                skipped_fragments.append(fragment.id)
                continue
            if fragment.skip_if_context_missing and fragment.context_keys and not context.has_any(fragment.context_keys):
                skipped_fragments.append(fragment.id)
                continue
            rendered = self._renderer.render(
                template=fragment.template,
                variables=context.select(fragment.context_keys),
                tool_snapshot=snapshot,
            )
            if not rendered:
                skipped_fragments.append(fragment.id)
                continue
            pieces.append(rendered)
            fragment_ids.append(fragment.id)
        pieces.extend(
            _collect_prompt_contributions(
                prompt_contributions=prompt_contributions,
                context_slots=context_slots,
            )
        )
        return ComposedPrompt(
            name=plan.name,
            version=plan.version,
            system_message="\n\n".join(pieces).strip(),
            fragment_ids=tuple(fragment_ids),
            skipped_fragments=tuple(skipped_fragments),
        )

    def _matches_tool_filters(
        self,
        fragment: PromptFragmentPlan,
        snapshot: PromptToolSnapshot,
    ) -> bool:
        """判断 fragment 是否满足工具过滤条件。"""

        filters = fragment.tool_filters
        if not filters:
            return True
        if not self._matches_any(filters.get("tool_tags_any"), snapshot.tool_tags):
            return False
        if not self._matches_all(filters.get("tool_tags_all"), snapshot.tool_tags):
            return False
        if not self._matches_any(filters.get("tool_names_any"), snapshot.tool_names):
            return False
        if not self._matches_all(filters.get("tool_names_all"), snapshot.tool_names):
            return False
        return True

    def _matches_any(self, required_values: Optional[list[str]], actual_values: frozenset[str]) -> bool:
        """判断 any 过滤条件是否满足。"""

        if not required_values:
            return True
        return any(value in actual_values for value in required_values)

    def _matches_all(self, required_values: Optional[list[str]], actual_values: frozenset[str]) -> bool:
        """判断 all 过滤条件是否满足。"""

        if not required_values:
            return True
        return all(value in actual_values for value in required_values)


def _collect_prompt_contributions(
    *,
    prompt_contributions: Optional[dict[str, str]],
    context_slots: tuple[str, ...],
) -> list[str]:
    """按 scene 声明顺序收集动态 prompt 片段。

    Args:
        prompt_contributions: Service 提供的动态 prompt 片段。
        context_slots: scene manifest 声明的 slot 顺序。

    Returns:
        追加到 system prompt 尾部的文本列表。

    Raises:
        无。
    """

    if not prompt_contributions:
        return []
    selected_contributions = select_prompt_contributions(
        prompt_contributions=prompt_contributions,
        context_slots=context_slots,
    ).selected_contributions
    pieces: list[str] = []
    for slot_name in context_slots:
        raw = selected_contributions.get(slot_name)
        if raw is None:
            continue
        normalized = str(raw).strip()
        if not normalized:
            continue
        pieces.append(normalized)
    return pieces


__all__ = [
    "ComposedPrompt",
    "PromptComposeContext",
    "PromptComposer",
    "PromptRenderer",
]
