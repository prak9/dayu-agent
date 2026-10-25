"""active 6-K 复判与误收剔除测试。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from alpha.fins.active_6k_retriage import retriage_active_6k_filings
from alpha.fins.domain.document_models import CompanyMeta, SourceDocumentUpsertRequest, now_iso8601
from alpha.fins.domain.enums import SourceKind
from tests.fins.storage_testkit import FsStorageTestContext, build_fs_storage_test_context


def _upsert_company(context: FsStorageTestContext, ticker: str) -> None:
    """写入测试公司元数据。

    Args:
        context: 存储上下文。
        ticker: 股票代码。

    Returns:
        无。

    Raises:
        OSError: 写入失败时抛出。
    """

    context.company_repository.upsert_company_meta(
        CompanyMeta(
            company_id=f"cik-{ticker}",
            company_name=f"{ticker} Corp",
            ticker=ticker,
            market="US",
            resolver_version="test",
            updated_at=now_iso8601(),
            ticker_aliases=[ticker],
        )
    )


def _create_active_filing(
    context: FsStorageTestContext,
    *,
    ticker: str,
    document_id: str,
    primary_document: str,
    files: dict[str, bytes],
    report_date: str,
) -> None:
    """创建测试用 active filing。

    Args:
        context: 存储上下文。
        ticker: 股票代码。
        document_id: 文档 ID。
        primary_document: 主文件名。
        files: 要写入的文件内容映射。
        report_date: 报告期日期。

    Returns:
        无。

    Raises:
        OSError: 仓储写入失败时抛出。
    """

    internal_document_id = document_id.removeprefix("fil_")
    context.source_repository.create_source_document(
        SourceDocumentUpsertRequest(
            ticker=ticker,
            document_id=document_id,
            internal_document_id=internal_document_id,
            form_type="6-K",
            primary_document=primary_document,
            meta={
                "document_id": document_id,
                "internal_document_id": internal_document_id,
                "accession_number": internal_document_id,
                "company_id": f"cik-{ticker}",
                "form_type": "6-K",
                "filing_date": report_date,
                "report_date": report_date,
                "source_fingerprint": f"fp-{document_id}",
                "ingest_method": "download",
                "is_deleted": False,
            },
        ),
        source_kind=SourceKind.FILING,
    )

    handle = context.source_repository.get_source_handle(ticker, document_id, SourceKind.FILING)
    file_entries: list[dict[str, object]] = []
    for filename, payload in files.items():
        file_meta = context.blob_repository.store_file(
            handle=handle,
            filename=filename,
            data=BytesIO(payload),
            content_type="text/html",
        )
        file_entries.append(
            {
                "name": filename,
                "uri": file_meta.uri,
                "etag": file_meta.etag,
                "last_modified": file_meta.last_modified,
                "size": file_meta.size,
                "content_type": file_meta.content_type,
                "sha256": file_meta.sha256,
                "source_url": f"https://example.test/{ticker}/{document_id}/{filename}",
                "ingested_at": now_iso8601(),
            }
        )
    context.source_repository.update_source_document(
        SourceDocumentUpsertRequest(
            ticker=ticker,
            document_id=document_id,
            internal_document_id=internal_document_id,
            form_type="6-K",
            primary_document=primary_document,
            meta={
                "document_id": document_id,
                "internal_document_id": internal_document_id,
                "accession_number": internal_document_id,
                "company_id": f"cik-{ticker}",
                "form_type": "6-K",
                "filing_date": report_date,
                "report_date": report_date,
                "source_fingerprint": f"fp-{document_id}",
                "ingest_method": "download",
                "is_deleted": False,
            },
            file_entries=file_entries,
        ),
        source_kind=SourceKind.FILING,
    )


@pytest.mark.unit
def test_retriage_active_6k_filings_dry_run_leaves_active_source_unchanged(tmp_path: Path) -> None:
    """验证 dry-run 只识别误收候选，不修改 active source。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "ALC")
    _create_active_filing(
        context,
        ticker="ALC",
        document_id="fil_alc_1",
        primary_document="cover.htm",
        files={
            "cover.htm": b"Alcon Agrees to Acquire STAAR Surgical in cash transaction.",
        },
        report_date="2025-07-01",
    )

    report = retriage_active_6k_filings(
        workspace_root=tmp_path,
        apply=False,
        target_tickers=["ALC"],
    )

    assert [candidate.document_id for candidate in report.candidates] == ["fil_alc_1"]
    assert report.outcomes[0].reason == "dry_run"
    meta = context.source_repository.get_source_meta("ALC", "fil_alc_1", SourceKind.FILING)
    assert meta["is_deleted"] is False
    assert context.filing_maintenance_repository.list_rejected_filing_artifacts("ALC") == []


@pytest.mark.unit
def test_retriage_active_6k_filings_apply_archives_and_deletes_false_positive(tmp_path: Path) -> None:
    """验证 apply 会把误收 active 6-K 写入 `.rejections/` 并退出 active。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "ALC")
    _create_active_filing(
        context,
        ticker="ALC",
        document_id="fil_alc_1",
        primary_document="cover.htm",
        files={
            "cover.htm": b"Alcon Agrees to Acquire STAAR Surgical in cash transaction.",
            "ex99.htm": b"As previously announced, STAAR will release financial results later.",
        },
        report_date="2025-07-01",
    )

    report = retriage_active_6k_filings(
        workspace_root=tmp_path,
        apply=True,
        target_tickers=["ALC"],
    )

    assert [candidate.document_id for candidate in report.candidates] == ["fil_alc_1"]
    assert report.outcomes[0].action == "rejected"
    assert report.outcomes[0].current_classification == "EXCLUDE_NON_QUARTERLY"

    meta = context.source_repository.get_source_meta("ALC", "fil_alc_1", SourceKind.FILING)
    assert meta["is_deleted"] is True
    artifact = context.filing_maintenance_repository.get_rejected_filing_artifact("ALC", "fil_alc_1")
    assert artifact.rejection_reason == "6k_filtered"
    assert artifact.rejection_category == "EXCLUDE_NON_QUARTERLY"
    assert sorted(item.name for item in artifact.files) == ["cover.htm", "ex99.htm"]
    registry = context.filing_maintenance_repository.load_download_rejection_registry("ALC")
    assert registry["fil_alc_1"]["reason"] == "6k_filtered"


@pytest.mark.unit
def test_retriage_active_6k_filings_keeps_true_quarterly_results(tmp_path: Path) -> None:
    """验证真实季度结果不会被误移出 active。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "FMX")
    _create_active_filing(
        context,
        ticker="FMX",
        document_id="fil_fmx_1",
        primary_document="ex99.htm",
        files={
            "ex99.htm": (
                b"1Q 2025 Results April 28, 2025 Monterrey, Mexico announced today its operational and financial results for the first quarter of 2025."
            ),
        },
        report_date="2025-04-28",
    )

    report = retriage_active_6k_filings(
        workspace_root=tmp_path,
        apply=True,
        target_tickers=["FMX"],
    )

    assert report.candidates == []
    assert report.outcomes == []
    meta = context.source_repository.get_source_meta("FMX", "fil_fmx_1", SourceKind.FILING)
    assert meta["is_deleted"] is False
    assert context.filing_maintenance_repository.list_rejected_filing_artifacts("FMX") == []


@pytest.mark.unit
def test_retriage_active_6k_filings_skips_broken_active_meta(tmp_path: Path) -> None:
    """验证坏掉的 active filing meta 不会中断整批 retriage。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "ALC")
    _create_active_filing(
        context,
        ticker="ALC",
        document_id="fil_alc_good_1",
        primary_document="cover.htm",
        files={
            "cover.htm": b"Alcon Agrees to Acquire STAAR Surgical in cash transaction.",
        },
        report_date="2025-07-01",
    )
    broken_dir = tmp_path / "portfolio" / "ALC" / "filings" / "fil_alc_broken_1"
    broken_dir.mkdir(parents=True, exist_ok=True)
    (broken_dir / "meta.json").write_text("{bad json", encoding="utf-8")

    report = retriage_active_6k_filings(
        workspace_root=tmp_path,
        apply=False,
        target_tickers=["ALC"],
    )

    assert [candidate.document_id for candidate in report.candidates] == ["fil_alc_good_1"]
    assert report.outcomes[0].document_id == "fil_alc_good_1"
    assert report.outcomes[0].reason == "dry_run"