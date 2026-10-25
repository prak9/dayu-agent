"""`sec_download_source_upsert` 真源模块测试。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, cast

import pytest

from alpha.fins.domain.document_models import FilingCreateRequest, FilingUpdateRequest
from alpha.fins.domain.enums import SourceKind
from alpha.fins.pipelines import sec_download_source_upsert
from alpha.fins.storage import SourceDocumentRepositoryProtocol


@dataclass(frozen=True)
class _FakeFilingRecord:
    """用于 source upsert 测试的 filing 桩。"""

    accession_number: str
    form_type: str
    filing_date: str
    report_date: Optional[str]


class _SpySourceRepository:
    """记录 create/update 调用的 source 仓储桩。"""

    def __init__(self) -> None:
        """初始化调用记录。"""

        self.created_requests: list[tuple[FilingCreateRequest, SourceKind]] = []
        self.updated_requests: list[tuple[FilingUpdateRequest, SourceKind]] = []

    def create_source_document(
        self,
        req: FilingCreateRequest,
        source_kind: SourceKind,
    ) -> object:
        """记录 create_source_document 调用。

        Args:
            req: 创建请求。
            source_kind: source kind。

        Returns:
            任意占位对象。

        Raises:
            无。
        """

        self.created_requests.append((req, source_kind))
        return object()

    def update_source_document(
        self,
        req: FilingUpdateRequest,
        source_kind: SourceKind,
    ) -> object:
        """记录 update_source_document 调用。

        Args:
            req: 更新请求。
            source_kind: source kind。

        Returns:
            任意占位对象。

        Raises:
            无。
        """

        self.updated_requests.append((req, source_kind))
        return object()


@pytest.mark.unit
def test_upsert_downloaded_filing_source_document_creates_and_marks_reprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证首次下载会创建 source 文档，并在 processed 已存在时标记重处理。"""

    monkeypatch.setattr(sec_download_source_upsert, "now_iso8601", lambda: "2026-04-13T10:00:00+00:00")
    repository = _SpySourceRepository()
    source_repository = cast(SourceDocumentRepositoryProtocol, repository)
    filing = _FakeFilingRecord(
        accession_number="0000000000-25-000001",
        form_type="10-K",
        filing_date="2025-02-01",
        report_date="2024-12-31",
    )
    marked: list[tuple[str, str]] = []

    sec_download_source_upsert.upsert_downloaded_filing_source_document(
        ticker="AAPL",
        cik="0000320193",
        document_id="fil_0000000000-25-000001",
        internal_document_id="0000000000-25-000001",
        filing=filing,
        primary_document="sample-10k.htm",
        file_entries=[{"name": "sample-10k.htm", "uri": "local://AAPL/sample-10k.htm"}],
        previous_meta=None,
        source_fingerprint="fp-v1",
        download_version="sec_pipeline_download_v1.2.0",
        has_xbrl=True,
        inferred_fiscal_year=2024,
        inferred_fiscal_period="FY",
        source_repository=source_repository,
        resolve_document_version=lambda previous_meta, source_fingerprint: "v1",
        safe_get_processed_meta=lambda ticker, document_id: {"reprocess_required": False},
        mark_processed_reprocess_required=lambda ticker, document_id: marked.append((ticker, document_id)),
    )

    assert len(repository.created_requests) == 1
    request, source_kind = repository.created_requests[0]
    assert source_kind == SourceKind.FILING
    assert request.primary_document == "sample-10k.htm"
    assert request.file_entries == [{"name": "sample-10k.htm", "uri": "local://AAPL/sample-10k.htm"}]
    assert request.meta["document_version"] == "v1"
    assert request.meta["first_ingested_at"] == "2026-04-13T10:00:00+00:00"
    assert request.meta["created_at"] == "2026-04-13T10:00:00+00:00"
    assert request.meta["updated_at"] == "2026-04-13T10:00:00+00:00"
    assert request.meta["source_fingerprint"] == "fp-v1"
    assert request.meta["has_xbrl"] is True
    assert marked == [("AAPL", "fil_0000000000-25-000001")]
    assert repository.updated_requests == []


@pytest.mark.unit
def test_upsert_downloaded_filing_source_document_updates_and_preserves_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证增量更新会保留历史首入库时间与创建时间。"""

    monkeypatch.setattr(sec_download_source_upsert, "now_iso8601", lambda: "2026-04-13T10:00:00+00:00")
    repository = _SpySourceRepository()
    source_repository = cast(SourceDocumentRepositoryProtocol, repository)
    filing = _FakeFilingRecord(
        accession_number="0000000000-25-000001",
        form_type="10-K",
        filing_date="2025-02-01",
        report_date="2024-12-31",
    )
    processed_meta_calls: list[tuple[str, str]] = []
    marked: list[tuple[str, str]] = []

    sec_download_source_upsert.upsert_downloaded_filing_source_document(
        ticker="AAPL",
        cik="0000320193",
        document_id="fil_0000000000-25-000001",
        internal_document_id="0000000000-25-000001",
        filing=filing,
        primary_document="sample-10k.htm",
        file_entries=[{"name": "sample-10k.htm", "uri": "local://AAPL/sample-10k.htm"}],
        previous_meta={
            "first_ingested_at": "2025-02-02T00:00:00+00:00",
            "created_at": "2025-02-02T00:00:00+00:00",
            "source_fingerprint": "fp-v1",
        },
        source_fingerprint="fp-v1",
        download_version="sec_pipeline_download_v1.2.0",
        has_xbrl=False,
        inferred_fiscal_year=2024,
        inferred_fiscal_period="FY",
        source_repository=source_repository,
        resolve_document_version=lambda previous_meta, source_fingerprint: "v3",
        safe_get_processed_meta=lambda ticker, document_id: processed_meta_calls.append((ticker, document_id)) or None,
        mark_processed_reprocess_required=lambda ticker, document_id: marked.append((ticker, document_id)),
    )

    assert len(repository.updated_requests) == 1
    request, source_kind = repository.updated_requests[0]
    assert source_kind == SourceKind.FILING
    assert request.meta["document_version"] == "v3"
    assert request.meta["first_ingested_at"] == "2025-02-02T00:00:00+00:00"
    assert request.meta["created_at"] == "2025-02-02T00:00:00+00:00"
    assert request.meta["updated_at"] == "2026-04-13T10:00:00+00:00"
    assert marked == []
    assert processed_meta_calls == []
    assert repository.created_requests == []


@pytest.mark.unit
def test_upsert_downloaded_filing_source_document_marks_reprocess_when_fingerprint_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证历史指纹变化时会标记 processed 需重处理。"""

    monkeypatch.setattr(sec_download_source_upsert, "now_iso8601", lambda: "2026-04-13T10:00:00+00:00")
    repository = _SpySourceRepository()
    source_repository = cast(SourceDocumentRepositoryProtocol, repository)
    filing = _FakeFilingRecord(
        accession_number="0000000000-25-000001",
        form_type="10-K",
        filing_date="2025-02-01",
        report_date="2024-12-31",
    )
    marked: list[tuple[str, str]] = []

    sec_download_source_upsert.upsert_downloaded_filing_source_document(
        ticker="AAPL",
        cik="0000320193",
        document_id="fil_0000000000-25-000001",
        internal_document_id="0000000000-25-000001",
        filing=filing,
        primary_document="sample-10k.htm",
        file_entries=[{"name": "sample-10k.htm", "uri": "local://AAPL/sample-10k.htm"}],
        previous_meta={
            "first_ingested_at": "2025-02-02T00:00:00+00:00",
            "created_at": "2025-02-02T00:00:00+00:00",
            "source_fingerprint": "fp-v1",
        },
        source_fingerprint="fp-v2",
        download_version="sec_pipeline_download_v1.2.0",
        has_xbrl=False,
        inferred_fiscal_year=2024,
        inferred_fiscal_period="FY",
        source_repository=source_repository,
        resolve_document_version=lambda previous_meta, source_fingerprint: "v4",
        safe_get_processed_meta=lambda ticker, document_id: None,
        mark_processed_reprocess_required=lambda ticker, document_id: marked.append((ticker, document_id)),
    )

    assert len(repository.updated_requests) == 1
    assert repository.updated_requests[0][0].meta["source_fingerprint"] == "fp-v2"
    assert marked == [("AAPL", "fil_0000000000-25-000001")]