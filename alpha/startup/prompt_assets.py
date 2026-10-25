"""Prompt 资产仓储。

该模块属于启动期稳定辅助模块，负责理解 ``alpha/config/prompts`` 的目录布局，
并向上提供 scene manifest、fragment 与 task prompt 的语义化读取接口。
"""

from __future__ import annotations

from typing import Literal, Optional, cast, overload

from alpha.contracts.prompt_assets import SceneManifestAsset, TaskPromptContractAsset
from alpha.startup.config_file_resolver import ConfigFileResolver


class FilePromptAssetStore:
    """基于文件系统的 prompt 资产仓储。"""

    def __init__(self, resolver: ConfigFileResolver) -> None:
        """初始化 prompt 资产仓储。

        Args:
            resolver: 配置文件解析器实例。

        Returns:
            无。

        Raises:
            无。
        """

        self._resolver = resolver
        self._manifest_cache: dict[str, SceneManifestAsset] = {}

    def load_scene_manifest(self, scene_name: str) -> SceneManifestAsset:
        """读取指定 scene 的 manifest。

        首次读取后缓存，后续直接返回缓存结果。

        Args:
            scene_name: 场景名。

        Returns:
            manifest 对应的 JSON 对象。

        Raises:
            FileNotFoundError: manifest 不存在时抛出。
            json.JSONDecodeError: manifest 非法时抛出。
        """

        normalized_scene_name = scene_name.strip().strip("/")
        if normalized_scene_name in self._manifest_cache:
            return self._manifest_cache[normalized_scene_name]
        manifest = self._resolver.read_json(
            f"prompts/manifests/{normalized_scene_name}.json",
            required=True,
        )
        if not isinstance(manifest, dict):
            raise TypeError(f"scene manifest {normalized_scene_name!r} 必须是对象")
        typed_manifest = cast(SceneManifestAsset, manifest)
        self._manifest_cache[normalized_scene_name] = typed_manifest
        return typed_manifest

    @overload
    def load_fragment_template(self, fragment_path: str, *, required: Literal[True] = True) -> str:
        """读取必须存在的 scene fragment 模板。"""

    @overload
    def load_fragment_template(self, fragment_path: str, *, required: Literal[False]) -> Optional[str]:
        """读取可缺失的 scene fragment 模板。"""

    def load_fragment_template(self, fragment_path: str, *, required: bool = True) -> Optional[str]:
        """读取 scene fragment 模板。

        Args:
            fragment_path: manifest 中声明的 fragment 相对路径。
            required: 是否必须存在。

        Returns:
            模板文本；当 ``required=False`` 且文件不存在时返回 ``None``。

        Raises:
            FileNotFoundError: 当 ``required=True`` 且文件不存在时抛出。
        """

        normalized_path = fragment_path.strip().lstrip("/")
        if not normalized_path.startswith("prompts/"):
            normalized_path = f"prompts/{normalized_path}"
        return self._resolver.read_text(normalized_path, required=required)

    def load_task_prompt(self, task_name: str) -> str:
        """读取 task 级 prompt 模板。

        Args:
            task_name: task 名称，可带或不带 ``tasks/`` 前缀与 ``.md`` 后缀。

        Returns:
            task prompt 模板文本。

        Raises:
            FileNotFoundError: task prompt 不存在时抛出。
        """

        normalized_name = task_name.strip().strip("/")
        if not normalized_name.startswith("tasks/"):
            normalized_name = f"tasks/{normalized_name}"
        if not normalized_name.endswith(".md"):
            normalized_name = f"{normalized_name}.md"
        return self._resolver.read_text(f"prompts/{normalized_name}", required=True)

    def load_task_prompt_contract(self, task_name: str) -> TaskPromptContractAsset:
        """读取 task 级 prompt sidecar contract。

        Args:
            task_name: task 名称，可带或不带 ``tasks/`` 前缀、``.md`` 后缀或 ``.contract.yaml`` 后缀。

        Returns:
            解析后的 YAML 对象。

        Raises:
            FileNotFoundError: contract 文件不存在时抛出。
            yaml.YAMLError: YAML 非法时抛出。
            TypeError: contract 解析结果不是映射时抛出。
        """

        normalized_name = task_name.strip().strip("/")
        if normalized_name.endswith(".contract.yaml"):
            normalized_name = normalized_name[: -len(".contract.yaml")]
        if normalized_name.endswith(".md"):
            normalized_name = normalized_name[:-3]
        if not normalized_name.startswith("tasks/"):
            normalized_name = f"tasks/{normalized_name}"
        contract_path = f"prompts/{normalized_name}.contract.yaml"
        contract = self._resolver.read_yaml(contract_path, required=True)
        if not isinstance(contract, dict):
            raise TypeError(f"task prompt contract {normalized_name!r} 必须是映射")
        return cast(TaskPromptContractAsset, contract)
