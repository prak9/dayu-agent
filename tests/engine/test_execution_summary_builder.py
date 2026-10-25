"""运行摘要构建模块测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from alpha.services.internal.write_pipeline.execution_summary_builder import ExecutionSummaryBuilder
from alpha.services.internal.write_pipeline.models import ChapterResult

from tests.engine.test_write_pipeline import _build_runner


@pytest.mark.unit
def test_build_summary_collects_failed_chapters(tmp_path: Path) -> None:
    """验证运行摘要会正确聚合失败章节信息。"""

    runner = _build_runner(tmp_path)
    builder = ExecutionSummaryBuilder(write_config=runner._write_config)
    chapter_results = {
        "公司介绍": ChapterResult(
            index=1,
            title="公司介绍",
            status="passed",
            content="ok",
            audit_passed=True,
        ),
        "竞争优势": ChapterResult(
            index=2,
            title="竞争优势",
            status="failed",
            content="",
            audit_passed=False,
            retry_count=2,
            failure_reason="evidence_insufficient",
        ),
    }

    result = builder.build_summary(
        chapter_results,
        output_file=Path("/tmp/report.md"),
        success_predicate=lambda item: bool(item and item.status == "passed"),
    )

    assert result["ticker"] == "AAPL"
    assert result["chapter_count"] == 2
    assert result["failed_count"] == 1
    assert result["failed_chapters"] == [
        {
            "title": "竞争优势",
            "reason": "evidence_insufficient",
            "retry_count": 2,
        }
    ]