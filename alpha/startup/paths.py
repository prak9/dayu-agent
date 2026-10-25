"""启动期路径解析辅助。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StartupPaths:
    """启动期稳定路径集合。"""

    workspace_root: Path
    config_root: Path
    output_dir: Path


def resolve_startup_paths(
    *,
    workspace_root: Path,
    config_root: Path | None = None,
) -> StartupPaths:
    """解析启动期需要的核心路径。

    Args:
        workspace_root: 工作区根目录。
        config_root: 显式配置目录；为空时回落到 ``<workspace>/config``。

    Returns:
        已解析完成的路径集合。

    Raises:
        FileNotFoundError: 工作区不存在时抛出。
        NotADirectoryError: 输入路径不是目录时抛出。
    """

    resolved_workspace_root = workspace_root.expanduser().resolve()
    if not resolved_workspace_root.exists():
        raise FileNotFoundError(f"工作区不存在: {resolved_workspace_root}")
    if not resolved_workspace_root.is_dir():
        raise NotADirectoryError(f"工作区不是目录: {resolved_workspace_root}")
    resolved_config_root = (
        config_root.expanduser().resolve()
        if config_root is not None
        else (resolved_workspace_root / "config").resolve()
    )
    return StartupPaths(
        workspace_root=resolved_workspace_root,
        config_root=resolved_config_root,
        output_dir=(resolved_workspace_root / "output").resolve(),
    )


__all__ = ["StartupPaths", "resolve_startup_paths"]
