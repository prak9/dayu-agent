"""processed 快照仓储辅助函数。

该模块封装 `processed/{document_id}` 目录的仓储访问，避免 pipeline
直接依赖真实文件系统路径。当前职责包括：
- 校验快照文件集合是否匹配当前导出模式
- 清理非目标快照文件
- 安全读取 `tool_snapshot_meta.json`
- 清空某个 ticker 的全部 processed 产物
"""

from __future__ import annotations

import json
from typing import Any, Optional

from alpha.fins.domain.document_models import ProcessedHandle
from alpha.fins.storage import (
    DocumentBlobRepositoryProtocol,
    ProcessedDocumentRepositoryProtocol,
)

from .tool_snapshot_export import (
    TOOL_SNAPSHOT_META_FILE_NAME,
    build_snapshot_file_names,
)

_REGISTERED_FINANCIALS_FILE = "financials.json"
_REGISTERED_FINANCIALS_MARKER = {"snapshot_registered": True}


def match_snapshot_files(
    *,
    repository: DocumentBlobRepositoryProtocol,
    ticker: str,
    document_id: str,
    ci: bool,
) -> bool:
    """校验快照文件集合是否与当前模式严格一致。

    Args:
        repository: 文档文件对象仓储。
        ticker: 股票代码。
        document_id: 文档 ID。
        ci: 是否 CI 模式。

    Returns:
        文件集合完全匹配时返回 `True`，否则返回 `False`。

    Raises:
        OSError: 仓储读取失败时抛出。
    """

    handle = ProcessedHandle(ticker=ticker, document_id=document_id)
    entries = repository.list_entries(handle)
    if not entries:
        return False
    if any(not entry.is_file for entry in entries):
        return False
    expected_files = set(build_snapshot_file_names(ci=ci))
    existing_files = {entry.name for entry in entries}
    # processed 仓储用此标记登记 XBRL 能力；它不是额外的工具快照或旧财务缓存。
    if _REGISTERED_FINANCIALS_FILE in existing_files:
        try:
            marker = json.loads(repository.read_file_bytes(handle, _REGISTERED_FINANCIALS_FILE))
        except (ValueError, UnicodeError):
            return False
        if marker != _REGISTERED_FINANCIALS_MARKER:
            return False
        existing_files.remove(_REGISTERED_FINANCIALS_FILE)
    return existing_files == expected_files


def cleanup_processed_snapshot_dir(
    *,
    repository: DocumentBlobRepositoryProtocol,
    ticker: str,
    document_id: str,
    allowed_files: set[str],
) -> None:
    """清理 `processed/{document_id}` 中非目标快照条目。

    Args:
        repository: 文档文件对象仓储。
        ticker: 股票代码。
        document_id: 文档 ID。
        allowed_files: 允许保留的文件名集合。

    Returns:
        无。

    Raises:
        OSError: 仓储删除失败时抛出。
    """

    handle = ProcessedHandle(ticker=ticker, document_id=document_id)
    for entry in repository.list_entries(handle):
        if entry.name in allowed_files:
            continue
        repository.delete_entry(handle, entry.name)


def safe_read_snapshot_meta(
    *,
    repository: DocumentBlobRepositoryProtocol,
    ticker: str,
    document_id: str,
) -> Optional[dict[str, Any]]:
    """安全读取 `tool_snapshot_meta.json`。

    Args:
        repository: 文档文件对象仓储。
        ticker: 股票代码。
        document_id: 文档 ID。

    Returns:
        JSON 字典；文件不存在、解码失败或格式非法时返回 `None`。

    Raises:
        OSError: 仓储底层读取失败且不属于可恢复场景时抛出。
    """

    handle = ProcessedHandle(ticker=ticker, document_id=document_id)
    try:
        payload = json.loads(
            repository.read_file_bytes(handle, TOOL_SNAPSHOT_META_FILE_NAME).decode("utf-8")
        )
    except (FileNotFoundError, IsADirectoryError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def clear_processed_documents(
    *,
    repository: ProcessedDocumentRepositoryProtocol,
    ticker: str,
) -> None:
    """清空某个 ticker 下的全部 processed 产物。

    Args:
        repository: processed 文档仓储。
        ticker: 股票代码。

    Returns:
        无。

    Raises:
        OSError: 仓储清理失败时抛出。
    """

    repository.clear_processed_documents(ticker)
