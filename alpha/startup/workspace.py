"""启动期工作区稳定资源定义。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alpha.contracts.infrastructure import (
    ConfigLoaderProtocol,
    PromptAssetStoreProtocol,
    WorkspaceResourcesProtocol,
)


@dataclass(frozen=True)
class WorkspaceResources:
    """启动期准备好的工作区稳定资源。"""

    workspace_dir: Path
    config_root: Path
    output_dir: Path
    config_loader: ConfigLoaderProtocol
    prompt_asset_store: PromptAssetStoreProtocol


__all__ = [
    "ConfigLoaderProtocol",
    "PromptAssetStoreProtocol",
    "WorkspaceResources",
    "WorkspaceResourcesProtocol",
]
