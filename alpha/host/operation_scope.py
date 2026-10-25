"""同步 Host 操作内真实子执行的取消作用域，按线程与异步上下文隔离。"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from alpha.contracts.cancellation import CancellationToken

_PARENT_TOKEN: ContextVar[CancellationToken | None] = ContextVar("alpha_host_parent_token", default=None)


def parent_cancellation_token() -> CancellationToken | None:
    """读取当前真实外层操作。参数：无。返回：父令牌或空。异常：无。"""
    return _PARENT_TOKEN.get()


@contextmanager
def operation_scope(token: CancellationToken) -> Iterator[None]:
    """限定同步操作的子调用作用域。参数：Host 令牌。返回：作用域。异常：业务异常原样传播。"""
    reset = _PARENT_TOKEN.set(token)
    try:
        yield
    finally:
        _PARENT_TOKEN.reset(reset)
