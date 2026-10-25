"""模型目录能力。

该模块把 ``llm_models.json`` 的读取收敛成稳定依赖，避免 Service 直接理解
配置文件来源。
"""

from __future__ import annotations

from dataclasses import dataclass

from alpha.contracts.infrastructure import ConfigLoaderProtocol, ModelCatalogProtocol
from alpha.contracts.model_config import ModelConfig


@dataclass(frozen=True)
class ConfigLoaderModelCatalog(ModelCatalogProtocol):
    """基于 ConfigLoader 的默认模型目录实现。"""

    config_loader: ConfigLoaderProtocol

    def load_model(self, model_name: str) -> ModelConfig:
        """读取单个模型配置。

        Args:
            model_name: 模型名。

        Returns:
            模型配置字典。

        Raises:
            KeyError: 模型不存在时抛出。
        """

        return self.config_loader.load_llm_model(model_name)

    def load_models(self) -> dict[str, ModelConfig]:
        """读取全部模型配置。

        Args:
            无。

        Returns:
            模型配置映射。

        Raises:
            无。
        """

        return self.config_loader.load_llm_models()


__all__ = [
    "ConfigLoaderModelCatalog",
    "ModelCatalogProtocol",
]
