"""基于 BeautifulSoup 的 8-K 表单处理器覆盖率测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from alpha.fins.processors.bs_eight_k_processor import BsEightKFormProcessor
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
# supports() 测试
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bs_eight_k_supports_html_8k(tmp_path: Path) -> None:
    """验证 8-K HTML 文件被正确识别为受支持。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k.html"
    source_path.write_text("<html><body>8-K</body></html>", encoding="utf-8")
    source = _make_source(source_path, media_type="text/html")

    assert BsEightKFormProcessor.supports(source, form_type="8-K", media_type="text/html") is True


@pytest.mark.unit
def test_bs_eight_k_supports_8ka(tmp_path: Path) -> None:
    """验证 8-K/A（修正版）也被正确识别。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8ka.html"
    source_path.write_text("<html><body>8-K/A</body></html>", encoding="utf-8")
    source = _make_source(source_path, media_type="text/html")

    assert BsEightKFormProcessor.supports(source, form_type="8-K/A", media_type="text/html") is True


@pytest.mark.unit
def test_bs_eight_k_rejects_non_8k_form(tmp_path: Path) -> None:
    """验证非 8-K 表单被拒绝。

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

    assert BsEightKFormProcessor.supports(source, form_type="10-K", media_type="text/html") is False


@pytest.mark.unit
def test_bs_eight_k_supports_xml_media_type(tmp_path: Path) -> None:
    """验证 XML 媒体类型被正确识别。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k.xml"
    source_path.write_text(
        '<?xml version="1.0"?><document>8-K</document>', encoding="utf-8"
    )
    source = _make_source(source_path, media_type="application/xml")

    assert (
        BsEightKFormProcessor.supports(source, form_type="8-K", media_type="application/xml")
        is True
    )


@pytest.mark.unit
def test_bs_eight_k_supports_xml_uri_suffix(tmp_path: Path) -> None:
    """验证通过 URI 后缀识别 XML 文件。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k.xml"
    source_path.write_text(
        '<?xml version="1.0"?><document>8-K</document>', encoding="utf-8"
    )
    source = LocalFileSource(
        path=source_path,
        uri="local://filing.xml",
        media_type=None,
        content_length=source_path.stat().st_size,
        etag=None,
    )

    assert BsEightKFormProcessor.supports(source, form_type="8-K") is True


# ---------------------------------------------------------------------------
# 章节切分测试
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bs_eight_k_splits_items_and_signature(tmp_path: Path) -> None:
    """验证 8-K Item + SIGNATURE 正确切分。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k_items.html"
    source_path.write_text(
        """
        <html>
          <body>
            <p><b>Item 2.02</b> Results of Operations and Financial Condition.</p>
            <p>On May 1, 2025, Apple Inc. issued a press release regarding
            Apple's financial results for its fiscal 2025 second quarter ended
            March 29, 2025. A copy of Apple's press release is attached hereto
            as Exhibit 99.1.</p>
            <p><b>Item 9.01</b> Financial Statements and Exhibits.</p>
            <p>(d) Exhibits</p>
            <p>Exhibit 99.1 Press Release dated May 1, 2025.</p>
            <p><b>SIGNATURE</b></p>
            <p>Pursuant to the requirements of the Securities Exchange Act of 1934,
            the registrant has duly caused this report to be signed on its behalf
            by the undersigned hereunto duly authorized.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    processor = BsEightKFormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="8-K",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    assert "Item 2.02" in titles
    assert "Item 9.01" in titles
    assert "SIGNATURE" in titles
    assert len(sections) == 3


@pytest.mark.unit
def test_bs_eight_k_handles_signatures_plural(tmp_path: Path) -> None:
    """验证 8-K 正确匹配 SIGNATURES（复数形式）。

    SEC 8-K 文件常使用 "SIGNATURES" 复数形式。
    修正后的正则应能匹配两种拼写。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k_signatures.html"
    source_path.write_text(
        """
        <html>
          <body>
            <p><b>Item 5.07</b> Submission of Matters to a Vote of Security Holders.</p>
            <p>Detailed content about the annual meeting.</p>
            <p><b>SIGNATURES</b></p>
            <p>Pursuant to the requirements of the Securities Exchange Act of 1934.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    processor = BsEightKFormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="8-K",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    assert "Item 5.07" in titles
    assert "SIGNATURE" in titles
    assert len(sections) == 2


@pytest.mark.unit
def test_bs_eight_k_deduplicates_items(tmp_path: Path) -> None:
    """验证重复 Item 编号只保留首次出现。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k_dup.html"
    source_path.write_text(
        """
        <html>
          <body>
            <p><b>Item 1.01</b> Entry into a Material Definitive Agreement.</p>
            <p>First section content.</p>
            <p><b>Item 1.01</b> (repeated reference)</p>
            <p><b>Item 2.03</b> Creation of a Direct Financial Obligation.</p>
            <p>Second section content.</p>
            <p><b>SIGNATURE</b></p>
            <p>Signed by authorized officer.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    processor = BsEightKFormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="8-K",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    # Item 1.01 应只出现一次
    assert titles.count("Item 1.01") == 1
    assert "Item 2.03" in titles
    assert "SIGNATURE" in titles


@pytest.mark.unit
def test_bs_eight_k_fallback_on_insufficient_markers(tmp_path: Path) -> None:
    """验证 marker 不足时回退到基类章节。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k_minimal.html"
    source_path.write_text(
        """
        <html>
          <body>
            <p>This is a plain SEC filing without any recognized Item markers
            or SIGNATURE section. The content is just plain text that does
            not match the 8-K Item pattern regex.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    processor = BsEightKFormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="8-K",
        media_type="text/html",
    )
    sections = processor.list_sections()

    # 回退到 BSProcessor 基类章节，至少有 1 个
    assert len(sections) >= 1


# ---------------------------------------------------------------------------
# 搜索测试：token 回退
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bs_eight_k_search_exact_match(tmp_path: Path) -> None:
    """验证精确短语匹配优先返回。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k_search.html"
    source_path.write_text(
        """
        <html>
          <body>
            <p><b>Item 2.02</b> Results of Operations and Financial Condition.</p>
            <p>Net revenue for the quarter was 12.7 billion, representing a sequential
            increase driven by strong demand in the cloud computing segment.</p>
            <p><b>Item 9.01</b> Financial Statements and Exhibits.</p>
            <p>Exhibit 99.1 Press Release.</p>
            <p><b>SIGNATURE</b></p>
            <p>Signed.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    processor = BsEightKFormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="8-K",
        media_type="text/html",
    )

    # "revenue" 精确匹配应命中
    hits = processor.search("revenue")
    assert len(hits) > 0


@pytest.mark.unit
def test_bs_eight_k_search_token_fallback_multiword(tmp_path: Path) -> None:
    """验证多词查询精确匹配失败时 token OR 回退生效。

    文档不含 "cash flow" 短语，但包含 "cash equivalents"。
    Token 回退应以 "cash" 匹配命中。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k_token_fallback.html"
    source_path.write_text(
        """
        <html>
          <body>
            <p><b>Item 2.02</b> Results of Operations and Financial Condition.</p>
            <p>Cash and cash equivalents totaled 5.2 billion at end of quarter.
            The company maintained strong liquidity with no material changes to
            the balance sheet.</p>
            <p><b>Item 9.01</b> Financial Statements and Exhibits.</p>
            <p>Exhibit 99.1 Press Release.</p>
            <p><b>SIGNATURE</b></p>
            <p>Signed.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    processor = BsEightKFormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="8-K",
        media_type="text/html",
    )

    # "cash flow" 精确匹配失败，但 "cash" token 存在
    hits = processor.search("cash flow")
    assert len(hits) > 0
    snippets = [h.get("snippet", "").lower() for h in hits]
    assert any("cash" in s for s in snippets)
    # 验证 token fallback 命中带 _token_fallback 标记
    assert all(h.get("_token_fallback") is True for h in hits)


@pytest.mark.unit
def test_bs_eight_k_search_single_word_no_fallback(tmp_path: Path) -> None:
    """验证单词查询不触发 token 回退。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k_single_search.html"
    source_path.write_text(
        """
        <html>
          <body>
            <p><b>Item 5.02</b> Departure of Directors or Certain Officers.</p>
            <p>The company announced the departure of the CFO effective immediately.</p>
            <p><b>SIGNATURE</b></p>
            <p>Signed.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    processor = BsEightKFormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="8-K",
        media_type="text/html",
    )

    # "guidance" 是单词且不存在于文档 → 返回空
    hits = processor.search("guidance")
    assert len(hits) == 0


@pytest.mark.unit
def test_bs_eight_k_search_within_ref(tmp_path: Path) -> None:
    """验证 within_ref 限定搜索范围。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k_within_ref.html"
    source_path.write_text(
        """
        <html>
          <body>
            <p><b>Item 2.02</b> Results of Operations and Financial Condition.</p>
            <p>Revenue grew 15% year over year reaching record quarterly revenue levels.</p>
            <p><b>Item 9.01</b> Financial Statements and Exhibits.</p>
            <p>Exhibit 99.1 contains the full press release with detailed revenue breakdown.</p>
            <p><b>SIGNATURE</b></p>
            <p>Signed.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    processor = BsEightKFormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="8-K",
        media_type="text/html",
    )

    sections = processor.list_sections()
    # 找到 Item 2.02 的 ref
    item_202_ref = None
    for s in sections:
        if s.get("title") == "Item 2.02":
            item_202_ref = s["ref"]
            break
    assert item_202_ref is not None

    # "revenue" 在 Item 2.02 中搜索应命中
    hits = processor.search("revenue", within_ref=item_202_ref)
    assert len(hits) > 0

    # 用不存在的 ref 搜索应返回空
    hits_bad = processor.search("revenue", within_ref="s_9999")
    assert len(hits_bad) == 0


@pytest.mark.unit
def test_bs_eight_k_parser_version(tmp_path: Path) -> None:
    """验证 parser_version 正确设置。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    assert BsEightKFormProcessor.PARSER_VERSION == "bs_eight_k_section_processor_v1.0.0"


@pytest.mark.unit
def test_bs_eight_k_read_section_content(tmp_path: Path) -> None:
    """验证 read_section 返回正确内容。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k_read_content.html"
    source_path.write_text(
        """
        <html>
          <body>
            <p><b>Item 1.01</b> Entry into a Material Definitive Agreement.</p>
            <p>The company entered into a definitive merger agreement with XYZ Corp
            for a total consideration of 10 billion in cash and stock.</p>
            <p><b>Item 9.01</b> Financial Statements and Exhibits.</p>
            <p>Exhibit 99.1 Press Release.</p>
            <p><b>SIGNATURE</b></p>
            <p>Signed by CEO.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    processor = BsEightKFormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="8-K",
        media_type="text/html",
    )

    sections = processor.list_sections()
    # 读取 Item 1.01 的内容
    for s in sections:
        if s.get("title") == "Item 1.01":
            content_result = processor.read_section(s["ref"])
            content = content_result.get("content", "")
            assert "merger agreement" in content.lower()
            assert "10 billion" in content
            break
    else:
        pytest.fail("Item 1.01 not found in sections")


__all__ = ["test_bs_eight_k_supports_html_8k"]
