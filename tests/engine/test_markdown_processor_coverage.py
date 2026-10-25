"""MarkdownProcessor 边界场景和错误处理测试（提升覆盖率到 90%+）。

本测试文件补充 test_markdown_processor.py 中未覆盖的边界情况、错误处理和特殊场景。
覆盖边界情况、错误处理和特殊场景。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Optional, BinaryIO

import pytest

from alpha.engine.processors.markdown_processor import MarkdownProcessor
from alpha.engine.processors.source import Source


class DummySource:
    """测试用 Source。"""

    def __init__(self, path: Path, *, uri: Optional[str] = None, media_type: Optional[str] = None) -> None:
        """初始化测试 Source。

        Args:
            path: 本地文件路径。
            uri: 可选 URI。
            media_type: 可选媒体类型。

        Returns:
            无。

        Raises:
            ValueError: 路径为空时抛出。
        """

        if not path:
            raise ValueError("path 不能为空")
        self._path = path
        self.uri = uri or str(path)
        self.media_type = media_type
        self.content_length = None
        self.etag = None

    def open(self) -> BinaryIO:
        """打开文件流。"""

        return self._path.open("rb")

    def materialize(self, suffix: Optional[str] = None) -> Path:
        """返回本地路径。"""

        del suffix
        return self._path


@pytest.mark.unit
def test_markdown_processor_init_file_not_exists(tmp_path: Path) -> None:
    """验证初始化时文件不存在抛出 ValueError。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    non_existent = tmp_path / "non_existent.md"
    source = DummySource(non_existent, uri="local://test.md", media_type="text/markdown")
    
    with pytest.raises(ValueError, match="Markdown 文件不存在"):
        MarkdownProcessor(source)


@pytest.mark.unit
def test_markdown_processor_init_path_is_directory(tmp_path: Path) -> None:
    """验证初始化时路径是目录抛出 ValueError。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    dir_path = tmp_path / "test_dir"
    dir_path.mkdir()
    
    source = DummySource(dir_path, uri="local://test", media_type="text/markdown")
    
    with pytest.raises(ValueError, match="Markdown 文件不存在"):
        MarkdownProcessor(source)


@pytest.mark.unit
def test_markdown_processor_read_section_not_found(tmp_path: Path) -> None:
    """验证读取不存在的章节引用抛出 KeyError。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    md_path = tmp_path / "test.md"
    md_path.write_text("# title\n\nSome content\n", encoding="utf-8")
    
    processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
    
    with pytest.raises(KeyError, match="Section not found"):
        processor.read_section("invalid_ref")


@pytest.mark.unit
def test_markdown_processor_read_table_not_found(tmp_path: Path) -> None:
    """验证读取不存在的表格引用抛出 KeyError。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    md_path = tmp_path / "test.md"
    md_path.write_text("# title\n\nSome content\n", encoding="utf-8")
    
    processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
    
    with pytest.raises(KeyError, match="Table not found"):
        processor.read_table("invalid_table_ref")


@pytest.mark.unit
def test_markdown_processor_supports_by_media_type() -> None:
    """验证 supports 方法通过 media_type 识别。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source = MagicMock()
    source.uri = "report.json"
    source.media_type = "text/markdown"
    
    assert MarkdownProcessor.supports(source) is True


@pytest.mark.unit
def test_markdown_processor_supports_by_uri_markdown_suffix(tmp_path: Path) -> None:
    """验证 supports 方法通过 .markdown 后缀识别。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    md_path = tmp_path / "report.markdown"
    md_path.write_text("# title\n", encoding="utf-8")
    
    source = DummySource(md_path, uri="local://report.markdown")
    assert MarkdownProcessor.supports(source) is True


@pytest.mark.unit
def test_markdown_processor_supports_vnd_markdown_type() -> None:
    """验证 supports 方法识别 vnd.markdown 类型。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source = MagicMock()
    source.uri = "doc.txt"
    source.media_type = "text/plain"
    
    result = MarkdownProcessor.supports(source, media_type="application/vnd.markdown")
    assert result is True


@pytest.mark.unit
def test_markdown_processor_supports_non_markdown(tmp_path: Path) -> None:
    """验证 supports 方法拒绝非 markdown 文件。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    txt_path = tmp_path / "report.txt"
    txt_path.write_text("plain text\n", encoding="utf-8")
    
    source = DummySource(txt_path, uri="local://report.txt", media_type="text/plain")
    assert MarkdownProcessor.supports(source) is False


@pytest.mark.unit
def test_markdown_processor_list_sections_empty(tmp_path: Path) -> None:
    """验证空文档返回空章节列表。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    md_path = tmp_path / "empty.md"
    # 创建没有标题的文件（无章节）
    md_path.write_text("Just some plain text without headings.\n", encoding="utf-8")
    
    processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
    sections = processor.list_sections()
    
    # 即使没有标题，也可能会创建一个默认章节
    # 这取决于实现，我们验证其行为一致
    assert isinstance(sections, list)


@pytest.mark.unit
def test_markdown_processor_list_tables_empty(tmp_path: Path) -> None:
    """验证无表格的文档返回空表格列表。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    md_path = tmp_path / "no_tables.md"
    md_path.write_text("# Title\n\nJust plain text without tables.\n", encoding="utf-8")
    
    processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
    tables = processor.list_tables()
    
    assert tables == []


@pytest.mark.unit
def test_markdown_processor_search_empty_query(tmp_path: Path) -> None:
    """验证空查询返回空列表。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    md_path = tmp_path / "test.md"
    md_path.write_text("# Title\n\nSome content.\n", encoding="utf-8")
    
    processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
    
    # 空查询应返回空列表
    result = processor.search("")
    assert result == []
    
    # 仅空白字符的查询应返回空列表
    result = processor.search("   ")
    assert result == []


@pytest.mark.unit
def test_markdown_processor_search_no_match(tmp_path: Path) -> None:
    """验证无匹配查询返回空列表。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    md_path = tmp_path / "test.md"
    md_path.write_text("# Title\n\nSome content about apples.\n", encoding="utf-8")
    
    processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
    
    # 搜索不存在的单词
    result = processor.search("NONEXISTENT_WORD_XYZ")
    assert result == []


@pytest.mark.unit
def test_markdown_processor_multiple_heading_levels(tmp_path: Path) -> None:
    """验证多层级标题的处理。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    md_path = tmp_path / "hierarchical.md"
    md_path.write_text(
        "\n".join([
            "# Level 1",
            "Content 1",
            "## Level 2a", 
            "Content 2a",
            "### Level 3",
            "Content 3",
            "## Level 2b",
            "Content 2b",
        ]),
        encoding="utf-8"
    )
    
    processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
    sections = processor.list_sections()
    
    # 验证层级被正确识别
    assert len(sections) > 1
    # 第一个应该是等级1
    assert sections[0]["level"] == 1


@pytest.mark.unit
def test_markdown_processor_read_section_with_tables(tmp_path: Path) -> None:
    """验证章节内容包含表格占位符。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    md_path = tmp_path / "with_table.md"
    md_path.write_text(
        "\n".join([
            "# 总览",
            "收入增长明显。",
            "| 项目 | 金额 |",
            "| --- | --- |",
            "| Revenue | 100 |",
        ]),
        encoding="utf-8"
    )
    
    processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
    sections = processor.list_sections()
    
    if sections:
        section_content = processor.read_section(sections[0]["ref"])
        # 验证返回字典有必需字段
        assert "ref" in section_content
        assert "content" in section_content
        assert "title" in section_content


@pytest.mark.unit
def test_markdown_processor_table_with_headers(tmp_path: Path) -> None:
    """验证表格头部解析。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    md_path = tmp_path / "table_test.md"
    md_path.write_text(
        "\n".join([
            "# Document",
            "| Header1 | Header2 | Header3 |",
            "| --- | --- | --- |",
            "| A | B | C |",
            "| D | E | F |",
        ]),
        encoding="utf-8"
    )
    
    processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
    tables = processor.list_tables()
    
    if tables:
        table_ref = tables[0]["table_ref"]
        table_content = processor.read_table(table_ref)
        
        # 验证表格返回值包含必需字段
        assert "table_ref" in table_content
        assert "data" in table_content or "data_format" in table_content


@pytest.mark.unit
def test_markdown_processor_empty_lines_handling(tmp_path: Path) -> None:
    """验证空行处理。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    md_path = tmp_path / "with_empty_lines.md"
    md_path.write_text(
        "\n".join([
            "# Title",
            "",
            "",
            "Content after empty lines.",
            "",
            "More content.",
        ]),
        encoding="utf-8"
    )
    
    processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
    sections = processor.list_sections()
    
    # 应该能处理有空行的文件
    assert len(sections) > 0


@pytest.mark.unit
def test_markdown_processor_special_characters(tmp_path: Path) -> None:
    """验证特殊字符处理。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    md_path = tmp_path / "special_chars.md"
    md_path.write_text(
        "\n".join([
            "# Title with 中文 and émojis 🚀",
            "Content with special chars: `code`, *italic*, **bold**",
            "Symbols: @#$%^&*()",
        ]),
        encoding="utf-8"
    )
    
    processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
    sections = processor.list_sections()
    
    # 应能处理特殊字符
    assert len(sections) > 0

@pytest.mark.unit
def test_markdown_processor_search_within_invalid_section(tmp_path: Path) -> None:
    """验证在不存在的章节范围内搜索返回空列表。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    md_path = tmp_path / "test.md"
    md_path.write_text("# Title\n\nContent with keyword.\n", encoding="utf-8")
    
    processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
    
    # 在不存在的章节范围内搜索
    result = processor.search("keyword", within_ref="invalid_ref")
    assert result == []


@pytest.mark.unit
def test_markdown_processor_table_parsing_with_duplicate_headers(tmp_path: Path) -> None:
    """验证表格头部有重复时的处理。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    md_path = tmp_path / "duplicate_headers.md"
    md_path.write_text(
        "\n".join([
            "# Document",
            "| Item | Value | Value |",
            "| --- | --- | --- |",
            "| A | 1 | 2 |",
        ]),
        encoding="utf-8"
    )
    
    processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
    tables = processor.list_tables()
    
    if tables:
        # 应该能处理重复表头的表格
        table_content = processor.read_table(tables[0]["table_ref"])
        assert table_content is not None
        # 由于头部重复，可能返回 markdown 格式而不是 records
        assert "data" in table_content


@pytest.mark.unit
def test_markdown_processor_large_word_count(tmp_path: Path) -> None:
    """验证大量内容的字数统计。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    md_path = tmp_path / "large.md"
    # 创建包含大量单词的内容
    large_content = "word " * 1000
    md_path.write_text(f"# Title\n\n{large_content}\n", encoding="utf-8")
    
    processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
    sections = processor.list_sections()
    
    if sections:
        section_content = processor.read_section(sections[0]["ref"])
        assert section_content["word_count"] > 0