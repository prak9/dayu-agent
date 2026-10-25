"""LocalFileStore 测试。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from alpha.fins.storage.local_file_store import LocalFileStore


class FailingStream(BytesIO):
    """读取时抛异常的流。"""

    def read(self, n: int | None = -1) -> bytes:
        _ = n
        raise OSError("boom")


def test_put_get_stat_list_and_delete_roundtrip(tmp_path: Path) -> None:
    """验证本地存储读写、stat、list 与删除。

    Args:
        tmp_path: 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    store = LocalFileStore(root=tmp_path / "store")
    meta = store.put_object("AAPL/filings/a.htm", BytesIO(b"hello"))
    assert meta.uri == "local://AAPL/filings/a.htm"
    assert meta.size == 5
    assert meta.sha256

    with store.get_object("AAPL/filings/a.htm") as stream:
        assert stream.read() == b"hello"

    stat = store.stat_object("AAPL/filings/a.htm")
    assert stat.size == 5
    assert stat.etag == stat.sha256

    store.put_object("AAPL/filings/b.htm", BytesIO(b"world"))
    listed = store.list_objects("AAPL/filings")
    assert len(listed) == 2
    uris = sorted(item.uri for item in listed)
    assert uris == ["local://AAPL/filings/a.htm", "local://AAPL/filings/b.htm"]

    store.delete_object("AAPL/filings/a.htm")
    with pytest.raises(FileNotFoundError):
        store.get_object("AAPL/filings/a.htm")


def test_invalid_keys_and_scheme_raise(tmp_path: Path) -> None:
    """验证非法 key 与 scheme 的异常。

    Args:
        tmp_path: 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    with pytest.raises(ValueError):
        LocalFileStore(root=tmp_path / "store", scheme=" ")

    store = LocalFileStore(root=tmp_path / "store")
    with pytest.raises(ValueError):
        store.put_object("  ", BytesIO(b"x"))
    with pytest.raises(ValueError):
        store.put_object("../escape.txt", BytesIO(b"x"))
    with pytest.raises(ValueError):
        store._build_uri(" ")


def test_put_object_stream_failure(tmp_path: Path) -> None:
    """验证写入失败时抛出异常。

    Args:
        tmp_path: 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    store = LocalFileStore(root=tmp_path / "store")
    with pytest.raises(OSError):
        store.put_object("AAPL/filings/a.htm", FailingStream())


def test_stat_and_delete_missing_raise(tmp_path: Path) -> None:
    """验证 stat/delete 在缺失对象时抛错。

    Args:
        tmp_path: 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    store = LocalFileStore(root=tmp_path / "store")
    with pytest.raises(FileNotFoundError):
        store.stat_object("AAPL/filings/missing.htm")
    with pytest.raises(FileNotFoundError):
        store.delete_object("AAPL/filings/missing.htm")


def test_list_objects_missing_prefix_returns_empty(tmp_path: Path) -> None:
    """验证 list_objects 对不存在前缀返回空列表。

    Args:
        tmp_path: 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    store = LocalFileStore(root=tmp_path / "store")
    listed = store.list_objects("AAPL/filings/not-exist")
    assert listed == []
