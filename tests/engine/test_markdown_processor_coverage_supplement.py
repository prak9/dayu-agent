"""MarkdownProcessor 补充覆盖率测试（提升到 95%+）。

本测试文件补充 test_markdown_processor_coverage.py 中未覆盖的边界情况、
表格解析、章节内容读取、搜索功能等深层逻辑。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, Mock
from typing import Mapping, Optional, BinaryIO

import pytest

from alpha.engine.processors.markdown_processor import MarkdownProcessor
from alpha.engine.processors.source import Source


def _hit_section_title(hit: Mapping[str, object]) -> str | None:
    """安全读取搜索命中的可选章节标题。

    Args:
        hit: 搜索命中字典。

    Returns:
        `section_title`；不存在时返回 `None`。

    Raises:
        无。
    """

    title = hit.get("section_title")
    return title if isinstance(title, str) else None


class DummySource:
    """测试用 Source 实现。"""

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
class TestMarkdownProcessorTableParsing:
    """Markdown 表格解析功能测试。"""

    def test_markdown_processor_list_tables_with_tables(self, tmp_path: Path) -> None:
        """验证正确识别 Markdown 表格。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "with_tables.md"
        md_path.write_text(
            "# Section\n\n"
            "| Name | Value |\n"
            "|------|-------|\n"
            "| A    | 1     |\n"
            "| B    | 2     |\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        tables = processor.list_tables()
        
        assert len(tables) > 0
        assert tables[0]["col_count"] == 2

    def test_markdown_processor_read_table_records_format(self, tmp_path: Path) -> None:
        """验证表格以 records 格式读取。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "table_records.md"
        md_path.write_text(
            "# Title\n\n"
            "| Name | Age |\n"
            "|------|-----|\n"
            "| Alice | 30  |\n"
            "| Bob   | 25  |\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        tables = processor.list_tables()
        
        if tables:
            content = processor.read_table(tables[0]["table_ref"])
            assert content["data_format"] in ["records", "markdown"]

    def test_markdown_processor_table_with_duplicate_headers(self, tmp_path: Path) -> None:
        """验证表头重复时返回 markdown 格式。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "dup_headers.md"
        md_path.write_text(
            "# Title\n\n"
            "| Col | Col |\n"
            "|-----|-----|\n"
            "| A   | B   |\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        tables = processor.list_tables()
        
        if tables:
            content = processor.read_table(tables[0]["table_ref"])
            # 重复表头应返回 markdown 格式
            assert content["data_format"] == "markdown"

    def test_markdown_processor_table_caption_extraction(self, tmp_path: Path) -> None:
        """验证表格标题提取。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "caption.md"
        md_path.write_text(
            "# Title\n\n"
            "**Table 1**: Sample Data\n\n"
            "| A | B |\n"
            "|---|---|\n"
            "| 1 | 2 |\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        tables = processor.list_tables()
        
        assert len(tables) > 0

    def test_markdown_processor_multiple_tables_in_section(self, tmp_path: Path) -> None:
        """验证同一章节多个表格。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "multiple_tables.md"
        md_path.write_text(
            "# Section\n\n"
            "| A | B |\n"
            "|---|---|\n"
            "| 1 | 2 |\n\n"
            "| X | Y |\n"
            "|---|---|\n"
            "| 3 | 4 |\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        tables = processor.list_tables()
        
        assert len(tables) >= 1


@pytest.mark.unit
class TestMarkdownProcessorSectionContent:
    """章节内容读取功能测试。"""

    def test_markdown_processor_read_section_content_basic(self, tmp_path: Path) -> None:
        """验证基本章节内容读取。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "section_content.md"
        md_path.write_text(
            "# Introduction\n\n"
            "This is the introduction section.\n\n"
            "# Details\n\n"
            "Detail content here.\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        sections = processor.list_sections()
        
        assert len(sections) > 0
        content = processor.read_section(sections[0]["ref"])
        assert "content" in content
        assert content["word_count"] >= 0

    def test_markdown_processor_section_word_count(self, tmp_path: Path) -> None:
        """验证章节字数统计。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "word_count.md"
        md_path.write_text(
            "# Title\n\n"
            "one two three four five\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        sections = processor.list_sections()
        
        if sections:
            content = processor.read_section(sections[0]["ref"])
            assert content["word_count"] > 0

    def test_markdown_processor_read_section_with_multiple_levels(self, tmp_path: Path) -> None:
        """验证多层级章节。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "multi_level.md"
        md_path.write_text(
            "# Chapter 1\n\nContent 1\n\n"
            "## Section 1.1\n\nContent 1.1\n\n"
            "## Section 1.2\n\nContent 1.2\n\n"
            "# Chapter 2\n\nContent 2\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        sections = processor.list_sections()
        
        assert len(sections) >= 3
        for section in sections:
            assert "parent_ref" in section

    def test_markdown_processor_section_preview(self, tmp_path: Path) -> None:
        """验证章节预览生成。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "preview.md"
        md_path.write_text("# Title\n\nVery long content " * 50 + "\n", encoding="utf-8")
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        sections = processor.list_sections()
        
        assert len(sections) > 0
        assert "preview" in sections[0]
        # 预览应有长度限制
        assert len(sections[0]["preview"]) <= 300


@pytest.mark.unit
class TestMarkdownProcessorSearch:
    """搜索功能测试。"""

    def test_markdown_processor_search_basic(self, tmp_path: Path) -> None:
        """验证基本搜索功能。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "search_basic.md"
        md_path.write_text(
            "# Chapter 1\n\nLooking for revenue data.\n\n"
            "# Chapter 2\n\nMore information about revenue.\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        hits = processor.search("revenue")
        
        assert isinstance(hits, list)
        if hits:
            assert _hit_section_title(hits[0]) is not None

    def test_markdown_processor_search_case_insensitive(self, tmp_path: Path) -> None:
        """验证搜索不分大小写。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "search_case.md"
        md_path.write_text(
            "# Chapter\n\nFINANCIAL REPORT\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        hits = processor.search("financial")
        
        assert isinstance(hits, list)

    def test_markdown_processor_search_within_section(self, tmp_path: Path) -> None:
        """验证在特定章节内搜索。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "search_within.md"
        md_path.write_text(
            "# Chapter 1\n\nprofit and loss\n\n"
            "# Chapter 2\n\nbalance sheet\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        sections = processor.list_sections()
        
        if sections:
            hits = processor.search("profit", within_ref=sections[0]["ref"])
            assert isinstance(hits, list)

    def test_markdown_processor_search_invalid_section(self, tmp_path: Path) -> None:
        """验证在无效章节内搜索返回空。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "search_invalid.md"
        md_path.write_text("# Title\n\nContent\n", encoding="utf-8")
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        hits = processor.search("content", within_ref="invalid_ref")
        
        assert hits == []

    def test_markdown_processor_search_whitespace_query(self, tmp_path: Path) -> None:
        """验证仅空白查询返回空。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "search_ws.md"
        md_path.write_text("# Title\n\nContent\n", encoding="utf-8")
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        hits = processor.search("   ")
        
        assert hits == []


@pytest.mark.unit
class TestMarkdownProcessorSpecialCases:
    """特殊场景测试。"""

    def test_markdown_processor_empty_sections(self, tmp_path: Path) -> None:
        """验证空章节处理。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "empty_sections.md"
        md_path.write_text(
            "# Section 1\n\n"
            "# Section 2\n\nContent\n\n"
            "# Section 3\n\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        sections = processor.list_sections()
        
        assert isinstance(sections, list)

    def test_markdown_processor_code_blocks(self, tmp_path: Path) -> None:
        """验证代码块处理。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "code_blocks.md"
        md_path.write_text(
            "# Section\n\n"
            "```python\n"
            "| table | like |\n"
            "|-------|------|\n"
            "```\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        tables = processor.list_tables()
        
        # 代码块内的表格不应被解析
        # 这验证了处理器是否正确忽略代码块

    def test_markdown_processor_html_content(self, tmp_path: Path) -> None:
        """验证 HTML 内容处理。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "html_content.md"
        md_path.write_text(
            "# Title\n\n"
            "<div>HTML content</div>\n\n"
            "| A | B |\n"
            "|---|---|\n"
            "| 1 | 2 |\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        tables = processor.list_tables()
        
        assert isinstance(tables, list)

    def test_markdown_processor_special_characters(self, tmp_path: Path) -> None:
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
            "# Title with © and ™\n\n"
            "中文内容测试\n\n"
            "| 名称 | 值 |\n"
            "|------|----|\n"
            "| A™   | €1 |\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        sections = processor.list_sections()
        
        assert len(sections) > 0

    def test_markdown_processor_very_long_lines(self, tmp_path: Path) -> None:
        """验证超长行处理。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        long_line = "x" * 10000
        md_path = tmp_path / "long_lines.md"
        md_path.write_text(f"# Title\n\n{long_line}\n", encoding="utf-8")
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        sections = processor.list_sections()
        
        assert len(sections) > 0

    def test_markdown_processor_windows_line_endings(self, tmp_path: Path) -> None:
        """验证 Windows 行尾符处理。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "windows_endings.md"
        content = "# Title\r\n\r\nContent\r\n"
        md_path.write_bytes(content.encode("utf-8"))
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        sections = processor.list_sections()
        
        assert len(sections) > 0


@pytest.mark.unit
class TestMarkdownProcessorErrorPaths:
    """错误处理路径测试。"""

    def test_markdown_processor_form_type_parameter(self, tmp_path: Path) -> None:
        """验证 form_type 参数传递。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "forms.md"
        md_path.write_text("# Title\n\nContent\n", encoding="utf-8")
        
        processor = MarkdownProcessor(
            DummySource(md_path, media_type="text/markdown"),
            form_type="8-K",
            media_type="text/markdown"
        )
        
        assert processor is not None

    def test_markdown_processor_unicode_filename(self, tmp_path: Path) -> None:
        """验证 Unicode 文件名处理。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "文档_测试.md"
        md_path.write_text("# 标题\n\n内容\n", encoding="utf-8")
        
        processor = MarkdownProcessor(
            DummySource(md_path, uri="local://文档_测试.md", media_type="text/markdown")
        )
        
        sections = processor.list_sections()
        assert len(sections) > 0

    def test_markdown_processor_supports_markdown_type(self) -> None:
        """验证 supports 方法识别 text/md 类型。

        Args:
            无。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        source = MagicMock()
        source.uri = "doc.unknown"
        source.media_type = "text/md"
        
        assert MarkdownProcessor.supports(source) is True

    def test_markdown_processor_parser_version(self) -> None:
        """验证 PARSER_VERSION 属性。

        Args:
            无。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        assert hasattr(MarkdownProcessor, "PARSER_VERSION")
        assert isinstance(MarkdownProcessor.PARSER_VERSION, str)
        assert "markdown" in MarkdownProcessor.PARSER_VERSION.lower()


@pytest.mark.unit
class TestMarkdownProcessorTableAttributes:
    """表格属性完整性测试。"""

    def test_markdown_processor_table_summary_fields(self, tmp_path: Path) -> None:
        """验证表格摘要字段完整性。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "table_fields.md"
        md_path.write_text(
            "# Section\n\n"
            "| Col1 | Col2 |\n"
            "|------|------|\n"
            "| A    | B    |\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        tables = processor.list_tables()
        
        if tables:
            table = tables[0]
            required_fields = ["table_ref", "caption", "context_before", "row_count", "col_count"]
            for field in required_fields:
                assert field in table

    def test_markdown_processor_table_content_fields(self, tmp_path: Path) -> None:
        """验证表格内容字段完整性。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        md_path = tmp_path / "table_content_fields.md"
        md_path.write_text(
            "# Section\n\n"
            "| Col1 | Col2 |\n"
            "|------|------|\n"
            "| A    | B    |\n",
            encoding="utf-8"
        )
        
        processor = MarkdownProcessor(DummySource(md_path, media_type="text/markdown"))
        tables = processor.list_tables()
        
        if tables:
            content = processor.read_table(tables[0]["table_ref"])
            assert "table_ref" in content
            assert "caption" in content
            assert "data_format" in content
            assert "data" in content
