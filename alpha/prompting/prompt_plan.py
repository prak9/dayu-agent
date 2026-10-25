"""Prompt 装配计划模型与构建器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Protocol, overload

from alpha.contracts.prompt_assets import SceneManifestAsset

from .scene_definition import PromptManifestError, SceneDefinition, load_scene_definition


@dataclass(frozen=True)
class PromptFragmentPlan:
    """单个 prompt 片段的装配计划。"""

    id: str
    template: str
    order: int
    context_keys: tuple[str, ...] = ()
    skip_if_context_missing: bool = False
    tool_filters: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptAssemblyPlan:
    """完整 prompt 的装配计划。"""

    name: str
    version: str
    fragments: tuple[PromptFragmentPlan, ...] = ()


class PromptFragmentAssetStoreProtocol(Protocol):
    """Prompt fragment 资产仓储协议。"""

    @overload
    def load_fragment_template(self, fragment_path: str, *, required: Literal[True] = True) -> str:
        """读取必须存在的 fragment 模板。"""

    @overload
    def load_fragment_template(self, fragment_path: str, *, required: Literal[False]) -> Optional[str]:
        """读取可缺失的 fragment 模板。"""

    def load_fragment_template(self, fragment_path: str, *, required: bool = True) -> Optional[str]:
        """读取 fragment 模板。"""

    def load_scene_manifest(self, scene_name: str) -> SceneManifestAsset:
        """读取 scene manifest。"""

        ...


def build_prompt_assembly_plan(
    *,
    asset_store: PromptFragmentAssetStoreProtocol,
    scene_name: str | None = None,
    scene_definition: SceneDefinition | None = None,
) -> PromptAssemblyPlan:
    """构建 prompt 装配计划。

    Args:
        asset_store: prompt 资产仓储。
        scene_name: scene 名称；当 ``scene_definition`` 为空时必填。
        scene_definition: 预解析 scene 定义。

    Returns:
        ``PromptAssemblyPlan``。

    Raises:
        PromptManifestError: scene_name 缺失或配置非法时抛出。
    """

    resolved_definition = scene_definition
    if resolved_definition is None:
        normalized_scene_name = str(scene_name or "").strip()
        if not normalized_scene_name:
            raise PromptManifestError("构建 prompt 装配计划时必须提供 scene_name")
        resolved_definition = load_scene_definition(asset_store, normalized_scene_name)
    fragments: list[PromptFragmentPlan] = []
    for fragment in sorted(resolved_definition.fragments, key=lambda item: item.order):
        if not fragment.enabled:
            continue
        template = asset_store.load_fragment_template(
            fragment.path,
            required=fragment.required and resolved_definition.missing_fragment_policy == "error",
        )
        if template is None:
            continue
        fragments.append(
            PromptFragmentPlan(
                id=fragment.id,
                template=template,
                order=fragment.order,
                context_keys=fragment.context_keys,
                skip_if_context_missing=fragment.skip_if_context_missing,
                tool_filters={key: list(value) for key, value in fragment.tool_filters.items()},
            )
        )
    fragments.sort(key=lambda item: item.order)
    return PromptAssemblyPlan(
        name=resolved_definition.name,
        version=resolved_definition.version,
        fragments=tuple(fragments),
    )


__all__ = [
    "PromptAssemblyPlan",
    "PromptFragmentPlan",
    "build_prompt_assembly_plan",
]
