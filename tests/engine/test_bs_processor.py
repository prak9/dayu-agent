"""BSProcessor 单元与集成测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from alpha.fins.storage.local_file_source import LocalFileSource
from alpha.engine.processors import bs_processor
from alpha.engine.processors.bs_processor import BSProcessor
from alpha.engine.processors.base import SearchHit


SYNTHETIC_HTML = """
<html>
  <body>
    <h1>Section A</h1>
    <p>Intro text before table.</p>
    <table>
      <caption>Balance Sheet</caption>
      <tr><th>Item</th><th>2024</th></tr>
      <tr><td>Cash</td><td>100</td></tr>
    </table>
    <h2>Section B</h2>
    <p>Another text with keyword for search; keyword appears again and keyword appears third time.</p>
    <table>
      <tr><th>Value</th><th>Value</th></tr>
      <tr><td colspan="2">Merged</td></tr>
    </table>
  </body>
</html>
"""


def _write_html(tmp_path: Path, name: str, html: str) -> Path:
    """写入 HTML 测试文件。

    Args:
        tmp_path: pytest 临时目录。
        name: 文件名。
        html: HTML 内容。

    Returns:
        文件路径。

    Raises:
        OSError: 写入失败时抛出。
    """

    file_path = tmp_path / name
    file_path.write_text(html, encoding="utf-8")
    return file_path


def _make_source(path: Path) -> LocalFileSource:
    """构建本地 Source。

    Args:
        path: 本地路径。

    Returns:
        LocalFileSource 实例。

    Raises:
        OSError: 路径非法时抛出。
    """

    return LocalFileSource(
        path=path,
        uri=f"local://{path.name}",
        media_type="text/html",
        content_length=path.stat().st_size,
        etag=None,
    )


def _hit_section_ref(hit: SearchHit) -> str | None:
    """安全读取搜索命中的可选 section_ref。"""

    return hit.get("section_ref")


def _hit_snippet(hit: SearchHit) -> str | None:
    """安全读取搜索命中的可选 snippet。"""

    return hit.get("snippet")


@pytest.mark.unit
def test_normalize_cell_value_preserves_bs_empty_string_semantics() -> None:
    """验证 BS processor 的空白字符串会保留为空串。"""

    assert bs_processor._normalize_cell_value(None) is None
    assert bs_processor._normalize_cell_value(float("nan")) is None
    assert bs_processor._normalize_cell_value("  text  ") == "text"
    assert bs_processor._normalize_cell_value("   ") == ""
    assert bs_processor._normalize_cell_value(3) == 3


@pytest.mark.unit
def test_bs_processor_sections_and_read_section(tmp_path: Path) -> None:
    """验证章节解析与 read_section 输出。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    html_path = _write_html(tmp_path, "sample.html", SYNTHETIC_HTML)
    processor = BSProcessor(_make_source(html_path))

    sections = processor.list_sections()
    assert len(sections) == 2
    assert sections[0]["ref"] == "s_0001"
    assert sections[1]["parent_ref"] == "s_0001"

    section_content = processor.read_section("s_0001")
    assert "[[t_0001]]" in section_content["content"]
    assert section_content["tables"] == ["t_0001"]
    assert section_content["word_count"] > 0
    assert section_content["contains_full_text"] is False


@pytest.mark.unit
def test_bs_processor_tables_and_read_table_format(tmp_path: Path) -> None:
    """验证表格摘要与 read_table 输出格式。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    html_path = _write_html(tmp_path, "tables.html", SYNTHETIC_HTML)
    processor = BSProcessor(_make_source(html_path))

    tables = processor.list_tables()
    assert len(tables) == 2
    assert tables[0]["table_ref"] == "t_0001"
    assert "Cash" in (tables[0]["headers"] or [])
    assert tables[0]["table_type"] == "data"

    table_1 = processor.read_table("t_0001")
    assert table_1["data_format"] == "records"
    assert table_1["columns"] is not None

    table_2 = processor.read_table("t_0002")
    assert table_2["data_format"] == "markdown"
    assert isinstance(table_2["data"], str)


@pytest.mark.unit
def test_bs_processor_search_within_ref(tmp_path: Path) -> None:
    """验证搜索与章节范围过滤。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    html_path = _write_html(tmp_path, "search.html", SYNTHETIC_HTML)
    processor = BSProcessor(_make_source(html_path))

    hits = processor.search("intro")
    assert hits
    assert _hit_section_ref(hits[0]) == "s_0001"

    scoped_hits = processor.search("keyword", within_ref="s_0002")
    assert scoped_hits
    assert all(_hit_section_ref(hit) == "s_0002" for hit in scoped_hits)
    assert len(scoped_hits) <= 2
    assert all("keyword" in str(_hit_snippet(hit)).lower() for hit in scoped_hits)
    assert all(len(str(_hit_snippet(hit))) <= 360 for hit in scoped_hits)


@pytest.mark.unit
def test_bs_processor_no_headings_full_text(tmp_path: Path) -> None:
    """验证无标题文档的 dummy section 行为。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    html = "<html><body><p>Only body text.</p><table><tr><td>1</td></tr></table></body></html>"
    html_path = _write_html(tmp_path, "no_headings.html", html)
    processor = BSProcessor(_make_source(html_path))

    sections = processor.list_sections()
    assert len(sections) == 1
    assert sections[0]["ref"] == "s_0001"

    section_content = processor.read_section("s_0001")
    assert section_content["contains_full_text"] is True
    assert "[[t_0001]]" in section_content["content"]


@pytest.mark.unit
def test_bs_processor_get_full_text_preserves_table_content(tmp_path: Path) -> None:
    """验证 get_full_text() 包含表格内文本而非占位符。

    read_section() 会将表格替换为 ``[[t_xxxx]]`` 占位符，
    而 get_full_text() 应保留表格内所有文本内容。
    这对于在 table-based layout HTML（如 AMZN）中检测
    虚拟章节 marker 至关重要。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    html = """<html><body>
        <p>Body text before table.</p>
        <table><tr><td>Item 1. Business Overview</td></tr></table>
        <table><tr><td>Item 7. MD and A</td></tr></table>
        <p>Body text after tables.</p>
    </body></html>"""
    html_path = _write_html(tmp_path, "table_layout.html", html)
    processor = BSProcessor(_make_source(html_path))

    # read_section 的文本包含占位符，不含表格内原始文本
    section_content = processor.read_section("s_0001")
    assert "[[t_" in section_content["content"]
    assert "Item 1" not in section_content["content"]

    # get_full_text 保留表格内文本
    full_text = processor.get_full_text()
    assert "Item 1" in full_text
    assert "Item 7" in full_text
    assert "Body text before table" in full_text
    assert "Body text after tables" in full_text
    # 不应包含占位符
    assert "[[t_" not in full_text


@pytest.mark.unit
def test_bs_processor_get_full_text_with_headings(tmp_path: Path) -> None:
    """验证 get_full_text() 在有标题文档上也正确工作。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    html_path = _write_html(tmp_path, "with_headings.html", SYNTHETIC_HTML)
    processor = BSProcessor(_make_source(html_path))

    full_text = processor.get_full_text()
    # 包含所有标题和段落文本
    assert "Section A" in full_text
    assert "Section B" in full_text
    assert "Intro text" in full_text
    # 包含表格内文本
    assert "Cash" in full_text
    assert "100" in full_text
    # 不应包含占位符
    assert "[[tbl_" not in full_text


@pytest.mark.unit
def test_bs_processor_hidden_content_filtered(tmp_path: Path) -> None:
    """验证隐藏内容不会进入 preview。

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
        <div style="display:none"><ix:header><ix:hidden>HIDDEN_TOKEN</ix:hidden></ix:header></div>
        <p>Visible intro text.</p>
        <table><tr><td>1</td></tr></table>
      </body>
    </html>
    """
    html_path = _write_html(tmp_path, "hidden.html", html)
    processor = BSProcessor(_make_source(html_path))

    sections = processor.list_sections()
    assert len(sections) == 1
    preview = sections[0]["preview"]
    assert "HIDDEN_TOKEN" not in preview
    assert "Visible" in preview


@pytest.mark.unit
def test_bs_processor_context_before_without_headings(tmp_path: Path) -> None:
    """验证无标题文档的表格上下文提取。

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
        <p>Intro before table.</p>
        <div><table>
          <tr><th>Year</th><th>Revenue</th><th>Profit</th></tr>
          <tr><td>2023</td><td>100</td><td>20</td></tr>
          <tr><td>2024</td><td>120</td><td>25</td></tr>
        </table></div>
      </body>
    </html>
    """
    html_path = _write_html(tmp_path, "context.html", html)
    processor = BSProcessor(_make_source(html_path))

    tables = processor.list_tables()
    assert tables
    assert "Intro before table" in (tables[0]["context_before"] or "")


@pytest.mark.unit
def test_bs_processor_header_helpers() -> None:
    """验证表头辅助函数的默认/非默认逻辑。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    assert bs_processor._looks_like_default_headers(["0", "1", "2"]) is True
    assert bs_processor._looks_like_default_headers(["1", "2"]) is True
    assert bs_processor._looks_like_default_headers(["Year", "Value"]) is False
    assert bs_processor._looks_like_default_headers(["①", "②", "③"]) is False

    matrix = [
        ["", ""],
        ["Year", "Value"],
        ["2024", "10"],
    ]
    headers = bs_processor._select_matrix_headers(matrix)
    assert headers == ["Year", "Value"]

    soup = bs_processor.BeautifulSoup(
        "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>",
        bs_processor._HTML_PARSER,
    )
    table_tag = soup.find("table")
    assert table_tag is not None
    th_headers = bs_processor._extract_headers_from_th(table_tag)
    assert th_headers == ["A", "B"]

    deduped = bs_processor._deduplicate_headers(["Products", "Services", "Products", "services"])
    assert deduped == ["Products", "Services"]


@pytest.mark.unit
def test_bs_processor_read_section_uses_render_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 read_section 对同一章节二次读取命中缓存。

    Args:
        tmp_path: pytest 临时目录。
        monkeypatch: pytest monkeypatch。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    html_path = _write_html(tmp_path, "cache_section.html", SYNTHETIC_HTML)
    processor = BSProcessor(_make_source(html_path))

    original_render = bs_processor._render_section_text
    tracked_render = Mock(side_effect=original_render)
    monkeypatch.setattr(bs_processor, "_render_section_text", tracked_render)
    first = processor.read_section("s_0001")
    second = processor.read_section("s_0001")

    assert first["content"] == second["content"]
    assert tracked_render.call_count == 1


@pytest.mark.unit
def test_bs_processor_read_table_uses_render_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 read_table 对同一表格二次读取命中缓存。

    Args:
        tmp_path: pytest 临时目录。
        monkeypatch: pytest monkeypatch。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    html_path = _write_html(tmp_path, "cache_table.html", SYNTHETIC_HTML)
    processor = BSProcessor(_make_source(html_path))

    original_render = bs_processor._render_table_data
    tracked_render = Mock(side_effect=original_render)
    monkeypatch.setattr(bs_processor, "_render_table_data", tracked_render)
    first = processor.read_table("t_0001")
    second = processor.read_table("t_0001")

    assert first["data_format"] == second["data_format"]
    assert tracked_render.call_count == 1
