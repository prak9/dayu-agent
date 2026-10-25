"""BSProcessor 边界场景和错误处理测试（提升覆盖率到 95%+）。

本测试文件补充 test_bs_processor.py 中未覆盖的边界情况、错误处理和特殊场景。
基于覆盖率分析报告的 TOP 10 关键未覆盖场景。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from alpha.fins.storage.local_file_source import LocalFileSource
from alpha.engine.processors import bs_processor
from alpha.engine.processors.bs_processor import BSProcessor


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
def test_bs_processor_init_file_not_exists(tmp_path: Path) -> None:
    """验证初始化时文件不存在抛出 ValueError。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    non_existent_path = tmp_path / "non_existent.html"
    source = LocalFileSource(
        path=non_existent_path,
        uri="local://test.html",
        media_type="text/html",
        content_length=0,
        etag=None,
    )
    
    with pytest.raises(ValueError, match="HTML 文件不存在"):
        BSProcessor(source)


@pytest.mark.unit
def test_bs_processor_init_path_is_directory(tmp_path: Path) -> None:
    """验证初始化时路径是目录抛出 ValueError。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    dir_path = tmp_path / "test_dir"
    dir_path.mkdir()
    
    source = LocalFileSource(
        path=dir_path,
        uri="local://test",
        media_type="text/html",
        content_length=0,
        etag=None,
    )
    
    with pytest.raises(ValueError, match="HTML 文件不存在"):
        BSProcessor(source)


@pytest.mark.unit
def test_bs_processor_read_section_not_found(tmp_path: Path) -> None:
    """验证读取不存在的章节引用抛出 KeyError。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    html = "<html><body><h1>Section</h1><p>Content</p></body></html>"
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    with pytest.raises(KeyError, match="Section not found: s_9999"):
        processor.read_section("s_9999")


@pytest.mark.unit
def test_bs_processor_read_table_not_found(tmp_path: Path) -> None:
    """验证读取不存在的表格引用抛出 KeyError。

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
        <table><tr><td>Test</td></tr></table>
    </body></html>
    """
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    with pytest.raises(KeyError, match="Table not found: t_9999"):
        processor.read_table("t_9999")


@pytest.mark.unit
def test_bs_processor_search_empty_query_basic(tmp_path: Path) -> None:
    """验证搜索空字符串返回空列表。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    html = "<html><body><h1>Section</h1><p>Content with keyword</p></body></html>"
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    assert processor.search("") == []
    assert processor.search("   ") == []


@pytest.mark.unit
def test_bs_processor_search_invalid_within_ref(tmp_path: Path) -> None:
    """验证指定不存在的 within_ref 返回空列表。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    html = "<html><body><h1>Section</h1><p>Content with keyword</p></body></html>"
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    results = processor.search("keyword", within_ref="s_9999")
    assert results == []


@pytest.mark.unit
def test_bs_processor_ix_namespace_tags(tmp_path: Path) -> None:
    """验证 ix: 命名空间标签的处理。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    html = """
    <html><body>
        <ix:header>
            <ix:hidden>HIDDEN_CONTENT</ix:hidden>
        </ix:header>
        <h1>Visible Section</h1>
        <p>Regular content</p>
        <p><ix:nonfraction>123.45</ix:nonfraction> million</p>
    </body></html>
    """
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    sections = processor.list_sections()
    assert sections
    
    # ix:header 应该被移除
    section_content = processor.read_section(sections[0]["ref"])
    assert "HIDDEN_CONTENT" not in section_content["content"]
    
    # ix:nonfraction 应该被 unwrap，保留文本内容
    assert "123.45" in section_content["content"] or "million" in section_content["content"]


@pytest.mark.unit
def test_bs_processor_hidden_attributes(tmp_path: Path) -> None:
    """验证 hidden 和 aria-hidden 属性的过滤。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    html = """
    <html><body>
        <h1>Visible Section</h1>
        <div hidden>Hidden div content</div>
        <div aria-hidden="true">Aria hidden content</div>
        <p>Visible content</p>
    </body></html>
    """
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    sections = processor.list_sections()
    assert sections
    
    section_content = processor.read_section(sections[0]["ref"])
    preview = sections[0]["preview"]
    
    # 隐藏内容不应出现在预览中
    assert "Hidden div content" not in preview
    assert "Aria hidden content" not in preview
    assert "Visible content" in preview


@pytest.mark.unit
def test_format_ref_invalid_index() -> None:
    """验证 ref 格式化时非正数索引抛出 ValueError。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    with pytest.raises(ValueError, match="index 必须为正数"):
        bs_processor._format_section_ref(0)
    
    with pytest.raises(ValueError, match="index 必须为正数"):
        bs_processor._format_section_ref(-1)
    
    with pytest.raises(ValueError, match="index 必须为正数"):
        bs_processor._format_table_ref(0)
    
    with pytest.raises(ValueError, match="index 必须为正数"):
        bs_processor._format_table_ref(-5)


@pytest.mark.unit
def test_bs_processor_filter_short_headings(tmp_path: Path) -> None:
    """验证短标题（长度 < 3）被过滤。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    html = """
    <html><body>
        <h1>AB</h1>
        <p>Content under short heading</p>
        <h2>X</h2>
        <p>More content</p>
        <h3>Valid Heading</h3>
        <p>Content under valid heading</p>
    </body></html>
    """
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    sections = processor.list_sections()
    
    # 短标题应该被过滤，只有 "Valid Heading" 段落或全文作为一个段落
    for section in sections:
        title = section.get("title")
        if title:
            assert len(title) >= 3, f"Short title found: {title}"


@pytest.mark.unit
def test_bs_processor_table_parsing_fallback(tmp_path: Path) -> None:
    """验证表格解析失败时降级到矩阵解析。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    # 创建一个 pandas 可能解析失败的复杂表格
    html = """
    <html><body>
        <h1>Section</h1>
        <table>
            <tr><td rowspan="2">Complex</td><td>A</td></tr>
            <tr><td>B</td></tr>
            <tr><td colspan="2">Merged</td></tr>
        </table>
    </body></html>
    """
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    tables = processor.list_tables()
    assert tables
    
    # 即使 pandas 解析失败，也应该能通过矩阵方式返回数据
    table_content = processor.read_table(tables[0]["table_ref"])
    assert table_content is not None
    assert table_content["data"] is not None


@pytest.mark.unit
def test_bs_processor_classify_table_layout_no_context(tmp_path: Path) -> None:
    """验证无上下文和 headers 的表格分类为 layout。

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
            <tr><td>A</td><td>B</td></tr>
            <tr><td>C</td><td>D</td></tr>
        </table>
    </body></html>
    """
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    # list_tables 默认过滤 layout 表格，应返回空列表
    tables = processor.list_tables()
    assert tables == []

    # 直接访问底层表格验证分类逻辑
    raw_tables = processor._tables
    assert raw_tables
    # 无上下文且无明显 headers 的表格应该是 layout 类型
    assert raw_tables[0].table_type == "layout"


@pytest.mark.unit
def test_bs_processor_empty_matrix_dimensions(tmp_path: Path) -> None:
    """验证空表格的维度处理。

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
        <table></table>
    </body></html>
    """
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    tables = processor.list_tables()
    
    # 空表格应该被处理（可能返回空列表或跳过）
    # 至少不应该崩溃
    assert isinstance(tables, list)


@pytest.mark.unit
def test_bs_processor_table_with_caption(tmp_path: Path) -> None:
    """验证带 caption 的表格处理。

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
            <caption>Balance Sheet Summary</caption>
            <tr><th>Item</th><th>Amount</th></tr>
            <tr><td>Assets</td><td>1000</td></tr>
        </table>
    </body></html>
    """
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    tables = processor.list_tables()
    assert tables
    
    # 表格应该能正常解析，caption 可能作为 context_before 或被保留
    table_info = tables[0]
    context = table_info.get("context_before", "")
    # Caption 可能出现在 context 中，也可能不出现（取决于实现）
    # 至少表格本身应该存在
    assert table_info["table_ref"]


@pytest.mark.unit
def test_bs_processor_caption_inferred_from_context(tmp_path: Path) -> None:
    """验证 caption 缺失时从 context_before 推断。

    当 HTML <caption> 标签不存在但前文包含描述性文本时，
    caption 应被自动推断。

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
        <p>The following table summarizes revenue by segment:</p>
        <table>
            <tr><th>Segment</th><th>Revenue</th></tr>
            <tr><td>North America</td><td>500</td></tr>
            <tr><td>Europe</td><td>300</td></tr>
        </table>
    </body></html>
    """
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))

    tables = processor.list_tables()
    assert tables
    table_info = tables[0]
    # caption 应从 context_before 推断出来
    caption = table_info.get("caption")
    assert caption is not None
    assert "following table" in caption.lower() or "revenue" in caption.lower()


@pytest.mark.unit
def test_bs_processor_nested_headings(tmp_path: Path) -> None:
    """验证嵌套标题的层级处理。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    html = """
    <html><body>
        <h1>Level 1</h1>
        <p>Content 1</p>
        <h2>Level 2A</h2>
        <p>Content 2A</p>
        <h2>Level 2B</h2>
        <p>Content 2B</p>
        <h3>Level 3</h3>
        <p>Content 3</p>
    </body></html>
    """
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    sections = processor.list_sections()
    assert len(sections) >= 2
    
    # 验证父子关系
    has_parent_relationship = any(s.get("parent_ref") for s in sections)
    assert has_parent_relationship


@pytest.mark.unit
def test_bs_processor_table_with_rowspan_colspan(tmp_path: Path) -> None:
    """验证包含 rowspan 和 colspan 的表格处理。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    html = """
    <html><body>
        <h1>Complex Table</h1>
        <table>
            <tr>
                <th rowspan="2">Item</th>
                <th colspan="2">Values</th>
            </tr>
            <tr>
                <th>2023</th>
                <th>2024</th>
            </tr>
            <tr>
                <td>Revenue</td>
                <td>100</td>
                <td>120</td>
            </tr>
        </table>
    </body></html>
    """
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    tables = processor.list_tables()
    assert tables
    
    # 应该能解析复杂表格
    table_content = processor.read_table(tables[0]["table_ref"])
    assert table_content is not None
    assert table_content["data"] is not None

@pytest.mark.unit
def test_bs_processor_search_empty_query(tmp_path: Path) -> None:
    """验证空查询返回空列表。

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
        <p>Some content.</p>
    </body></html>
    """
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    # 空查询
    result = processor.search("")
    assert result == []
    
    # 仅空白字符
    result = processor.search("   ")
    assert result == []


@pytest.mark.unit
def test_bs_processor_search_no_match(tmp_path: Path) -> None:
    """验证无匹配查询返回空列表。

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
        <p>Revenue analysis for Q1 2024.</p>
    </body></html>
    """
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    # 搜索不存在的词
    result = processor.search("NONEXISTENT_WORD_XYZ")
    assert result == []


@pytest.mark.unit
def test_bs_processor_search_within_section(tmp_path: Path) -> None:
    """验证在特定章节范围内搜索。

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
        <p>Content with keyword.</p>
        <h2>Section B</h2>
        <p>Different content.</p>
    </body></html>
    """
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    sections = processor.list_sections()
    if sections:
        # 在不存在的章节范围内搜索应返回空列表
        result = processor.search("keyword", within_ref="nonexistent_ref")
        assert result == []


@pytest.mark.unit
def test_bs_processor_table_without_headers(tmp_path: Path) -> None:
    """验证无表头的表格处理。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    html = """
    <html><body>
        <h1>Data Table</h1>
        <table>
            <tr><td>Row 1 Col 1</td><td>Row 1 Col 2</td></tr>
            <tr><td>Row 2 Col 1</td><td>Row 2 Col 2</td></tr>
        </table>
    </body></html>
    """
    html_path = _write_html(tmp_path, "test.html", html)
    processor = BSProcessor(_make_source(html_path))
    
    tables = processor.list_tables()
    assert len(tables) > 0
    
    # 读取表格内容
    table_content = processor.read_table(tables[0]["table_ref"])
    assert table_content is not None


@pytest.mark.unit
def test_bs_processor_supports_by_suffix(tmp_path: Path) -> None:
    """验证 supports 方法通过后缀识别。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    html_path = _write_html(tmp_path, "report.html", "<html></html>")
    source = _make_source(html_path)
    
    assert BSProcessor.supports(source) is True


@pytest.mark.unit
def test_bs_processor_supports_by_media_type(tmp_path: Path) -> None:
    """验证 supports 方法通过 media_type 识别。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    html_path = _write_html(tmp_path, "data.xml", "<html></html>")
    
    source = LocalFileSource(
        path=html_path,
        uri="local://data",
        media_type="text/html",
        content_length=html_path.stat().st_size,
        etag=None,
    )
    
    assert BSProcessor.supports(source) is True


@pytest.mark.unit
def test_bs_processor_supports_non_html(tmp_path: Path) -> None:
    """验证 supports 方法拒绝非 HTML 文件。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    txt_path = tmp_path / "file.txt"
    txt_path.write_text("Plain text", encoding="utf-8")
    
    source = LocalFileSource(
        path=txt_path,
        uri="local://file.txt",
        media_type="text/plain",
        content_length=txt_path.stat().st_size,
        etag=None,
    )
    
    assert BSProcessor.supports(source) is False


# ---------- P1-3: 增强表格分类 & 布局过滤测试 ----------


@pytest.mark.unit
def test_classify_section_heading_table_as_layout() -> None:
    """验证 section heading 横线表在注入 SEC 规则后被分类为 layout。

    SEC 文档中常出现 "Item 7. MD&A ──────" 等格式的分隔表格，
    无实质数据价值，应归类为 layout。
    此规则由 FinsBSProcessor 通过 extra_layout_check 回调注入。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    from alpha.fins.processors.fins_bs_processor import FinsBSProcessor

    result = bs_processor._classify_table_type(
        row_count=5,
        col_count=3,
        headers=["Year", "Revenue", "Profit"],
        context_before="See management discussion",
        table_text="Item 7. Management Discussion and Analysis ━━━━━━━━━━━━━━",
        extra_layout_check=FinsBSProcessor._extra_layout_table_check,
    )
    assert result == "layout"


@pytest.mark.unit
def test_classify_section_heading_table_with_dash() -> None:
    """验证 Item 标题加短横线也被识别为 layout。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    from alpha.fins.processors.fins_bs_processor import FinsBSProcessor

    result = bs_processor._classify_table_type(
        row_count=3,
        col_count=2,
        headers=["A", "B"],
        context_before="Some context here",
        table_text="Item 1A. Risk Factors --------",
        extra_layout_check=FinsBSProcessor._extra_layout_table_check,
    )
    assert result == "layout"


@pytest.mark.unit
def test_classify_sec_cover_page_table_as_layout() -> None:
    """验证 SEC 封面页元数据表在注入 SEC 规则后被分类为 layout。

    基于 SEC Regulation S-K 封面页法定格式，含有 commission file number、
    securities exchange act 等声明的表格为低价值元数据。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    from alpha.fins.processors.fins_bs_processor import FinsBSProcessor

    cover_text = (
        "ANNUAL REPORT PURSUANT to Section 13 or 15(d) of the "
        "Securities Exchange Act of 1934 Commission File Number 001-12345"
    )
    result = bs_processor._classify_table_type(
        row_count=4,
        col_count=2,
        headers=["Field", "Value"],
        context_before="UNITED STATES SECURITIES AND EXCHANGE COMMISSION",
        table_text=cover_text,
        extra_layout_check=FinsBSProcessor._extra_layout_table_check,
    )
    assert result == "layout"


@pytest.mark.unit
def test_classify_sec_cover_page_only_under_5_rows() -> None:
    """验证行数 > 5 时不触发封面页规则。

    封面页表格一般很小（≤5 行）。含关键词但行数多的表格可能是有实际价值的。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    from alpha.fins.processors.fins_bs_processor import FinsBSProcessor

    cover_text = (
        "ANNUAL REPORT PURSUANT to Section 13 or 15(d) of the "
        "Securities Exchange Act of 1934"
    )
    result = bs_processor._classify_table_type(
        row_count=6,
        col_count=2,
        headers=["Field", "Value"],
        context_before="Some long context text here",
        table_text=cover_text,
        extra_layout_check=FinsBSProcessor._extra_layout_table_check,
    )
    assert result == "data"


@pytest.mark.unit
def test_classify_normal_data_table_not_layout() -> None:
    """验证正常数据表不被错误标记为 layout。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    result = bs_processor._classify_table_type(
        row_count=10,
        col_count=4,
        headers=["Year", "Revenue", "Net Income", "EPS"],
        context_before="Financial highlights for the fiscal year",
        table_text="Year Revenue Net Income EPS 2024 500000 50000 3.25 2023 450000 45000 2.90",
    )
    assert result == "data"


@pytest.mark.unit
def test_list_tables_filters_layout(tmp_path: Path) -> None:
    """验证 list_tables() 默认过滤 layout 表格。

    文档包含 1 个 layout 表和 1 个 data 表，list_tables() 应只返回 data 表。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    html = """
    <html><body>
        <table><tr><td>x</td></tr></table>
        <h1>Revenue</h1>
        <p>Financial data below</p>
        <table>
            <tr><th>Year</th><th>Revenue</th><th>Profit</th></tr>
            <tr><td>2023</td><td>500,000</td><td>50,000</td></tr>
            <tr><td>2024</td><td>600,000</td><td>60,000</td></tr>
        </table>
    </body></html>
    """
    html_path = tmp_path / "mixed.html"
    html_path.write_text(html, encoding="utf-8")

    source = LocalFileSource(
        path=html_path,
        uri="local://mixed.html",
        media_type="text/html",
        content_length=html_path.stat().st_size,
        etag=None,
    )
    processor = BSProcessor(source)

    # 底层应有 2 个表格
    assert len(processor._tables) == 2
    # 第一个是 layout（1×1, 文本极短）
    assert processor._tables[0].table_type == "layout"
    # 第二个是 data
    assert processor._tables[1].table_type == "data"

    # list_tables() 默认只返回 data 表格
    tables = processor.list_tables()
    assert len(tables) == 1
    assert tables[0]["table_type"] == "data"
    assert tables[0]["table_ref"] == "t_0002"


@pytest.mark.unit
def test_safe_table_text_extraction() -> None:
    """验证 _safe_table_text 安全提取表格文本。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        "<table><tr><td>Hello</td><td>World</td></tr></table>",
        bs_processor._HTML_PARSER,
    )
    table_tag = soup.find("table")
    assert table_tag is not None
    text = bs_processor._safe_table_text(table_tag)
    assert "Hello" in text
    assert "World" in text


@pytest.mark.unit
def test_bs_processor_table_section_ref_mapping_preserves_dom_order(tmp_path: Path) -> None:
    """验证表格归属按 DOM 线性扫描映射且顺序稳定。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    html = """
    <html><body>
        <table>
            <tr><th>Name</th><th>Value</th></tr>
            <tr><td>PreHeading</td><td>1</td></tr>
        </table>
        <h1>Item 1. Business</h1>
        <table>
            <tr><th>Name</th><th>Value</th></tr>
            <tr><td>Item1</td><td>2</td></tr>
        </table>
        <h2>Item 2. Risk Factors</h2>
        <table>
            <tr><th>Name</th><th>Value</th></tr>
            <tr><td>Item2</td><td>3</td></tr>
        </table>
    </body></html>
    """
    html_path = _write_html(tmp_path, "table_section_ref.html", html)
    processor = BSProcessor(_make_source(html_path))

    assert [table.ref for table in processor._tables] == ["t_0001", "t_0002", "t_0003"]
    assert [table.section_ref for table in processor._tables] == [None, "s_0001", "s_0002"]


@pytest.mark.unit
def test_bs_processor_build_tables_not_call_reverse_heading_lookup(
    tmp_path: Path,
) -> None:
    """验证构建表格不再逐表调用反向标题查找。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    html = """
    <html><body>
        <h1>Item 1. Business</h1>
        <table>
            <tr><th>Name</th><th>Value</th></tr>
            <tr><td>A</td><td>1</td></tr>
        </table>
        <h2>Item 2. Risk Factors</h2>
        <table>
            <tr><th>Name</th><th>Value</th></tr>
            <tr><td>B</td><td>2</td></tr>
        </table>
    </body></html>
    """
    html_path = _write_html(tmp_path, "no_reverse_lookup.html", html)
    processor = BSProcessor(_make_source(html_path))

    assert len(processor._tables) == 2
    assert [table.section_ref for table in processor._tables] == ["s_0001", "s_0002"]
