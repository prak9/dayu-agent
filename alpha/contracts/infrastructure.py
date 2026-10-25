"""跨层基础设施协议。

定义 Service / Host / startup 等多层共用的基础设施 Protocol，
避免下层依赖上层（startup）的类型定义。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal, Optional, Protocol, TypeAlias, overload, runtime_checkable

from alpha.contracts.model_config import ModelConfig
from alpha.contracts.prompt_assets import SceneManifestAsset, TaskPromptContractAsset


StructuredConfigScalar: TypeAlias = str | int | float | bool | None
StructuredConfigValue: TypeAlias = (
    StructuredConfigScalar
    | list["StructuredConfigValue"]
    | dict[str, "StructuredConfigValue"]
)
StructuredConfigObject: TypeAlias = dict[str, StructuredConfigValue]


class ConfigLoaderProtocol(Protocol):
    """配置加载器协议。"""

    def load_run_config(self) -> dict[str, Any]:
        """读取运行配置。"""
        ...

    def load_llm_models(self) -> dict[str, ModelConfig]:
        """读取全部模型配置。"""
        ...

    def load_llm_model(self, model_name: str) -> ModelConfig:
        """读取单个模型配置。"""
        ...

    def load_toolset_registrars(self) -> dict[str, str]:
        """读取 toolset registrar 安装清单。"""
        ...

    def collect_model_referenced_env_vars(self, model_names: Iterable[str]) -> tuple[str, ...]:
        """收集指定模型配置引用的环境变量。"""
        ...


class PromptAssetStoreProtocol(Protocol):
    """Prompt 资产仓储协议。"""

    def load_scene_manifest(self, scene_name: str) -> SceneManifestAsset:
        """读取 scene manifest。"""
        ...

    @overload
    def load_fragment_template(self, fragment_path: str, *, required: Literal[True] = True) -> str:
        """读取必须存在的 fragment 模板。"""

    @overload
    def load_fragment_template(self, fragment_path: str, *, required: Literal[False]) -> Optional[str]:
        """读取可缺失的 fragment 模板。"""

    def load_fragment_template(self, fragment_path: str, *, required: bool = True) -> Optional[str]:
        """读取 fragment 模板。"""
        ...

    def load_task_prompt(self, task_name: str) -> str:
        """读取 task prompt。"""
        ...

    def load_task_prompt_contract(self, task_name: str) -> TaskPromptContractAsset:
        """读取 task prompt sidecar contract。

        Args:
            task_name: task prompt 名称。

        Returns:
            解析后的 contract 映射对象。
        """
        ...


class WorkspaceResourcesProtocol(Protocol):
    """工作区稳定资源协议。"""

    @property
    def workspace_dir(self) -> Path:
        """返回工作区目录。"""

        ...

    @property
    def config_root(self) -> Path:
        """返回配置目录。"""

        ...

    @property
    def output_dir(self) -> Path:
        """返回输出目录。"""

        ...

    @property
    def config_loader(self) -> ConfigLoaderProtocol:
        """返回配置加载器。"""

        ...

    @property
    def prompt_asset_store(self) -> PromptAssetStoreProtocol:
        """返回 prompt 资产仓储。"""

        ...


@runtime_checkable
class ModelCatalogProtocol(Protocol):
    """模型目录协议。"""

    def load_model(self, model_name: str) -> ModelConfig:
        """读取单个模型配置。"""
        ...

    def load_models(self) -> dict[str, ModelConfig]:
        """读取全部模型配置。"""
        ...


__all__ = [
    "ConfigLoaderProtocol",
    "ModelCatalogProtocol",
    "PromptAssetStoreProtocol",
    "StructuredConfigObject",
    "StructuredConfigScalar",
    "StructuredConfigValue",
    "WorkspaceResourcesProtocol",
]
