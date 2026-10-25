"""跨层可执行路径共享的协作式取消原语。"""

from __future__ import annotations

import threading
from typing import Callable


class CancelledError(Exception):
    """执行过程被取消。

    当 CancellationToken 被触发后，调用 raise_if_cancelled() 将抛出此异常。
    """


class CancellationToken:
    """协作式取消令牌。线程安全。

    使用方式：
    - 创建方持有 token 引用，需要取消时调用 cancel()
    - 执行方在循环中定期调用 raise_if_cancelled() 或检查 is_cancelled()
    """

    def __init__(self) -> None:
        """初始化取消令牌。"""
        self._event = threading.Event()
        self._callbacks: list[Callable[[], None]] = []
        self._lock = threading.Lock()

    def cancel(self) -> None:
        """触发取消。"""
        if self._event.is_set():
            return
        self._event.set()
        with self._lock:
            callbacks = list(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass

    def is_cancelled(self) -> bool:
        """检查是否已被取消。"""
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        """如果已取消，抛出 CancelledError。"""
        if self._event.is_set():
            raise CancelledError("操作已被取消")

    def on_cancel(self, callback: Callable[[], None]) -> Callable[[], None]:
        """注册取消回调。

        参数:
            callback: 取消触发后要执行的回调。

        返回值:
            Callable[[], None]: 注销当前回调的函数；若 token 已取消，则返回空操作函数。

        异常:
            无。回调的执行异常会被内部吞掉。
        """
        with self._lock:
            if self._event.is_set():
                try:
                    callback()
                except Exception:
                    pass
                return _noop_unregister
            self._callbacks.append(callback)

        def _unregister() -> None:
            """移除当前已注册的取消回调。

            参数:
                无。

            返回值:
                无。

            异常:
                无。
            """

            with self._lock:
                if self._event.is_set():
                    return
                try:
                    self._callbacks.remove(callback)
                except ValueError:
                    return

        return _unregister

    def wait(self, timeout: float | None = None) -> bool:
        """阻塞等待取消信号。"""
        return self._event.wait(timeout=timeout)

    @classmethod
    def create_linked(cls, *parents: "CancellationToken") -> "CancellationToken":
        """创建级联取消令牌。"""
        child = cls()
        for parent in parents:
            parent.on_cancel(child.cancel)
        return child


def _noop_unregister() -> None:
    """空操作回调注销函数。

    参数:
        无。

    返回值:
        无。

    异常:
        无。
    """
