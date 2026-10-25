"""研究文件存储共用的持久写入与临时目录原语。"""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_PENDING_PREFIX = ".pending-"


def sync_directory(path: Path) -> None:
    """持久化目录项。参数：path 目录。返回：无。异常：I/O 错误。"""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_bytes_synced(path: Path, data: bytes) -> None:
    """写入并同步文件。参数：path 文件、data 内容。返回：无。异常：I/O 错误。"""
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def staged_directory(parent: Path) -> Iterator[Path]:
    """提供同文件系统临时目录。参数：parent 父目录。返回：目录迭代器。异常：I/O 或调用方异常传播。"""
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=_PENDING_PREFIX, dir=parent))
    try:
        yield staging
    finally:
        if staging.exists():
            shutil.rmtree(staging)
