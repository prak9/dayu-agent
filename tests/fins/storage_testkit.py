"""Fins 测试用文件系统仓储装配辅助。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alpha.fins.storage import (
    FsCompanyMetaRepository,
    FsDocumentBlobRepository,
    FsFilingMaintenanceRepository,
    FsProcessedDocumentRepository,
    FsSourceDocumentRepository,
)
from alpha.fins.storage._fs_repository_factory import build_fs_repository_set


@dataclass(frozen=True)
class FsStorageTestContext:
    """测试用文件系统仓储上下文。

    该上下文仅供测试准备数据时复用同一底层 core，避免每个测试重复手写
    `repository_set` 装配逻辑。
    """

    core: Any
    company_repository: FsCompanyMetaRepository
    source_repository: FsSourceDocumentRepository
    processed_repository: FsProcessedDocumentRepository
    blob_repository: FsDocumentBlobRepository
    filing_maintenance_repository: FsFilingMaintenanceRepository


def build_fs_storage_test_context(workspace_root: Path) -> FsStorageTestContext:
    """构建测试用文件系统仓储上下文。

    Args:
        workspace_root: 工作区根目录。

    Returns:
        共享同一底层 core 的测试仓储上下文。

    Raises:
        OSError: 底层仓储初始化失败时抛出。
    """

    repository_set = build_fs_repository_set(workspace_root=workspace_root)
    return FsStorageTestContext(
        core=repository_set.core,
        company_repository=FsCompanyMetaRepository(
            workspace_root,
            repository_set=repository_set,
        ),
        source_repository=FsSourceDocumentRepository(
            workspace_root,
            repository_set=repository_set,
        ),
        processed_repository=FsProcessedDocumentRepository(
            workspace_root,
            repository_set=repository_set,
        ),
        blob_repository=FsDocumentBlobRepository(
            workspace_root,
            repository_set=repository_set,
        ),
        filing_maintenance_repository=FsFilingMaintenanceRepository(
            workspace_root,
            repository_set=repository_set,
        ),
    )


def build_storage_core(workspace_root: Path) -> Any:
    """构建测试用底层文件系统存储 core。

    Args:
        workspace_root: 工作区根目录。

    Returns:
        共享文件系统存储 core。

    Raises:
        OSError: 底层仓储初始化失败时抛出。
    """

    return build_fs_storage_test_context(workspace_root).core
