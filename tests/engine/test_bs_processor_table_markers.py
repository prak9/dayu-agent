"""BSProcessor.get_full_text_with_table_markers() 单元测试。

验证带表格占位符的全文提取功能，确保占位符编号与 list_tables()
保持一致、DOM 恢复安全、以及各种边界场景的正确行为。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alpha.fins.storage.local_file_source import LocalFileSource
from alpha.engine.processors.bs_processor import BSProcessor


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _write_html(tmp_path: Path, name: str, html: str) -> Path:
    """写入 HTML 测试文件。

    Args:
        tmp_path: pytest 临时目录。
        name: 文件名。
        html: HTML 内容。

    Returns:
        文件路径。
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
    """

    return LocalFileSource(
        path=path,
        uri=f"local://{path.name}",
        media_type="text/html",
    )


# ---------------------------------------------------------------------------
# 测试用合成 HTML
# ---------------------------------------------------------------------------

MULTI_TABLE_HTML = """
<html><body>
    <h1>Annual Report</h1>
    <p>Introduction paragraph.</p>
    <table>
        <caption>Balance Sheet</caption>
        <tr><th>Item</th><th>2024</th></tr>
        <tr><td>Cash</td><td>100</td></tr>
    </table>
    <h2>Risk Factors</h2>
    <p>Risk description text.</p>
    <table>
        <tr><th>Risk Type</th><th>Level</th></tr>
        <tr><td>Market</td><td>High</td></tr>
    </table>
    <h2>Financial Statements</h2>
    <table>
        <caption>Income Statement</caption>
        <tr><th>Revenue</th><th>2024</th></tr>
        <tr><td>Total</td><td>500</td></tr>
    </table>
</body></html>
"""


# ---------------------------------------------------------------------------
# 测试类：get_full_text_with_table_markers
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetFullTextWithTableMarkers:
    """BSProcessor.get_full_text_with_table_markers() 单元测试。"""

    def test_markers_present_in_output(self, tmp_path: Path) -> None:
        """验证输出包含所有 [[t_XXXX]] 占位符。"""

        path = _write_html(tmp_path, "multi.html", MULTI_TABLE_HTML)
        processor = BSProcessor(_make_source(path))

        marked = processor.get_full_text_with_table_markers()

        assert "[[t_0001]]" in marked
        assert "[[t_0002]]" in marked
        assert "[[t_0003]]" in marked

    def test_marker_count_matches_list_tables(self, tmp_path: Path) -> None:
        """验证占位符数量与 list_tables() 返回的表格数一致。"""

        path = _write_html(tmp_path, "multi.html", MULTI_TABLE_HTML)
        processor = BSProcessor(_make_source(path))

        tables = processor.list_tables()
        marked = processor.get_full_text_with_table_markers()

        # 统计 [[t_XXXX]] 出现次数
        import re
        marker_count = len(re.findall(r"\[\[t_\d{4}\]\]", marked))
        assert marker_count == len(tables)

    def test_table_content_replaced_by_markers(self, tmp_path: Path) -> None:
        """验证表格内文本被占位符替代，不出现在输出中。"""

        path = _write_html(tmp_path, "multi.html", MULTI_TABLE_HTML)
        processor = BSProcessor(_make_source(path))

        marked = processor.get_full_text_with_table_markers()

        # 表格内文本不应出现
        assert "Cash" not in marked
        assert "100" not in marked
        assert "Revenue" not in marked

    def test_non_table_text_preserved(self, tmp_path: Path) -> None:
        """验证非表格文本（标题、段落）在输出中保留。"""

        path = _write_html(tmp_path, "multi.html", MULTI_TABLE_HTML)
        processor = BSProcessor(_make_source(path))

        marked = processor.get_full_text_with_table_markers()

        assert "Annual Report" in marked
        assert "Introduction paragraph" in marked
        assert "Risk Factors" in marked
        assert "Risk description text" in marked
        assert "Financial Statements" in marked

    def test_dom_restored_after_call(self, tmp_path: Path) -> None:
        """验证调用后 DOM 恢复，get_full_text() 行为不受影响。"""

        path = _write_html(tmp_path, "multi.html", MULTI_TABLE_HTML)
        processor = BSProcessor(_make_source(path))

        # 先调用带标记版本
        processor.get_full_text_with_table_markers()

        # 再调用普通版本，应包含表格内文本
        full_text = processor.get_full_text()
        assert "Cash" in full_text
        assert "100" in full_text
        assert "Revenue" in full_text
        # 不应有占位符
        assert "[[t_" not in full_text

    def test_dom_restored_after_multiple_calls(self, tmp_path: Path) -> None:
        """验证多次调用后 DOM 仍然完整。"""

        path = _write_html(tmp_path, "multi.html", MULTI_TABLE_HTML)
        processor = BSProcessor(_make_source(path))

        # 多次调用
        result1 = processor.get_full_text_with_table_markers()
        result2 = processor.get_full_text_with_table_markers()

        # 结果应一致
        assert result1 == result2

        # DOM 仍然完整
        full_text = processor.get_full_text()
        assert "Cash" in full_text
        assert "[[tbl_" not in full_text

    def test_marker_order_matches_dom_order(self, tmp_path: Path) -> None:
        """验证占位符顺序与 DOM 中 table 出现顺序一致。"""

        path = _write_html(tmp_path, "multi.html", MULTI_TABLE_HTML)
        processor = BSProcessor(_make_source(path))

        marked = processor.get_full_text_with_table_markers()

        # t_0001 应出现在 t_0002 之前，t_0002 在 t_0003 之前
        pos1 = marked.index("[[t_0001]]")
        pos2 = marked.index("[[t_0002]]")
        pos3 = marked.index("[[t_0003]]")
        assert pos1 < pos2 < pos3

    def test_no_tables_returns_plain_text(self, tmp_path: Path) -> None:
        """验证无表格文档返回纯文本（无占位符）。"""

        html = "<html><body><h1>Title</h1><p>Content only.</p></body></html>"
        path = _write_html(tmp_path, "no_table.html", html)
        processor = BSProcessor(_make_source(path))

        marked = processor.get_full_text_with_table_markers()

        assert "Title" in marked
        assert "Content only" in marked
        assert "[[t_" not in marked

    def test_single_table(self, tmp_path: Path) -> None:
        """验证仅一个数据表格时的正确行为。"""

        html = """<html><body>
            <p>Before table.</p>
            <table>
                <tr><th>Header A</th><th>Header B</th></tr>
                <tr><td>Data 1</td><td>Data 2</td></tr>
            </table>
            <p>After table.</p>
        </body></html>"""
        path = _write_html(tmp_path, "single.html", html)
        processor = BSProcessor(_make_source(path))

        marked = processor.get_full_text_with_table_markers()

        assert "[[t_0001]]" in marked
        assert "[[t_0002]]" not in marked
        assert "Before table" in marked
        assert "After table" in marked
        # 表格内容应被替换
        assert "Data 1" not in marked

    def test_markers_between_headings(self, tmp_path: Path) -> None:
        """验证占位符出现在对应标题的文本段内。"""

        path = _write_html(tmp_path, "multi.html", MULTI_TABLE_HTML)
        processor = BSProcessor(_make_source(path))

        marked = processor.get_full_text_with_table_markers()

        # t_0001 应在 "Annual Report" 和 "Risk Factors" 之间
        pos_h1 = marked.index("Annual Report")
        pos_h2 = marked.index("Risk Factors")
        pos_tbl1 = marked.index("[[t_0001]]")
        assert pos_h1 < pos_tbl1 < pos_h2

        # t_0002 应在 "Risk Factors" 和 "Financial Statements" 之间
        pos_h3 = marked.index("Financial Statements")
        pos_tbl2 = marked.index("[[t_0002]]")
        assert pos_h2 < pos_tbl2 < pos_h3

    def test_layout_tables_excluded_from_markers(self, tmp_path: Path) -> None:
        """验证 layout 表格不产生占位符标记。

        layout 表格（单行单列、无数据表头）应直接被移除，
        不注入 [[t_XXXX]] 标记——与 list_tables() 过滤策略一致。
        """

        # 构造含 layout 表格的 HTML
        # 第一个表格是 layout（单行单列，无 th），第二个是数据表
        html = """<html><body>
            <p>Before layout.</p>
            <table><tr><td>Just a wrapper</td></tr></table>
            <p>Between tables.</p>
            <table>
                <tr><th>Col A</th><th>Col B</th></tr>
                <tr><td>Data 1</td><td>Data 2</td></tr>
            </table>
            <p>After data table.</p>
        </body></html>"""
        path = _write_html(tmp_path, "layout.html", html)
        processor = BSProcessor(_make_source(path))

        marked = processor.get_full_text_with_table_markers()

        # list_tables 应只返回数据表
        tables = processor.list_tables()
        table_refs_in_list = {t["table_ref"] for t in tables}

        # marked text 中的 tbl 标记应与 list_tables 一致
        import re
        marker_refs = set(re.findall(r"t_\d{4}", marked))
        assert marker_refs == table_refs_in_list, (
            f"标记 {marker_refs} 与 list_tables {table_refs_in_list} 不一致"
        )
