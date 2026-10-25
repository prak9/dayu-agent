"""基于 state_dir 的跨平台单实例锁。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TextIO

import alpha.file_lock as file_lock_module


class StateDirSingleInstanceLock:
    """基于固定锁文件的 state_dir 单实例锁。"""

    def __init__(
        self,
        *,
        state_dir: Path,
        lock_file_name: str,
        lock_name: str,
        lock_region_bytes: int = 1,
    ) -> None:
        """初始化单实例锁。

        Args:
            state_dir: 状态目录。
            lock_file_name: 锁文件名。
            lock_name: 锁用途说明。
            lock_region_bytes: 需要锁定的字节数。

        Returns:
            无。

        Raises:
            ValueError: 参数非法时抛出。
        """

        normalized_lock_file_name = str(lock_file_name).strip()
        normalized_lock_name = str(lock_name).strip()
        if not normalized_lock_file_name:
            raise ValueError("lock_file_name 不能为空")
        if not normalized_lock_name:
            raise ValueError("lock_name 不能为空")
        if lock_region_bytes <= 0:
            raise ValueError("lock_region_bytes 必须大于 0")
        self._state_dir = Path(state_dir).expanduser().resolve()
        self._lock_path = self._state_dir / normalized_lock_file_name
        self._lock_name = normalized_lock_name
        self._lock_region_bytes = lock_region_bytes
        self._stream: TextIO | None = None

    @property
    def state_dir(self) -> Path:
        """返回锁绑定的状态目录。"""

        return self._state_dir

    def acquire(self) -> None:
        """获取单实例锁。

        Args:
            无。

        Returns:
            无。

        Raises:
            RuntimeError: 当前 `state_dir` 已有活跃实例时抛出。
            OSError: 底层文件锁失败时抛出。
        """

        if self._stream is not None:
            return
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path.touch(exist_ok=True)
        stream = self._lock_path.open("r+", encoding="utf-8")
        try:
            file_lock_module.acquire_text_file_lock(
                stream,
                blocking=False,
                region_bytes=self._lock_region_bytes,
                lock_name=self._lock_name,
            )
            stream.seek(0)
            stream.write(f"{os.getpid()}\n")
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
            stream.seek(0)
        except OSError as exc:
            stream.close()
            if file_lock_module.is_lock_contention_error(exc):
                raise RuntimeError(
                    f"同一个 state_dir 已有运行中的 {self._lock_name}: "
                    f"state_dir={self._state_dir}"
                ) from exc
            raise
        self._stream = stream

    def release(self) -> None:
        """释放单实例锁。"""

        stream = self._stream
        if stream is None:
            return
        try:
            stream.seek(0)
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
            file_lock_module.release_text_file_lock(
                stream,
                region_bytes=self._lock_region_bytes,
                lock_name=self._lock_name,
            )
        finally:
            stream.close()
            self._stream = None


__all__ = ["StateDirSingleInstanceLock"]
