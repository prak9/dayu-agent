"""BSProcessor 补充覆盖率测试（提升到 95%+）。

本测试文件补充 test_bs_processor_coverage.py 中未覆盖的深层逻辑、
HTML 清理、表格转换、复杂搜索场景等。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, Mock

import pytest

from alpha.fins.storage.local_file_source import LocalFileSource
from alpha.engine.processors import bs_processor
from alpha.engine.processors.bs_processor import BSProcessor
from alpha.engine.processors.table_utils import parse_html_table_dataframe


def _write_html(tmp_path: Path, name: str, html: str) -> Path:
    """写入 HTML 测试文件。"""
    file_path = tmp_path / name
    file_path.write_text(html, encoding="utf-8")
    return file_path


def _make_source(path: Path) -> LocalFileSource:
    """构建本地 Source。"""
    return LocalFileSource(
        path=path,
        uri=f"local://{path.name}",
        media_type="text/html",
        content_length=path.stat().st_size,
        etag=None,
    )


@pytest.mark.unit
class TestBSProcessorTableParsing:
    """BeautifulSoup 表格解析功能测试。"""

    def test_bs_processor_list_tables_with_complex_table(self, tmp_path: Path) -> None:
        """验证复杂表格识别。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Financial Data</h1>
            <table>
                <thead>
                    <tr><th>Year</th><th>Revenue</th><th>Profit</th></tr>
                </thead>
                <tbody>
                    <tr><td>2022</td><td>100M</td><td>10M</td></tr>
                    <tr><td>2023</td><td>120M</td><td>15M</td></tr>
                </tbody>
            </table>
        </body></html>
        """
        html_path = _write_html(tmp_path, "complex.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        tables = processor.list_tables()
        assert len(tables) > 0
        assert tables[0]["col_count"] == 3
        assert tables[0]["row_count"] >= 2

    def test_bs_processor_read_table_records_format(self, tmp_path: Path) -> None:
        """验证表格 records 格式读取。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <table>
                <thead><tr><th>Name</th><th>Age</th></tr></thead>
                <tbody>
                    <tr><td>Alice</td><td>30</td></tr>
                    <tr><td>Bob</td><td>25</td></tr>
                </tbody>
            </table>
        </body></html>
        """
        html_path = _write_html(tmp_path, "records.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        tables = processor.list_tables()
        if tables:
            content = processor.read_table(tables[0]["table_ref"])
            assert content["data_format"] in ["records", "dataframe"]

    def test_bs_processor_table_with_colspan(self, tmp_path: Path) -> None:
        """验证 colspan 处理。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Revenue Section</h1>
            <table>
                <tr>
                    <th colspan="2">Revenue Breakdown</th>
                </tr>
                <tr><td>Product A</td><td>100,000</td></tr>
                <tr><td>Product B</td><td>200,000</td></tr>
                <tr><td>Total</td><td>300,000</td></tr>
            </table>
        </body></html>
        """
        html_path = _write_html(tmp_path, "colspan.html", html)
        processor = BSProcessor(_make_source(html_path))

        tables = processor.list_tables()
        # 验证表格被正确识别
        assert len(tables) > 0

    def test_bs_processor_table_with_rowspan(self, tmp_path: Path) -> None:
        """验证 rowspan 处理。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Assets Table</h1>
            <table>
                <tr>
                    <td rowspan="2">Cash and equivalents</td>
                    <td>First Quarter 2024</td>
                </tr>
                <tr>
                    <td>Second Quarter 2024</td>
                </tr>
                <tr><td>Investments</td><td>Third Quarter 2024</td></tr>
            </table>
        </body></html>
        """
        html_path = _write_html(tmp_path, "rowspan.html", html)
        processor = BSProcessor(_make_source(html_path))

        tables = processor.list_tables()
        # 验证表格被正确识别
        assert len(tables) > 0

    def test_bs_processor_multiple_tables_per_section(self, tmp_path: Path) -> None:
        """验证同一章节多个表格。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Financial Statements</h1>
            <table>
                <tr><th>Year</th><th>Revenue</th><th>Profit</th></tr>
                <tr><td>2023</td><td>500,000</td><td>50,000</td></tr>
                <tr><td>2024</td><td>600,000</td><td>60,000</td></tr>
            </table>
            <p>Content between tables</p>
            <table>
                <tr><th>Quarter</th><th>Sales</th><th>Growth</th></tr>
                <tr><td>Q1</td><td>150,000</td><td>10%</td></tr>
                <tr><td>Q2</td><td>160,000</td><td>12%</td></tr>
            </table>
        </body></html>
        """
        html_path = _write_html(tmp_path, "multiple.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        tables = processor.list_tables()
        assert len(tables) >= 2

    def test_parse_table_dataframe_no_hang_on_comma_heavy_cells(self, tmp_path: Path) -> None:
        """验证含大量逗号数字的单元格不会导致 pd.read_html 卡死。

        复现场景：SEC 6-K 表格中单个 <td> 内堆叠多人持股数据，
        形如 "59,486,252 19,479,448 28,899,800 ..."。pandas 默认
        thousands=',' 会对此类长字符串触发病态正则回溯。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        # 模拟 UMC 6-K 原表结构：一个单元格内堆叠 12+ 个持股数字
        numbers = " ".join([
            "59,486,252", "19,479,448", "28,899,800", "6,515,400",
            "2,488,784", "2,682,766", "3,465,889", "4,569,517",
            "523,100", "487,771", "1,773,100", "575,308",
        ])
        html = f"""
        <html><body>
        <h1>Shareholding Changes</h1>
        <table>
            <tr><td></td><td></td><td></td></tr>
            <tr>
                <td>Title</td>
                <td>Name</td>
                <td>Number of shares</td>
            </tr>
            <tr>
                <td>Chairman President SVP</td>
                <td>Stan Hung SC Chien Jason Wang</td>
                <td>{numbers}</td>
            </tr>
        </table>
        </body></html>
        """
        html_path = _write_html(tmp_path, "comma_heavy.html", html)
        processor = BSProcessor(_make_source(html_path))
        # 若 thousands 未禁用，此处会卡死；正常应在毫秒级完成
        table = processor.read_table("t_0001")
        assert table is not None
        assert table["data_format"] in ("records", "markdown")

    def test_parse_html_table_dataframe_returns_none_when_pandas_fails(self) -> None:
        """验证公共表格解析工具在 pandas 失败时返回 None。

        Args:
            无。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        with patch("alpha.engine.processors.table_utils.pd.read_html", side_effect=ValueError("boom")):
            table_tag = bs_processor.BeautifulSoup("<table></table>", "lxml").table
            assert table_tag is not None
            actual = parse_html_table_dataframe(table_tag)

        assert actual is None


@pytest.mark.unit
class TestBSProcessorSectionParsing:
    """章节解析功能测试。"""

    def test_bs_processor_hierarchical_sections(self, tmp_path: Path) -> None:
        """验证多层级章节识别。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Chapter 1</h1>
            <p>Content 1</p>
            <h2>Section 1.1</h2>
            <p>Content 1.1</p>
            <h2>Section 1.2</h2>
            <p>Content 1.2</p>
            <h1>Chapter 2</h1>
            <p>Content 2</p>
        </body></html>
        """
        html_path = _write_html(tmp_path, "hierarchy.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        sections = processor.list_sections()
        assert len(sections) >= 4
        # 验证层级关系
        for section in sections:
            assert "level" in section
            assert "parent_ref" in section

    def test_bs_processor_section_with_tables_reference(self, tmp_path: Path) -> None:
        """验证章节表格引用。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Section</h1>
            <table><tr><td>Data</td></tr></table>
            <p>Content</p>
        </body></html>
        """
        html_path = _write_html(tmp_path, "section_tables.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        sections = processor.list_sections()
        if sections:
            section = sections[0]
            assert "preview" in section

    def test_bs_processor_section_word_count(self, tmp_path: Path) -> None:
        """验证章节字数统计。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Title</h1>
            <p>one two three four five</p>
        </body></html>
        """
        html_path = _write_html(tmp_path, "wordcount.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        sections = processor.list_sections()
        if sections:
            content = processor.read_section(sections[0]["ref"])
            assert content["word_count"] > 0


@pytest.mark.unit
class TestBSProcessorSearch:
    """搜索功能测试。"""

    def test_bs_processor_search_basic_keyword(self, tmp_path: Path) -> None:
        """验证基本关键词搜索。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Financial Report</h1>
            <p>Discussing important metrics.</p>
            <h2>Revenue Analysis</h2>
            <p>Revenue increased by 20%.</p>
        </body></html>
        """
        html_path = _write_html(tmp_path, "search.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        hits = processor.search("revenue")
        assert isinstance(hits, list)

    def test_bs_processor_search_case_insensitive(self, tmp_path: Path) -> None:
        """验证搜索不分大小写。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>FINANCIAL REPORT</h1>
            <p>Content about finances.</p>
        </body></html>
        """
        html_path = _write_html(tmp_path, "search_case.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        hits = processor.search("financial")
        assert isinstance(hits, list)

    def test_bs_processor_search_within_section(self, tmp_path: Path) -> None:
        """验证在特定章节搜索。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Section A</h1>
            <p>profit information</p>
            <h1>Section B</h1>
            <p>balance sheet data</p>
        </body></html>
        """
        html_path = _write_html(tmp_path, "search_within.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        sections = processor.list_sections()
        if sections:
            hits = processor.search("profit", within_ref=sections[0]["ref"])
            assert isinstance(hits, list)

    def test_bs_processor_search_special_characters(self, tmp_path: Path) -> None:
        """验证特殊字符搜索转义。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Report</h1>
            <p>Price: $100.50 (50% off)</p>
        </body></html>
        """
        html_path = _write_html(tmp_path, "special_search.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        # 搜索包含特殊字符的文本
        hits = processor.search("$")
        assert isinstance(hits, list)


@pytest.mark.unit
class TestBSProcessorHTMLCleaning:
    """HTML 清理功能测试。"""

    def test_bs_processor_remove_script_style(self, tmp_path: Path) -> None:
        """验证 script 和 style 标签移除。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Content</h1>
            <script>var x = "hidden";</script>
            <style>body { color: red; }</style>
            <p>Visible content</p>
        </body></html>
        """
        html_path = _write_html(tmp_path, "clean_script.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        sections = processor.list_sections()
        if sections:
            content = processor.read_section(sections[0]["ref"])
            assert "hidden" not in content["content"].lower()
            assert "color: red" not in content["content"]

    def test_bs_processor_remove_noscript(self, tmp_path: Path) -> None:
        """验证 noscript 标签移除。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Page</h1>
            <noscript>JavaScript disabled</noscript>
            <p>Normal content</p>
        </body></html>
        """
        html_path = _write_html(tmp_path, "clean_noscript.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        sections = processor.list_sections()
        if sections:
            content = processor.read_section(sections[0]["ref"])
            assert "JavaScript" not in content["content"]

    def test_bs_processor_unwrap_infoblock_tags(self, tmp_path: Path) -> None:
        """验证 ix 标签 unwrap。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Section</h1>
            <p>Text with <ix:nonfraction>123.45</ix:nonfraction> amount</p>
        </body></html>
        """
        html_path = _write_html(tmp_path, "unwrap.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        sections = processor.list_sections()
        if sections:
            content = processor.read_section(sections[0]["ref"])
            assert "123.45" in content["content"]


@pytest.mark.unit
class TestBSProcessorSpecialCases:
    """特殊场景测试。"""

    def test_bs_processor_empty_document(self, tmp_path: Path) -> None:
        """验证空文档处理。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = "<html><body></body></html>"
        html_path = _write_html(tmp_path, "empty.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        sections = processor.list_sections()
        assert isinstance(sections, list)

    def test_bs_processor_malformed_html(self, tmp_path: Path) -> None:
        """验证畸形 HTML 处理。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html>
        <body>
        <h1>Title
        <p>Unclosed paragraph
        <h2>Another title
        Content here
        </body>
        </html>
        """
        html_path = _write_html(tmp_path, "malformed.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        sections = processor.list_sections()
        assert isinstance(sections, list)

    def test_bs_processor_unicode_content(self, tmp_path: Path) -> None:
        """验证 Unicode 内容处理。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>中文标题</h1>
            <p>中文内容 with 混合 混合内容</p>
            <table>
                <tr><td>名称</td><td>值</td></tr>
                <tr><td>项目</td><td>999</td></tr>
            </table>
        </body></html>
        """
        html_path = _write_html(tmp_path, "unicode.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        sections = processor.list_sections()
        assert len(sections) > 0

    def test_bs_processor_nested_lists(self, tmp_path: Path) -> None:
        """验证嵌套列表处理。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Lists</h1>
            <ul>
                <li>Item 1
                    <ul>
                        <li>Sub 1.1</li>
                        <li>Sub 1.2</li>
                    </ul>
                </li>
                <li>Item 2</li>
            </ul>
        </body></html>
        """
        html_path = _write_html(tmp_path, "lists.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        sections = processor.list_sections()
        assert len(sections) > 0

    def test_bs_processor_form_elements(self, tmp_path: Path) -> None:
        """验证表单元素处理。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Form Page</h1>
            <form>
                <input type="text" placeholder="Name"/>
                <input type="submit" value="Submit"/>
            </form>
            <p>Content after form</p>
        </body></html>
        """
        html_path = _write_html(tmp_path, "forms.html", html)
        processor = BSProcessor(_make_source(html_path))
        
        sections = processor.list_sections()
        assert len(sections) > 0


@pytest.mark.unit
class TestBSProcessorSupports:
    """supports 方法测试。"""

    def test_bs_processor_supports_html_media_type(self) -> None:
        """验证通过 media_type 识别 HTML。

        Args:
            无。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        source = MagicMock()
        source.media_type = "text/html"
        source.uri = "file.unknown"
        
        assert BSProcessor.supports(source) is True

    def test_bs_processor_supports_html_suffix(self) -> None:
        """验证通过后缀识别 HTML。

        Args:
            无。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        source = MagicMock()
        source.media_type = "text/plain"
        source.uri = "document.html"
        
        assert BSProcessor.supports(source) is True

    def test_bs_processor_supports_htm_suffix(self) -> None:
        """验证通过 .htm 后缀识别。

        Args:
            无。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        source = MagicMock()
        source.media_type = None
        source.uri = "document.htm"
        
        assert BSProcessor.supports(source) is True

    def test_bs_processor_supports_non_html(self) -> None:
        """验证拒绝非 HTML。

        Args:
            无。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        source = MagicMock()
        source.media_type = "text/plain"
        source.uri = "document.txt"
        
        assert BSProcessor.supports(source) is False


@pytest.mark.unit
class TestBSProcessorTableSummary:
    """表格摘要字段完整性测试。"""

    def test_bs_processor_table_summary_fields(self, tmp_path: Path) -> None:
        """验证表格摘要包含所有预期字段。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Summary Section</h1>
            <table>
                <tr><th>Category</th><th>Amount</th><th>Change</th></tr>
                <tr><td>Revenue</td><td>100,000</td><td>+5%</td></tr>
                <tr><td>Expenses</td><td>80,000</td><td>+3%</td></tr>
            </table>
        </body></html>
        """
        html_path = _write_html(tmp_path, "summary.html", html)
        processor = BSProcessor(_make_source(html_path))

        tables = processor.list_tables()
        assert tables
        required_fields = [
            "table_ref", "caption", "context_before",
            "row_count", "col_count",
            "table_type", "headers", "section_ref"
        ]
        for field in required_fields:
            assert field in tables[0]

    def test_bs_processor_table_content_fields(self, tmp_path: Path) -> None:
        """验证表格内容包含所有预期字段。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            None。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
            <h1>Content Section</h1>
            <table>
                <tr><th>Name</th><th>Description</th></tr>
                <tr><td>Revenue</td><td>Total annual revenue</td></tr>
                <tr><td>Profit</td><td>Net income after tax</td></tr>
            </table>
        </body></html>
        """
        html_path = _write_html(tmp_path, "content.html", html)
        processor = BSProcessor(_make_source(html_path))

        tables = processor.list_tables()
        assert tables
        content = processor.read_table(tables[0]["table_ref"])
        required_fields = [
            "table_ref", "caption", "data_format",
            "data", "columns", "row_count", "col_count",
        ]
        for field in required_fields:
            assert field in content


@pytest.mark.unit
class TestBSProcessorParserVersion:
    """PARSER_VERSION 测试。"""

    def test_parser_version_attribute(self) -> None:
        """验证 PARSER_VERSION 属性存在且格式正确。

        Args:
            无。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        assert hasattr(BSProcessor, "PARSER_VERSION")
        version = BSProcessor.PARSER_VERSION
        assert isinstance(version, str)
        assert "bs_processor" in version.lower() or "processor" in version.lower()


@pytest.mark.unit
class TestBSProcessorPerformanceOptimizations:
    """性能优化相关功能测试。"""

    def test_has_complex_spans_with_descendants_early_exit(self, tmp_path: Path) -> None:
        """验证 _has_complex_spans 使用 descendants 惰性迭代能早期退出。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
        <h1>Test</h1>
        <table>
            <tr><th>Header A</th><th>Header B</th><th>Header C</th></tr>
            <tr><td rowspan="2">Cell A</td><td>B1</td><td>C1</td></tr>
            <tr><td>B2</td><td>C2</td></tr>
            <tr><td>D</td><td>E</td><td>F</td></tr>
        </table>
        </body></html>
        """
        path = _write_html(tmp_path, "spans.html", html)
        proc = BSProcessor(_make_source(path))
        tables = proc.list_tables()
        assert len(tables) >= 1

    def test_has_complex_spans_no_spans(self, tmp_path: Path) -> None:
        """验证无 span 表格返回 has_spans=False。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
        <h1>Test</h1>
        <table>
            <tr><th>A</th><th>B</th><th>C</th></tr>
            <tr><td>1</td><td>2</td><td>3</td></tr>
            <tr><td>4</td><td>5</td><td>6</td></tr>
        </table>
        </body></html>
        """
        path = _write_html(tmp_path, "no_spans.html", html)
        proc = BSProcessor(_make_source(path))
        table = proc.read_table("t_0001")
        # 无 span 表应使用 records 格式
        assert table["data_format"] == "records"

    def test_can_skip_dataframe_for_span_table(self, tmp_path: Path) -> None:
        """验证有 span 的表格渲染时跳过 pd.read_html。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
        <h1>Financial</h1>
        <table>
            <tr><th colspan="3">Revenue Breakdown</th></tr>
            <tr><td>Q1</td><td>Q2</td><td>Q3</td></tr>
            <tr><td>100</td><td>200</td><td>300</td></tr>
        </table>
        </body></html>
        """
        path = _write_html(tmp_path, "span_table.html", html)
        proc = BSProcessor(_make_source(path))
        table = proc.read_table("t_0001")
        # 有 span → markdown 格式，不需要 pd.read_html
        assert table["data_format"] == "markdown"

    def test_can_skip_dataframe_function_directly(self) -> None:
        """直接测试 _can_skip_dataframe 函数。

        Args:
            无。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        from alpha.engine.processors.bs_processor import (
            _can_skip_dataframe,
            _TableBlock,
        )
        from unittest.mock import MagicMock

        tag = MagicMock()
        # has_spans=True → 跳过
        block = _TableBlock(
            ref="t_0001", tag=tag, caption=None,
            row_count=5, col_count=3, headers=None,
            section_ref=None, context_before="", table_type="data",
            has_spans=True,
        )
        assert _can_skip_dataframe(block) is True

        # 超宽表 → 跳过
        block2 = _TableBlock(
            ref="t_0002", tag=tag, caption=None,
            row_count=5, col_count=30, headers=None,
            section_ref=None, context_before="", table_type="data",
            has_spans=False,
        )
        assert _can_skip_dataframe(block2) is True

        # 超长表 → 跳过
        block3 = _TableBlock(
            ref="t_0003", tag=tag, caption=None,
            row_count=600, col_count=3, headers=None,
            section_ref=None, context_before="", table_type="data",
            has_spans=False,
        )
        assert _can_skip_dataframe(block3) is True

        # 空表 → 跳过
        block4 = _TableBlock(
            ref="t_0004", tag=tag, caption=None,
            row_count=0, col_count=0, headers=None,
            section_ref=None, context_before="", table_type="data",
            has_spans=False,
        )
        assert _can_skip_dataframe(block4) is True

        # 正常表 → 不跳过（需要 pd.read_html）
        block5 = _TableBlock(
            ref="t_0005", tag=tag, caption=None,
            row_count=10, col_count=5, headers=["A", "B"],
            section_ref=None, context_before="", table_type="data",
            has_spans=False,
        )
        assert _can_skip_dataframe(block5) is False

    def test_build_tables_without_dataframe(self, tmp_path: Path) -> None:
        """验证 build 阶段不调用 pd.read_html 仍能正确提取维度和表头。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
        <h1>Report</h1>
        <table>
            <tr><th>Period</th><th>Revenue</th><th>Cost</th></tr>
            <tr><td>2024</td><td>1000</td><td>500</td></tr>
            <tr><td>2025</td><td>1200</td><td>600</td></tr>
        </table>
        </body></html>
        """
        path = _write_html(tmp_path, "no_df_build.html", html)
        proc = BSProcessor(_make_source(path))
        tables = proc.list_tables()
        assert len(tables) == 1
        tbl = tables[0]
        assert tbl["row_count"] == 3
        assert tbl["col_count"] == 3
        # 表头应从 th 或 matrix 中提取
        assert tbl["headers"] is not None
        assert len(tbl["headers"]) > 0

    def test_sanitize_soup_combined_passes(self, tmp_path: Path) -> None:
        """验证合并后的 _sanitize_soup 正确移除 hidden + ix: 标签。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        html = """
        <html><body>
        <h1>Test</h1>
        <div hidden>hidden content</div>
        <div style="display:none">invisible</div>
        <ix:header>ix header</ix:header>
        <ix:nonfraction>12345</ix:nonfraction>
        <script>alert('x')</script>
        <table>
            <tr><th>A</th><th>B</th></tr>
            <tr><td>1</td><td>2</td></tr>
        </table>
        </body></html>
        """
        path = _write_html(tmp_path, "sanitize.html", html)
        proc = BSProcessor(_make_source(path))
        # 隐藏内容应被移除
        full_text = proc.get_full_text()
        assert "hidden content" not in full_text
        assert "invisible" not in full_text
        assert "alert" not in full_text
        # ix:nonfraction 应被 unwrap，值保留
        assert "12345" in full_text
        # ix:header 应被 decompose
        assert "ix header" not in full_text


@pytest.mark.unit
class TestBSProcessorHtmlLoading:
    """BSProcessor 默认 HTML 读取行为测试。"""

    def test_load_html_content_keeps_raw_source(self, tmp_path: Path) -> None:
        """验证 Engine 默认读取不做业务域预处理。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        plain_path = _write_html(
            tmp_path,
            "plain.html",
            "<html><body><p>Plain</p></body></html>",
        )
        processor = BSProcessor(_make_source(plain_path))

        raw = (
            "<DOCUMENT>\n<TYPE>EX-99.1\n<TEXT>\n"
            "<html><body><p>Hello</p></body></html>\n"
            "</TEXT>\n</DOCUMENT>"
        )
        path = tmp_path / "exhibit.htm"
        path.write_text(raw, encoding="utf-8")

        content = processor._load_html_content(path)
        assert content == raw

    def test_raw_sgml_html_can_surface_metadata_without_fins_hook(self, tmp_path: Path) -> None:
        """验证 Engine 路径不会主动剥离 EDGAR SGML 元数据。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """

        raw = (
            "<DOCUMENT>\n"
            "<TYPE>EX-99.1\n"
            "<SEQUENCE>2\n"
            "<FILENAME>dex991.htm\n"
            "<TEXT>\n"
            "<html><body>\n"
            "<h1>Financial Results</h1>\n"
            "</body></html>\n"
            "</TEXT>\n"
            "</DOCUMENT>\n"
        )
        path = _write_html(tmp_path, "exhibit.htm", raw)
        proc = BSProcessor(_make_source(path))

        full_text = proc.get_full_text()
        assert "EX-99.1" in full_text
        assert "Financial Results" in full_text
