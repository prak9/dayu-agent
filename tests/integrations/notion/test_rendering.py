"""Notion 报告投影、表格和回读完整内容核验测试。"""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from alpha.contracts.research import EvidenceClassification, ResearchEvidence
from alpha.contracts.research_working import ResearchReportContent
from alpha.research.publication_identity import publication_identifier, publication_marker
from alpha.research.publication_rendering import notion_markdown, render_publication, verify_publication_markdown
from alpha.research.storage.catalog import SQLiteResearchCatalog
from tests.research.test_publications import _ready


def test_tables_keep_values_and_code_blocks_remain_code() -> None:
    """表格转官方语法，代码块中的管道保持原文。参数：无。返回：无。异常：断言失败。"""
    source = "| 项目 | 2025 |\n| :--- | ---: |\n| Revenue | $1,000 |\n| A\\|B | 2 |\n\n```text\n| x | y |\n| - | - |\n```"
    converted = notion_markdown(source)
    assert "<td>$1,000</td>" in converted and "<td>A|B</td>" in converted
    assert "```text\n| x | y |\n| - | - |\n```" in converted
    assert notion_markdown("原文\n没有表格") == "原文\n没有表格"


def test_readback_accepts_formatting_but_rejects_changed_facts_links_and_symbols() -> None:
    """格式归一不放过数值、币种、反证文字和来源改变。参数：无。返回：无。异常：断言失败。"""
    marker = publication_marker("publication_test")
    expected = f"# 判断\n\n收入 **$100.00**，β=2。\n\n[原始来源](https://example.com/report)\n\n{marker}"
    actual = f"# 判断\n\n收入 $100.00，β=2。\n\n[原始来源](https://example.com/report)\n\n{marker}\n"
    verify_publication_markdown(expected, actual, "publication_test")
    verify_publication_markdown(expected.replace("[原始来源](https://example.com/report)", "https://example.com/report"),
                                 actual.replace("[原始来源]", "[https://example.com/report]"), "publication_test")
    for changed in (actual.replace("100.00", "1000.00"), actual.replace("$", "€"), actual.replace("β", "γ"),
                    actual.replace("$100.00", "-$100.00"), actual.replace("$100.00", "($100.00)"), actual.replace("$100.00", "- $100.00"),
                    actual.replace("example.com", "different.com"), marker, actual.replace("判断", "不判断")):
        with pytest.raises(ValueError, match="回读"):
            verify_publication_markdown(expected, changed, "publication_test")


def test_rendered_page_contains_original_evidence_and_version_identity(tmp_path: Path) -> None:
    """指定版本渲染保留证据定位、时间与方法来源。参数：目录。返回：无。异常：断言失败。"""
    store, _, revision = _ready(tmp_path)
    research = SQLiteResearchCatalog(store).get(revision.research_id, "owner")
    evidence = ResearchEvidence("ev-1", "https://example.com/report", "10-K", "原始摘录", EvidenceClassification.REPORTED_FACT,
                                datetime.now(timezone.utc), locator="p. 42", time_missing_reason="原件未列公开时间")
    content = ResearchReportContent("# 分析\n\n[财报定位](fins://doc/section)", (evidence,))
    title, markdown = render_publication(research, replace(revision, parent_revision_id="previous-revision"), content, "invest")
    identifier = publication_identifier(revision.revision_id, "invest")
    assert identifier in title and publication_marker(identifier) in markdown
    assert "p. 42" in markdown and "原始摘录" in markdown and "原件未列公开时间" in markdown
    assert revision.content_hash in markdown and revision.skill_hash in markdown and "previous-revision" in markdown
    assert "[财报定位](fins://" not in markdown and "本地引用：fins://doc/section" in markdown
