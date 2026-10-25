"""最终报告拼装模块测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from alpha.services.internal.write_pipeline.models import ChapterResult
from alpha.services.internal.write_pipeline.report_assembler import ReportAssembler
from alpha.services.internal.write_pipeline.template_parser import parse_template_layout

from tests.engine.test_write_pipeline import _build_runner


@pytest.mark.unit
def test_assemble_report_replaces_preface_placeholders(tmp_path: Path) -> None:
    """验证 assemble_report 会替换 preface 中的占位符。"""

    runner = _build_runner(tmp_path)
    assembler = ReportAssembler(write_config=runner._write_config)
    template_text = (
        "# [公司名称] 全貌梳理\n\n"
        "本文基于 [公司名称] (TICKER) 公开披露信息生成。\n\n"
        "<!-- 这段写作说明不应出现在最终报告中 -->\n\n"
        "---\n\n"
        "## 投资要点概览\n\n"
        "x\n\n"
        "## 来源清单\n\n"
        "x"
    )
    layout = parse_template_layout(template_text)
    result = assembler.assemble_report(layout, {}, "## 来源清单\n\n- 无", company_name="Apple Inc.")

    assert "# Apple Inc. 全貌梳理" in result
    assert "Apple Inc. (AAPL)" in result
    assert "[公司名称]" not in result
    assert "(TICKER)" not in result
    assert "这段写作说明不应出现在最终报告中" not in result
    assert "\n\n---\n\n---\n\n" not in result


@pytest.mark.unit
def test_assemble_report_strips_evidence_from_overview(tmp_path: Path) -> None:
    """验证概览章在最终报告中不会保留证据与出处小节。"""

    runner = _build_runner(tmp_path)
    assembler = ReportAssembler(write_config=runner._write_config)
    layout = parse_template_layout(
        "## 投资要点概览\n\n### 结论要点\n\n- \n\n### 证据与出处\n\n- \n\n"
        "## 公司介绍\n\nx\n\n"
        "## 来源清单\n\nx\n"
    )
    overview_result = ChapterResult(
        index=1,
        title="投资要点概览",
        status="passed",
        content=(
            "## 投资要点概览\n\n"
            "### 结论要点\n\n- 核心业务\n\n"
            "### 证据与出处\n\n- 来源1"
        ),
        audit_passed=True,
    )

    result = assembler.assemble_report(
        layout,
        {"投资要点概览": overview_result},
        "## 来源清单\n\n- 无",
        company_name="TestCo",
    )

    overview_block = result.split("## 投资要点概览")[1].split("## 公司介绍")[0]
    assert "### 证据与出处" not in overview_block
    assert "来源1" not in overview_block
    assert "### 结论要点" in overview_block


@pytest.mark.unit
def test_assemble_report_without_source_chapter_keeps_template_order(tmp_path: Path) -> None:
    """验证模板缺少来源清单时，最终报告仍按模板顺序组装。"""

    runner = _build_runner(tmp_path)
    assembler = ReportAssembler(write_config=runner._write_config)
    layout = parse_template_layout(
        "## 投资要点概览\n\n### 结论要点\n\n- \n\n"
        "## 公司介绍\n\nx\n\n"
        "## 是否值得继续深研与待验证问题\n\nx\n"
    )
    chapter_results = {
        "投资要点概览": ChapterResult(
            index=1,
            title="投资要点概览",
            status="passed",
            content="## 投资要点概览\n\n### 结论要点\n\n- 核心业务\n\n### 证据与出处\n\n- 来源1",
            audit_passed=True,
        ),
        "公司介绍": ChapterResult(
            index=2,
            title="公司介绍",
            status="passed",
            content="## 公司介绍\n\n- 正文",
            audit_passed=True,
        ),
    }

    result = assembler.assemble_report(layout, chapter_results, None, company_name="TestCo")

    assert "## 投资要点概览" in result
    assert "## 公司介绍" in result
    assert "## 是否值得继续深研与待验证问题" in result
    assert "## 来源清单" not in result