"""engine 处理器注册构建器测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO, Optional, cast

import pytest

from alpha.engine.processors.bs_processor import BSProcessor
from alpha.engine.processors.registry import build_engine_processor_registry
from alpha.engine.processors.source import Source


class DummySource:
    """测试用 Source。"""

    def __init__(self, uri: str, media_type: Optional[str] = "text/html") -> None:
        """初始化测试 Source。

        Args:
            uri: 资源 URI。
            media_type: 媒体类型。

        Returns:
            无。

        Raises:
            ValueError: URI 为空时抛出。
        """

        if not uri:
            raise ValueError("uri 不能为空")
        self.uri = uri
        self.media_type = media_type
        self.content_length = None
        self.etag = None

    def open(self) -> BinaryIO:
        """打开只读流（测试桩）。

        Args:
            无。

        Returns:
            二进制只读流。

        Raises:
            OSError: 测试桩不提供读取能力。
        """

        raise OSError("dummy source 不提供 open")

    def materialize(self, suffix: Optional[str] = None) -> Path:
        """物化路径（测试桩）。

        Args:
            suffix: 可选后缀。

        Returns:
            本地路径。

        Raises:
            OSError: 测试桩不提供物化能力。
        """

        raise OSError("dummy source 不提供 materialize")


@pytest.mark.unit
def test_build_engine_processor_registry_registers_bs_only() -> None:
    """验证 engine 构建器会注册 Docling/Markdown/BS 处理器。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    registry = build_engine_processor_registry()
    processors = registry.list_processors()
    assert [item["name"] for item in processors] == [
        "docling_processor",
        "markdown_processor",
        "bs_processor",
    ]
    assert {
        str(item["name"]): int(cast(Any, item["priority"]))
        for item in processors
    } == {
        "docling_processor": 10,
        "markdown_processor": 10,
        "bs_processor": 10,
    }

    source = DummySource("local://sample.html")
    resolved = registry.resolve(source, form_type="DEF 14A")
    assert resolved is BSProcessor
