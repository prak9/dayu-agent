"""processors.base 协议与占位类型测试。"""

from __future__ import annotations

from typing import get_type_hints

from alpha.engine.processors import base
from alpha.engine.processors.source import Source


def test_placeholder_types_are_dict_subclasses() -> None:
    """验证占位类型均为 dict 子类。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    placeholders = [
        base.SectionSummary,
        base.TableSummary,
        base.SectionContent,
        base.TableContent,
        base.SearchHit,
        base.PageContentResult,
    ]
    for item in placeholders:
        assert issubclass(item, dict)


def test_document_processor_protocol_type_hints_are_available() -> None:
    """验证协议方法类型注解可被读取。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    init_hints = get_type_hints(base.DocumentProcessor.__init__)
    supports_hints = get_type_hints(base.DocumentProcessor.supports)
    assert init_hints["source"] is Source
    assert supports_hints["source"] is Source


def test_document_processor_protocol_declares_get_parser_version() -> None:
    """验证处理器协议声明 get_parser_version。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    assert hasattr(base.DocumentProcessor, "get_parser_version")
    hints = get_type_hints(base.DocumentProcessor.get_parser_version)
    assert hints["return"] is str
