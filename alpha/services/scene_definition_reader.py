"""Service 侧 scene 定义读取模块。"""

from __future__ import annotations

from dataclasses import dataclass

from alpha.prompting.scene_definition import SceneDefinition, ScenePromptAssetStoreProtocol, load_scene_definition


@dataclass(frozen=True)
class SceneDefinitionReader:
    """读取 scene manifest 并解析为稳定定义。"""

    prompt_asset_store: ScenePromptAssetStoreProtocol

    def read(self, scene_name: str) -> SceneDefinition:
        """读取指定 scene 的完整定义。"""

        return load_scene_definition(self.prompt_asset_store, scene_name)


__all__ = ["SceneDefinitionReader"]
