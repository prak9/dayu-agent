"""rejected 6-K 本地救回测试。"""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest

from alpha.fins.domain.document_models import (
    CompanyMeta,
    FileObjectMeta,
    RejectedFilingArtifact,
    RejectedFilingArtifactUpsertRequest,
    SourceFileEntry,
    now_iso8601,
)
from alpha.fins.domain.enums import SourceKind
from alpha.fins import rejected_6k_rescue as rescue_module
from alpha.fins.rejected_6k_rescue import rescue_rejected_6k_filings
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


def _create_rejected_6k_artifact(
    context: FsStorageTestContext,
    *,
    ticker: str,
    document_id: str,
    cover_content: bytes,
    selected_content: bytes,
    rejection_category: str = "NO_MATCH",
) -> None:
    """创建测试用 rejected 6-K artifact。

    Args:
        context: 存储上下文。
        ticker: 股票代码。
        document_id: 文档 ID。
        cover_content: 封面文件内容。
        selected_content: selected primary 文件内容。
        rejection_category: 初始 rejection category。

    Returns:
        无。

    Raises:
        OSError: 文件写入失败时抛出。
    """

    cover_meta = context.filing_maintenance_repository.store_rejected_filing_file(
        ticker=ticker,
        document_id=document_id,
        filename="cover.htm",
        data=BytesIO(cover_content),
        content_type="text/html",
    )
    selected_meta = context.filing_maintenance_repository.store_rejected_filing_file(
        ticker=ticker,
        document_id=document_id,
        filename="ex99.htm",
        data=BytesIO(selected_content),
        content_type="text/html",
    )
    context.filing_maintenance_repository.upsert_rejected_filing_artifact(
        RejectedFilingArtifactUpsertRequest(
            ticker=ticker,
            document_id=document_id,
            internal_document_id=document_id.replace("fil_", ""),
            accession_number=document_id.replace("fil_", ""),
            company_id=f"cik-{ticker}",
            form_type="6-K",
            filing_date="2025-08-01",
            report_date="2025-06-30",
            primary_document="cover.htm",
            selected_primary_document="ex99.htm",
            rejection_reason="6k_filtered",
            rejection_category=rejection_category,
            classification_version="sec_pipeline_download_v1.1.0",
            source_fingerprint=f"fp-{document_id}",
            files=[
                SourceFileEntry(
                    name="cover.htm",
                    uri=cover_meta.uri,
                    etag=cover_meta.etag,
                    last_modified=cover_meta.last_modified,
                    size=cover_meta.size,
                    content_type=cover_meta.content_type,
                    sha256=cover_meta.sha256,
                ),
                SourceFileEntry(
                    name="ex99.htm",
                    uri=selected_meta.uri,
                    etag=selected_meta.etag,
                    last_modified=selected_meta.last_modified,
                    size=selected_meta.size,
                    content_type=selected_meta.content_type,
                    sha256=selected_meta.sha256,
                ),
            ],
        )
    )


def _seed_rejection_registry(context: FsStorageTestContext, ticker: str, document_id: str) -> None:
    """写入测试用下载拒绝注册表。

    Args:
        context: 存储上下文。
        ticker: 股票代码。
        document_id: 文档 ID。

    Returns:
        无。

    Raises:
        OSError: 写入失败时抛出。
    """

    context.filing_maintenance_repository.save_download_rejection_registry(
        ticker,
        {
            document_id: {
                "reason": "6k_filtered",
                "category": "NO_MATCH",
                "form_type": "6-K",
                "filing_date": "2025-08-01",
            }
        },
    )


@pytest.mark.unit
def test_rescue_rejected_6k_filings_dry_run_keeps_active_storage_unchanged(tmp_path: Path) -> None:
    """验证 dry-run 只识别候选，不会写回 active filings。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "BILI")
    _create_rejected_6k_artifact(
        context,
        ticker="BILI",
        document_id="fil_bili_1",
        cover_content=b"Cover page",
        selected_content=(
            b"Bilibili Inc. Announces First Quarter 2025 Financial Results "
            b"today announced its unaudited financial results for the first quarter ended March 31, 2025."
        ),
    )
    _seed_rejection_registry(context, "BILI", "fil_bili_1")

    report = rescue_rejected_6k_filings(
        workspace_root=tmp_path,
        apply=False,
        target_tickers=["BILI"],
    )

    assert [candidate.document_id for candidate in report.candidates] == ["fil_bili_1"]
    assert report.outcomes == [
        report.outcomes[0].__class__(
            ticker="BILI",
            document_id="fil_bili_1",
            action="skipped",
            reason="dry_run",
            current_classification="RESULTS_RELEASE",
        )
    ]
    with pytest.raises(FileNotFoundError):
        context.source_repository.get_source_meta("BILI", "fil_bili_1", SourceKind.FILING)
    registry = context.filing_maintenance_repository.load_download_rejection_registry("BILI")
    assert "fil_bili_1" in registry


@pytest.mark.unit
def test_rescue_rejected_6k_filings_restores_active_source_and_clears_registry(tmp_path: Path) -> None:
    """验证 apply 模式会回灌 active source 并清理 skip index。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "ASML")
    _create_rejected_6k_artifact(
        context,
        ticker="ASML",
        document_id="fil_asml_1",
        cover_content=b"Cover page",
        selected_content=(
            b"ASML reports \\xe2\\x82\\xac7.7 billion total net sales and \\xe2\\x82\\xac2.4 billion net income in Q1 2025. "
            b"Today, ASML has published its 2025 first-quarter results."
        ),
    )
    _seed_rejection_registry(context, "ASML", "fil_asml_1")

    report = rescue_rejected_6k_filings(
        workspace_root=tmp_path,
        apply=True,
        target_tickers=["ASML"],
    )

    assert [candidate.document_id for candidate in report.candidates] == ["fil_asml_1"]
    assert report.outcomes == [
        report.outcomes[0].__class__(
            ticker="ASML",
            document_id="fil_asml_1",
            action="rescued",
            reason="restored_from_rejections",
            current_classification="RESULTS_RELEASE",
        )
    ]

    source_meta = context.source_repository.get_source_meta("ASML", "fil_asml_1", SourceKind.FILING)
    assert source_meta["is_deleted"] is False
    assert source_meta["primary_document"] == "ex99.htm"
    active_handle = context.source_repository.get_source_handle("ASML", "fil_asml_1", SourceKind.FILING)
    assert context.blob_repository.read_file_bytes(active_handle, "cover.htm") == b"Cover page"
    assert b"first-quarter results" in context.blob_repository.read_file_bytes(active_handle, "ex99.htm")
    registry = context.filing_maintenance_repository.load_download_rejection_registry("ASML")
    assert registry == {}
    artifact = context.filing_maintenance_repository.get_rejected_filing_artifact("ASML", "fil_asml_1")
    assert artifact.document_id == "fil_asml_1"


@pytest.mark.unit
def test_rescue_rejected_6k_filings_skips_non_quarterly_rejections(tmp_path: Path) -> None:
    """验证非季报 rejected artifact 不会被误救回。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "ALC")
    _create_rejected_6k_artifact(
        context,
        ticker="ALC",
        document_id="fil_alc_1",
        cover_content=b"Cover page",
        selected_content=b"Alcon Agrees to Acquire STAAR Surgical in cash transaction.",
        rejection_category="RESULTS_RELEASE",
    )
    _seed_rejection_registry(context, "ALC", "fil_alc_1")

    report = rescue_rejected_6k_filings(
        workspace_root=tmp_path,
        apply=True,
        target_tickers=["ALC"],
    )

    assert report.candidates == []
    assert report.outcomes == []
    with pytest.raises(FileNotFoundError):
        context.source_repository.get_source_meta("ALC", "fil_alc_1", SourceKind.FILING)
    registry = context.filing_maintenance_repository.load_download_rejection_registry("ALC")
    assert "fil_alc_1" in registry


@pytest.mark.unit
def test_rescue_rejected_6k_filings_skips_broken_rejection_directories(tmp_path: Path) -> None:
    """验证坏掉的 `.rejections/` 目录不会中断整批 rescue。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "BLK")
    _create_rejected_6k_artifact(
        context,
        ticker="BLK",
        document_id="fil_blk_good_1",
        cover_content=b"Cover page",
        selected_content=(
            b"BlackRock Announces First Quarter 2025 Results and unaudited financial results for the quarter ended."
        ),
    )
    broken_dir = (
        tmp_path
        / "portfolio"
        / "BLK"
        / "filings"
        / ".rejections"
        / "fil_blk_broken_1"
    )
    broken_dir.mkdir(parents=True, exist_ok=True)

    report = rescue_rejected_6k_filings(
        workspace_root=tmp_path,
        apply=False,
        target_tickers=["BLK"],
    )

    assert [candidate.document_id for candidate in report.candidates] == ["fil_blk_good_1"]
    assert report.outcomes == [
        report.outcomes[0].__class__(
            ticker="BLK",
            document_id="fil_blk_good_1",
            action="skipped",
            reason="dry_run",
            current_classification="RESULTS_RELEASE",
        )
    ]


@pytest.mark.unit
def test_rescue_rejected_6k_filings_skips_annual_report_with_late_quarter_phrase(tmp_path: Path) -> None:
    """验证 annual report 深层季度词不会误触发 rescue。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "ASML")
    annual_report_prefix = (
        b"Exhibit 99.1 ASML Annual Report 2025 STRATEGIC REPORT CORPORATE GOVERNANCE "
        b"SUSTAINABILITY FINANCIALS At a glance Our business Financial performance Risk factors "
    )
    late_quarter_phrase = (
        b" Today, ASML has published its 2025 fourth-quarter and full-year results. "
        b"Q4 total net sales were strong."
    )
    _create_rejected_6k_artifact(
        context,
        ticker="ASML",
        document_id="fil_asml_annual_1",
        cover_content=b"Cover page",
        selected_content=annual_report_prefix + (b"A" * 5000) + late_quarter_phrase,
        rejection_category="NO_MATCH",
    )
    _seed_rejection_registry(context, "ASML", "fil_asml_annual_1")

    report = rescue_rejected_6k_filings(
        workspace_root=tmp_path,
        apply=True,
        target_tickers=["ASML"],
    )

    assert report.candidates == []
    assert report.outcomes == []
    with pytest.raises(FileNotFoundError):
        context.source_repository.get_source_meta("ASML", "fil_asml_annual_1", SourceKind.FILING)
    registry = context.filing_maintenance_repository.load_download_rejection_registry("ASML")
    assert "fil_asml_annual_1" in registry


@pytest.mark.unit
def test_rejected_6k_rescue_helper_functions_cover_target_and_meta_edges(tmp_path: Path) -> None:
    """验证 rejected 6-K rescue helper 的剩余边界分支。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "bili")
    _upsert_company(context, "asml")
    _create_rejected_6k_artifact(
        context,
        ticker="BILI",
        document_id="fil_bili_helper_1",
        cover_content=b"Cover page",
        selected_content=b"Quarterly results release",
    )
    artifact = context.filing_maintenance_repository.get_rejected_filing_artifact("BILI", "fil_bili_helper_1")

    assert rescue_module._normalize_targets([" bili ", "", "BILI", "asml"], uppercase=True) == ["BILI", "ASML"]
    assert rescue_module._normalize_targets([], uppercase=False) is None
    assert set(
        rescue_module._resolve_target_tickers(
            company_repository=context.company_repository,
            target_tickers=None,
        )
    ) == {"BILI", "ASML"}
    assert rescue_module._should_consider_artifact(artifact, document_id_filter=set()) is True
    assert rescue_module._should_consider_artifact(artifact, document_id_filter={"other_doc"}) is False
    assert rescue_module._resolve_selected_primary_document(replace(artifact, selected_primary_document="   ")) == "cover.htm"
    assert rescue_module._get_source_meta_if_present(
        source_repository=context.source_repository,
        ticker="BILI",
        document_id="missing_doc",
    ) is None


@pytest.mark.unit
def test_rejected_6k_rescue_helper_functions_cover_restore_payload_and_cleanup() -> None:
    """验证 rescue helper 的 meta 构建、文件清理和条目映射分支。"""

    artifact = RejectedFilingArtifact(
        ticker="BILI",
        document_id="fil_bili_helper_2",
        internal_document_id="helper-2",
        accession_number="0002",
        company_id="cik-BILI",
        form_type="6-K",
        filing_date="2025-08-01",
        report_date="2025-06-30",
        primary_document="cover.htm",
        selected_primary_document="ex99.htm",
        rejection_reason="6k_filtered",
        rejection_category="NO_MATCH",
        classification_version="sec_pipeline_download_v1.1.0",
        source_fingerprint="fp-helper-2",
        report_kind=None,
        fiscal_year=2025,
        fiscal_period="Q2",
        ingest_method="sec_download",
        has_xbrl=False,
        amended=False,
        created_at="2025-08-01T00:00:00+00:00",
        files=[
            SourceFileEntry(
                name="cover.htm",
                uri="local://BILI/rejections/cover.htm",
                source_url="https://example.com/cover",
                http_etag="etag-cover",
                http_last_modified="Mon, 01 Jan 2025 00:00:00 GMT",
                ingested_at="2025-08-01T00:00:00+00:00",
            )
        ],
    )
    preserved_meta = rescue_module._build_rescued_source_meta(
        artifact=artifact,
        existing_meta={
            "created_at": "2024-01-01T00:00:00+00:00",
            "first_ingested_at": "2024-01-02T00:00:00+00:00",
            "document_version": "v7",
        },
    )

    class _BlobRepository:
        """最小 blob 仓储桩，用于验证 stale 清理。"""

        def __init__(self) -> None:
            """初始化删除记录。"""

            self.deleted: list[str] = []

        def list_entries(self, _handle: object) -> list[object]:
            """返回当前目录条目。"""

            return [
                type("Entry", (), {"is_file": True, "name": "stale.htm"})(),
                type("Entry", (), {"is_file": True, "name": "cover.htm"})(),
                type("Entry", (), {"is_file": False, "name": "subdir"})(),
            ]

        def delete_entry(self, _handle: object, name: str) -> None:
            """记录被删除的文件名。"""

            self.deleted.append(name)

    blob_repository = _BlobRepository()
    rescue_module._remove_stale_active_source_entries(
        blob_repository=cast(Any, blob_repository),
        active_handle=object(),  # type: ignore[arg-type]
        valid_filenames={"cover.htm"},
    )
    restored_entry = rescue_module._build_restored_source_entry(
        original_entry=artifact.files[0],
        stored_file_meta=FileObjectMeta(
            uri="local://BILI/filings/fil_bili_helper_2/cover.htm",
            etag="etag-new",
            last_modified="2025-08-02T00:00:00+00:00",
            size=123,
            content_type="text/html",
            sha256="sha256:new",
        ),
    )

    assert preserved_meta["created_at"] == "2024-01-01T00:00:00+00:00"
    assert preserved_meta["first_ingested_at"] == "2024-01-02T00:00:00+00:00"
    assert preserved_meta["document_version"] == "v7"
    assert blob_repository.deleted == ["stale.htm"]
    assert restored_entry.uri.endswith("cover.htm")
    assert restored_entry.source_url == "https://example.com/cover"
    assert restored_entry.http_etag == "etag-cover"


@pytest.mark.unit
def test_write_rescued_source_document_falls_back_to_create_when_deleted_meta_has_no_file() -> None:
    """验证 deleted meta 缺实体文件时，rescue 会回退到 create。"""

    request = rescue_module.SourceDocumentUpsertRequest(
        ticker="EDN",
        document_id="fil_edn_helper_1",
        internal_document_id="edn-helper-1",
        form_type="6-K",
        primary_document="ex99.htm",
        meta={"is_deleted": False},
        file_entries=[],
    )

    class _SourceRepositoryStub:
        """最小 source 仓储桩，用于验证 update 失败后的 create fallback。"""

        def __init__(self) -> None:
            """初始化调用记录。"""

            self.calls: list[str] = []

        def create_source_document(
            self,
            req: rescue_module.SourceDocumentUpsertRequest,
            _source_kind: SourceKind,
        ) -> None:
            """记录 create 调用。"""

            assert req.document_id == "fil_edn_helper_1"
            self.calls.append("create")

        def update_source_document(
            self,
            _req: rescue_module.SourceDocumentUpsertRequest,
            _source_kind: SourceKind,
        ) -> None:
            """模拟 deleted meta 对应实体文件已缺失。"""

            self.calls.append("update")
            raise FileNotFoundError("missing meta")

    repository = _SourceRepositoryStub()

    rescue_module._write_rescued_source_document(
        source_repository=cast(Any, repository),
        request=request,
        existing_meta={"is_deleted": True},
    )

    assert repository.calls == ["update", "create"]
