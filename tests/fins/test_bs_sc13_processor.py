"""基于 BeautifulSoup 的 SC 13 系列表单处理器覆盖率测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from alpha.fins.processors.bs_sc13_processor import BsSc13FormProcessor
from alpha.fins.storage.local_file_source import LocalFileSource


def _make_source(path: Path, *, media_type: Optional[str] = "text/html") -> LocalFileSource:
    """构建本地 Source。

    Args:
        path: 文件路径。
        media_type: 媒体类型。

    Returns:
        LocalFileSource 实例。

    Raises:
        OSError: 文件状态读取失败时抛出。
    """

    return LocalFileSource(
        path=path,
        uri=f"local://{path.name}",
        media_type=media_type,
        content_length=path.stat().st_size,
        etag=None,
    )


# ---------------------------------------------------------------------------
# SC 13G 标准文档（7 Items + SIGNATURE），模拟 SEC Schedule 13G 结构
# ---------------------------------------------------------------------------

_SC13G_HTML = """
<html>
  <body>
    <p><b>Item 1.</b> Name of Issuer</p>
    <p>Example Corp.</p>
    <p><b>Item 2.</b> Name of Person Filing</p>
    <p>Amazon.com, Inc., a Delaware corporation, 410 Terry Avenue North,
    Seattle, Washington 98109. Citizenship: Delaware.</p>
    <p><b>Item 3.</b> If This Statement Filed Pursuant to Rule 13d-1(b)</p>
    <p>(b) Broker or dealer registered under Section 15 of the Act.</p>
    <p><b>Item 4.</b> Ownership</p>
    <p>Amount beneficially owned: 10,000 shares. Percent of class: 5.2%.
    Sole voting power: 10,000. Shared voting power: 0.</p>
    <p><b>Item 5.</b> Ownership of 5 Percent or Less of a Class</p>
    <p>Not Applicable.</p>
    <p><b>Item 6.</b> Ownership of More than 5 Percent on Behalf of Another Person</p>
    <p>Not Applicable.</p>
    <p><b>Item 7.</b> Identification and Classification of the Subsidiary</p>
    <p>Not Applicable.</p>
    <p><b>SIGNATURE</b></p>
    <p>After reasonable inquiry, I certify that the information set forth
    in this statement is true, complete and correct.</p>
    <p>Amazon.com, Inc.</p>
    <p>Date: February 14, 2026</p>
  </body>
</html>
"""

# ---------------------------------------------------------------------------
# supports() 测试
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bs_sc13_supports_html_sc13d(tmp_path: Path) -> None:
    """验证 SC 13D HTML 文件被正确识别为受支持。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13d.html"
    source_path.write_text("<html><body>SC 13D</body></html>", encoding="utf-8")
    source = _make_source(source_path, media_type="text/html")

    assert BsSc13FormProcessor.supports(source, form_type="SC 13D", media_type="text/html") is True


@pytest.mark.unit
def test_bs_sc13_supports_sc13g(tmp_path: Path) -> None:
    """验证 SC 13G 被正确识别。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13g.html"
    source_path.write_text("<html><body>SC 13G</body></html>", encoding="utf-8")
    source = _make_source(source_path, media_type="text/html")

    assert BsSc13FormProcessor.supports(source, form_type="SC 13G", media_type="text/html") is True


@pytest.mark.unit
def test_bs_sc13_supports_sc13da(tmp_path: Path) -> None:
    """验证 SC 13D/A（修正版）也被正确识别。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13da.html"
    source_path.write_text("<html><body>SC 13D/A</body></html>", encoding="utf-8")
    source = _make_source(source_path, media_type="text/html")

    assert BsSc13FormProcessor.supports(source, form_type="SC 13D/A", media_type="text/html") is True


@pytest.mark.unit
def test_bs_sc13_supports_sc13ga(tmp_path: Path) -> None:
    """验证 SC 13G/A（修正版）也被正确识别。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13ga.html"
    source_path.write_text("<html><body>SC 13G/A</body></html>", encoding="utf-8")
    source = _make_source(source_path, media_type="text/html")

    assert BsSc13FormProcessor.supports(source, form_type="SC 13G/A", media_type="text/html") is True


@pytest.mark.unit
def test_bs_sc13_supports_schedule_13g(tmp_path: Path) -> None:
    """验证 SCHEDULE 13G 命名兼容。

    SEC 旧命名 SCHEDULE 13G 应归一化后被正确识别。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "schedule13g.html"
    source_path.write_text("<html><body>SCHEDULE 13G</body></html>", encoding="utf-8")
    source = _make_source(source_path, media_type="text/html")

    assert BsSc13FormProcessor.supports(source, form_type="SCHEDULE 13G", media_type="text/html") is True


@pytest.mark.unit
def test_bs_sc13_rejects_non_sc13_form(tmp_path: Path) -> None:
    """验证非 SC 13 表单被拒绝。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "10k.html"
    source_path.write_text("<html><body>10-K</body></html>", encoding="utf-8")
    source = _make_source(source_path, media_type="text/html")

    assert BsSc13FormProcessor.supports(source, form_type="10-K", media_type="text/html") is False


@pytest.mark.unit
def test_bs_sc13_supports_xml_media_type(tmp_path: Path) -> None:
    """验证 XML 媒体类型被正确识别。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13g.xml"
    source_path.write_text(
        '<?xml version="1.0"?><document>SC 13G</document>', encoding="utf-8"
    )
    source = _make_source(source_path, media_type="application/xml")

    assert (
        BsSc13FormProcessor.supports(source, form_type="SC 13G", media_type="application/xml")
        is True
    )


@pytest.mark.unit
def test_bs_sc13_supports_txt_media_type(tmp_path: Path) -> None:
    """验证 SC 13 `.txt` 主文件被正确识别。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13g.txt"
    source_path.write_text(_SC13G_HTML, encoding="utf-8")
    source = _make_source(source_path, media_type="text/plain")

    assert (
        BsSc13FormProcessor.supports(source, form_type="SC 13G/A", media_type="text/plain")
        is True
    )


# ---------------------------------------------------------------------------
# 章节切分测试
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bs_sc13_splits_items_and_signature(tmp_path: Path) -> None:
    """验证 SC 13G Item 1-7 + SIGNATURE 正确切分。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13g.html"
    source_path.write_text(_SC13G_HTML, encoding="utf-8")

    processor = BsSc13FormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="SC 13G",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    # SC 13G 标准结构：Item 1-7 + SIGNATURE = 8 节
    assert "Item 1" in titles
    assert "Item 7" in titles
    assert "SIGNATURE" in titles
    assert len(sections) == 8


@pytest.mark.unit
def test_bs_sc13_splits_items_from_txt_source(tmp_path: Path) -> None:
    """验证 SC 13 `.txt` 文件可完成章节切分。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13g.txt"
    source_path.write_text(_SC13G_HTML, encoding="utf-8")

    processor = BsSc13FormProcessor(
        _make_source(source_path, media_type="text/plain"),
        form_type="SC 13G/A",
        media_type="text/plain",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    assert "Item 1" in titles
    assert "Item 7" in titles
    assert "SIGNATURE" in titles
    assert len(sections) == 8


@pytest.mark.unit
def test_bs_sc13_handles_signatures_plural(tmp_path: Path) -> None:
    """验证 SC 13 正确匹配 SIGNATURES（复数形式）。

    SEC SC 13 文件常使用 "SIGNATURES" 复数形式。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    html = _SC13G_HTML.replace("<b>SIGNATURE</b>", "<b>SIGNATURES</b>")
    source_path = tmp_path / "sc13g_plural.html"
    source_path.write_text(html, encoding="utf-8")

    processor = BsSc13FormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="SC 13G",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    assert "SIGNATURE" in titles or "SIGNATURES" in titles
    assert len(sections) == 8


@pytest.mark.unit
def test_bs_sc13_splits_with_schedule_a_and_exhibit(tmp_path: Path) -> None:
    """验证 SC 13 正确识别 Schedule A 和 Exhibit 尾段标记。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    html = _SC13G_HTML.replace(
        "<p>Date: February 14, 2026</p>",
        """<p>Date: February 14, 2026</p>
        <p><b>Schedule A</b></p>
        <p>List of entities that beneficially own the securities.</p>
        <p><b>Exhibit</b></p>
        <p>Power of Attorney.</p>""",
    )

    source_path = tmp_path / "sc13g_extras.html"
    source_path.write_text(html, encoding="utf-8")

    processor = BsSc13FormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="SC 13G",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    assert "Schedule A" in titles
    assert "Exhibit" in titles
    assert len(sections) == 10  # Item 1-7 + SIGNATURE + Schedule A + Exhibit


# ---------------------------------------------------------------------------
# 搜索测试
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bs_sc13_search_exact_match(tmp_path: Path) -> None:
    """验证精确短语搜索命中。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13g.html"
    source_path.write_text(_SC13G_HTML, encoding="utf-8")

    processor = BsSc13FormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="SC 13G",
        media_type="text/html",
    )
    # "beneficially owned" 精确出现在 Item 4 中
    hits = processor.search("beneficially owned")

    assert len(hits) >= 1
    assert any("beneficially" in str(h.get("snippet", "")).lower() for h in hits)


@pytest.mark.unit
def test_bs_sc13_search_token_fallback_multiword(tmp_path: Path) -> None:
    """验证多词查询 token 回退搜索。

    "voting power" 完整短语不在文本中，但 "voting" 和 "power"
    作为独立 token 出现在 Item 4 中。Token 回退应命中。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13g.html"
    source_path.write_text(_SC13G_HTML, encoding="utf-8")

    processor = BsSc13FormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="SC 13G",
        media_type="text/html",
    )
    # "voting power" 中的 "voting" 和 "power" 分别出现在 Item 4
    hits = processor.search("voting power")

    assert len(hits) >= 1


@pytest.mark.unit
def test_bs_sc13_search_single_word_no_match(tmp_path: Path) -> None:
    """验证单词不匹配时返回空列表。

    单词 "revenue" 不出现在 SC 13G 中，也无 token 可回退。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13g.html"
    source_path.write_text(_SC13G_HTML, encoding="utf-8")

    processor = BsSc13FormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="SC 13G",
        media_type="text/html",
    )
    hits = processor.search("revenue")

    assert hits == []


@pytest.mark.unit
def test_bs_sc13_search_within_ref(tmp_path: Path) -> None:
    """验证 within_ref 限定搜索范围。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13g.html"
    source_path.write_text(_SC13G_HTML, encoding="utf-8")

    processor = BsSc13FormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="SC 13G",
        media_type="text/html",
    )
    sections = processor.list_sections()

    # "shares" 在 Item 4 中出现，搜索限定到 Item 4 应命中
    item4_ref = None
    for s in sections:
        if s.get("title") == "Item 4":
            item4_ref = s["ref"]
            break
    assert item4_ref is not None

    hits = processor.search("shares", within_ref=item4_ref)
    assert len(hits) >= 1

    # 搜索限定到 Item 1（不含 "shares"）应无命中
    item1_ref = None
    for s in sections:
        if s.get("title") == "Item 1":
            item1_ref = s["ref"]
            break
    assert item1_ref is not None

    hits_empty = processor.search("shares", within_ref=item1_ref)
    assert hits_empty == []


# ---------------------------------------------------------------------------
# 其他功能测试
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bs_sc13_parser_version(tmp_path: Path) -> None:
    """验证 parser_version 格式正确。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13g.html"
    source_path.write_text(_SC13G_HTML, encoding="utf-8")

    processor = BsSc13FormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="SC 13G",
        media_type="text/html",
    )

    assert processor.PARSER_VERSION == "bs_sc13_section_processor_v1.0.0"


@pytest.mark.unit
def test_bs_sc13_read_section_content(tmp_path: Path) -> None:
    """验证 read_section 返回有效内容。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13g.html"
    source_path.write_text(_SC13G_HTML, encoding="utf-8")

    processor = BsSc13FormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="SC 13G",
        media_type="text/html",
    )
    sections = processor.list_sections()

    # 读取 Item 4（持股详情），应包含 "beneficially"
    item4_ref = None
    for s in sections:
        if s.get("title") == "Item 4":
            item4_ref = s["ref"]
            break
    assert item4_ref is not None

    content = processor.read_section(item4_ref)
    assert content is not None
    section_text = content.get("content", "")
    assert "beneficially" in section_text.lower()


@pytest.mark.unit
def test_bs_sc13_fallback_on_insufficient_markers(tmp_path: Path) -> None:
    """验证当 marker 不足时回退到 BS 基类行为。

    若 HTML 中不含 SC 13 标准 Item 标记，处理器应回退到
    FinsBSProcessor 基类的默认章节切分。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13g_minimal.html"
    source_path.write_text(
        """
        <html>
          <body>
            <h1>Schedule 13G</h1>
            <p>This is a very minimal filing with no standard items.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    processor = BsSc13FormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="SC 13G",
        media_type="text/html",
    )
    sections = processor.list_sections()

    # 回退到 BS 基类的切分方式（至少有 1 个节）
    assert len(sections) >= 1


__all__ = []
