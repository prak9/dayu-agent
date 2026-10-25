"""来源清单构建模块测试。"""

from __future__ import annotations

from alpha.services.internal.write_pipeline.source_list_builder import (
    build_source_entries,
    extract_evidence_items,
    looks_like_evidence_item,
    render_source_list_chapter,
)


def test_extract_evidence_items_reads_bullets_under_heading() -> None:
    """验证仅提取“证据与出处”下的条目。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    markdown = """
## 收入结构

### 结论要点
- 结论A

### 证据与出处
- SEC EDGAR | Form 10-K | Filed 2025-02-01 | Accession 0000000000-25-000001
- 公司官网 | 2025-01-01 | 新闻稿 | URL:https://example.com/pr

### 详细情况
- 内容
""".strip()

    items = extract_evidence_items(markdown)

    assert len(items) == 2
    assert items[0].startswith("SEC EDGAR")
    assert "example.com" in items[1]


def test_extract_evidence_items_accepts_bare_evidence_lines_and_skips_fences() -> None:
    """验证裸 evidence 行会被抽取， stray fence 会被忽略。"""

    markdown = """
## 决策

### 证据与出处

SEC EDGAR | Form 10-K | Filed 2025-02-01 | Accession 0000000000-25-000001 | Part II - Item 8
```
Reuters | 标题 | 访问日期 2026-04-01 | URL:https://example.com/a

### 详细情况
- 正文
""".strip()

    items = extract_evidence_items(markdown)

    assert items == [
        "SEC EDGAR | Form 10-K | Filed 2025-02-01 | Accession 0000000000-25-000001 | Part II - Item 8",
        "Reuters | 标题 | 访问日期 2026-04-01 | URL:https://example.com/a",
    ]


def test_build_source_entries_deduplicates_and_classifies() -> None:
    """验证来源去重与分组归类。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    entries = build_source_entries(
        [
            "SEC EDGAR | Form 10-K | Filed 2025-02-01 | Accession 0000000000-25-000001",
            "SEC EDGAR | Form 10-K | Filed 2025-02-01 | Accession 0000000000-25-000001",
            "公司官网 | 2025-01-01 | 页面 | URL:https://investor.example.com",
            "Reuters | 2025-01-03 | 报道 | URL:https://reuters.com/x",
        ]
    )

    assert len(entries) == 3
    groups = {item.group for item in entries}
    assert "SEC filings" in groups
    assert "公司官网与公告/新闻稿" in groups
    assert "媒体报道" in groups


def test_render_source_list_chapter_contains_all_groups() -> None:
    """验证来源清单章节渲染包含固定分组。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    entries = build_source_entries(
        [
            "SEC EDGAR | Form 20-F | Filed 2024-12-31 | Accession 0000000000-24-000888",
        ]
    )
    markdown = render_source_list_chapter(entries)

    assert markdown.startswith("## 来源清单")
    assert "### SEC filings" in markdown
    assert "### 媒体报道" in markdown
    assert "- 无" in markdown


def test_extract_evidence_items_stops_at_h4_glossary() -> None:
    """验证遇到 #### 关键术语说明 时停止收集，不将术语条目误判为证据。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    markdown = """
## 产品分析

### 证据与出处
- SEC EDGAR | Form 20-F | Filed 2025-03-01 | Accession 0000000099-25-000001

#### 关键术语说明
- ASP
  - "Average Selling Price per unit"
  - 单位平均售价
""".strip()

    items = extract_evidence_items(markdown)

    assert len(items) == 1
    assert items[0].startswith("SEC EDGAR")
    glossary_leaked = any(
        kw in item for item in items for kw in ("ASP", "Average Selling Price", "单位平均售价")
    )
    assert not glossary_leaked


def test_looks_like_evidence_item_requires_at_least_four_segments() -> None:
    """验证 evidence 行识别要求至少 4 段。"""

    assert looks_like_evidence_item("SEC EDGAR | Form 10-K | Filed 2025-02-01 | Accession 0000000000-25-000001") is True
    assert looks_like_evidence_item("这是一句正文，不是证据") is False
    assert looks_like_evidence_item("字段1 | 字段2 | 字段3") is False


def test_build_source_entries_deduplicates_by_first_three_segments() -> None:
    """验证来源清单按前三段字段去重。"""

    accession = "SEC EDGAR | Form DEF 14A | Filed 2025-12-08 | Accession 0001308179-25-000635"
    entries = build_source_entries(
        [
            accession + " | Section 薪酬政策",
            accession + " | Section 薪酬政策",
            accession + " | Item 8 财务报表",
        ]
    )

    assert len(entries) == 1
    assert entries[0].text == accession + " | Section 薪酬政策"


def test_build_source_entries_keeps_different_web_lines() -> None:
    """验证不同网页 evidence line 不会因相同 URL 被错误合并。"""

    entries = build_source_entries(
        [
            "Reuters | 标题A | 访问日期 2026-04-01 | URL:https://reuters.com/asml-q4",
            "Reuters | 标题B | 访问日期 2026-04-02 | URL:https://reuters.com/asml-q4",
        ]
    )

    assert len(entries) == 2


def test_build_source_entries_merges_same_hk_cn_document_with_different_locations() -> None:
    """验证港股/A股同一文档不同定位会按前三段合并。"""

    entries = build_source_entries(
        [
            "腾讯控股 | 2024年度报告 | 2024财年，公告日期未披露 | 第二章 业务概况",
            "腾讯控股 | 2024年度报告 | 2024财年，公告日期未披露 | 第四章 财务报告",
        ]
    )

    assert len(entries) == 1
    assert entries[0].text == "腾讯控股 | 2024年度报告 | 2024财年，公告日期未披露 | 第二章 业务概况"


def test_build_source_entries_classifies_cn_annual_report_as_uploaded_document() -> None:
    """验证 A 股年度报告不会被误分到监管机构与官方发布。"""

    entries = build_source_entries(
        [
            "福耀玻璃 | 2025年年度报告 | 2025年 | (一) 主要会计数据 | 表格t_0009",
        ]
    )

    assert len(entries) == 1
    assert entries[0].group == "上传财报/公告"
