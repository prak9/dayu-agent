"""Source 抽象测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from alpha.fins.storage.local_file_source import LocalFileSource


@pytest.mark.unit
def test_local_file_source_open_and_materialize(tmp_path: Path) -> None:
    """验证本地 Source 的 open 与 materialize。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    sample = tmp_path / "sample.html"
    sample.write_text("<html>ok</html>", encoding="utf-8")

    source = LocalFileSource(
        path=sample,
        uri="local://sample.html",
        media_type="text/html",
        content_length=sample.stat().st_size,
        etag="etag",
    )

    with source.open() as stream:
        payload = stream.read()
    assert b"ok" in payload

    materialized = source.materialize(suffix=".html")
    assert materialized == sample
