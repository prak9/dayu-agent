"""SEC 6-K 主文件选文诊断测试。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from alpha.fins.domain.document_models import SourceDocumentUpsertRequest
from alpha.fins.domain.enums import SourceKind
from alpha.fins.sec_6k_primary_document_diagnostics import (
    run_sec_6k_primary_document_diagnostics,
)
from tests.fins.storage_testkit import FsStorageTestContext, build_fs_storage_test_context


def _create_active_6k_filing(
    context: FsStorageTestContext,
    *,
    ticker: str,
    document_id: str,
    primary_document: str,
    file_payloads: dict[str, bytes],
) -> None:
    """创建带多个文件的 active 6-K filing。

    Args:
        context: 测试仓储上下文。
        ticker: 股票代码。
        document_id: 文档 ID。
        primary_document: 当前主文件名。
        file_payloads: 文件名到文件内容的映射。

    Returns:
        无。

    Raises:
        OSError: 仓储写入失败时抛出。
    """

    context.source_repository.create_source_document(
        SourceDocumentUpsertRequest(
            ticker=ticker,
            document_id=document_id,
            internal_document_id=document_id.replace("fil_", ""),
            form_type="6-K",
            primary_document=primary_document,
            meta={
                "form_type": "6-K",
                "report_date": "2025-09-30",
                "is_deleted": False,
            },
        ),
        source_kind=SourceKind.FILING,
    )
    handle = context.source_repository.get_source_handle(ticker, document_id, SourceKind.FILING)
    file_metas = []
    for filename, payload in file_payloads.items():
        file_metas.append(
            context.blob_repository.store_file(
                handle=handle,
                filename=filename,
                data=BytesIO(payload),
                content_type="text/html",
            )
        )
    context.source_repository.update_source_document(
        SourceDocumentUpsertRequest(
            ticker=ticker,
            document_id=document_id,
            internal_document_id=document_id.replace("fil_", ""),
            form_type="6-K",
            primary_document=primary_document,
            meta={
                "form_type": "6-K",
                "report_date": "2025-09-30",
                "is_deleted": False,
            },
            files=file_metas,
        ),
        source_kind=SourceKind.FILING,
    )


@pytest.mark.unit
def test_primary_document_diagnostics_reports_quarterly_alternative(tmp_path: Path) -> None:
    """验证当主文件非季报、替代 exhibit 为季报时会报告错位样本。"""

    context = build_fs_storage_test_context(tmp_path)
    _create_active_6k_filing(
        context,
        ticker="JHX",
        document_id="fil_jhx_primary_mismatch",
        primary_document="ex991changeinsubstantial.htm",
        file_payloads={
            "ex991changeinsubstantial.htm": (
                b"Exhibit 99.1 Change in substantial holding and governance notice"
            ),
            "ex993preliminarysecondquar.htm": (
                b"Exhibit 99.3 James Hardie Announces Preliminary Second Quarter Results "
                b"for the quarter ended September 30, 2025"
            ),
        },
    )

    report = run_sec_6k_primary_document_diagnostics(
        workspace_root=tmp_path,
        output_dir=tmp_path / "out",
        target_tickers=["JHX"],
    )

    assert report.analyzed_filing_count == 1
    assert len(report.mismatches) == 1
    sample = report.mismatches[0]
    assert sample.ticker == "JHX"
    assert sample.primary_document == "ex991changeinsubstantial.htm"
    assert sample.primary_classification == "NO_MATCH"
    assert sample.recommended_document == "ex993preliminarysecondquar.htm"
    assert sample.recommended_classification == "RESULTS_RELEASE"
    assert (tmp_path / "out" / "summary.json").exists()
    assert (tmp_path / "out" / "mismatch_samples.json").exists()


@pytest.mark.unit
def test_primary_document_diagnostics_skips_when_primary_already_quarterly(tmp_path: Path) -> None:
    """验证当主文件本身已是季度结果时不会误报主文件错位。"""

    context = build_fs_storage_test_context(tmp_path)
    _create_active_6k_filing(
        context,
        ticker="ITUB",
        document_id="fil_itub_ok",
        primary_document="eng_prx3t25.htm",
        file_payloads={
            "eng_prx3t25.htm": (
                b"Ita\xc3\xba Unibanco reports profit in the third quarter of 2025"
            ),
            "governance_notice.htm": b"Notice of meeting and governance matters",
        },
    )

    report = run_sec_6k_primary_document_diagnostics(
        workspace_root=tmp_path,
        output_dir=tmp_path / "out",
        target_tickers=["ITUB"],
    )

    assert report.analyzed_filing_count == 1
    assert report.mismatches == ()