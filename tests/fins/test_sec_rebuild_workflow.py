"""`sec_rebuild_workflow` 真源边界测试。"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

from alpha.fins.domain.document_models import SourceDocumentUpsertRequest
from alpha.fins.domain.enums import SourceKind
from alpha.fins.pipelines.sec_form_utils import (
    expand_form_aliases as _expand_form_aliases,
    normalize_form as _normalize_form,
    parse_date as _parse_date,
    split_form_input as _split_form_input,
)
from alpha.fins.pipelines.sec_pipeline import SEC_PIPELINE_DOWNLOAD_VERSION
from alpha.fins.pipelines.sec_rebuild_workflow import (
    _should_preserve_previous_rebuild_fiscal_fields,
    build_rebuild_filter_spec,
    overwrite_rebuilt_meta,
    passes_rebuild_filters,
    rebuild_single_local_filing,
)
from tests.fins.storage_testkit import build_fs_storage_test_context


def test_build_rebuild_filter_spec_expands_aliases_and_dates() -> None:
    """重建过滤条件应展开 SC13 别名并解析日期边界。"""

    target_forms, start_bound, end_bound = build_rebuild_filter_spec(
        form_type="SC13D/G",
        start_date="2024-01",
        end_date="2024",
        expand_form_aliases=_expand_form_aliases,
        split_form_input=_split_form_input,
        parse_date=_parse_date,
    )

    assert target_forms == {"SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"}
    assert start_bound == _parse_date("2024-01", False)
    assert end_bound == _parse_date("2024", True)


def test_passes_rebuild_filters_applies_form_and_date_bounds() -> None:
    """重建过滤应同时收敛 form 与 filing_date。"""

    target_forms, start_bound, end_bound = build_rebuild_filter_spec(
        form_type="10-K",
        start_date="2024-01-01",
        end_date="2024-12-31",
        expand_form_aliases=_expand_form_aliases,
        split_form_input=_split_form_input,
        parse_date=_parse_date,
    )

    assert passes_rebuild_filters(
        meta={"form_type": "10-K", "filing_date": "2024-06-30"},
        target_forms=target_forms,
        start_bound=start_bound,
        end_bound=end_bound,
        normalize_form=_normalize_form,
        parse_date=_parse_date,
    ) is True
    assert passes_rebuild_filters(
        meta={"form_type": "8-K", "filing_date": "2024-06-30"},
        target_forms=target_forms,
        start_bound=start_bound,
        end_bound=end_bound,
        normalize_form=_normalize_form,
        parse_date=_parse_date,
    ) is False
    assert passes_rebuild_filters(
        meta={"form_type": "10-K", "filing_date": "2025-01-01"},
        target_forms=target_forms,
        start_bound=start_bound,
        end_bound=end_bound,
        normalize_form=_normalize_form,
        parse_date=_parse_date,
    ) is False


def test_rebuild_single_local_filing_rewrites_canonical_meta(tmp_path: Path) -> None:
    """单 filing 重建应保留版本并覆盖掉历史脏字段。"""

    context = build_fs_storage_test_context(tmp_path)
    ticker = "AAPL"
    document_id = "fil_0000000000-25-000001"

    context.source_repository.create_source_document(
        SourceDocumentUpsertRequest(
            ticker=ticker,
            document_id=document_id,
            internal_document_id="0000000000-25-000001",
            form_type="10-K",
            primary_document="sample-10k.htm",
            meta={},
        ),
        source_kind=SourceKind.FILING,
    )
    handle = context.source_repository.get_source_handle(ticker, document_id, SourceKind.FILING)
    stored_file = context.blob_repository.store_file(
        handle=handle,
        filename="sample-10k.htm",
        data=BytesIO(b"<html>sample</html>"),
        content_type="text/html",
    )
    previous_meta = {
        "document_id": document_id,
        "internal_document_id": "0000000000-25-000001",
        "accession_number": "0000000000-25-000001",
        "ingest_method": "download",
        "ticker": ticker,
        "company_id": "320193",
        "form_type": "10-K",
        "fiscal_year": 2024,
        "fiscal_period": "FY",
        "report_kind": None,
        "report_date": "2024-12-31",
        "filing_date": "2025-02-01",
        "first_ingested_at": "2025-02-02T00:00:00+00:00",
        "ingest_complete": True,
        "is_deleted": False,
        "deleted_at": None,
        "document_version": "v7",
        "source_fingerprint": "fingerprint_fixed",
        "amended": False,
        "download_version": "legacy_download_version",
        "legacy_field_to_remove": "legacy",
        "created_at": "2025-02-02T00:00:00+00:00",
        "updated_at": "2025-02-02T00:00:00+00:00",
        "files": [
            {
                "name": "sample-10k.htm",
                "uri": stored_file.uri,
                "etag": stored_file.etag,
                "last_modified": stored_file.last_modified,
                "size": stored_file.size,
                "content_type": stored_file.content_type,
                "sha256": stored_file.sha256,
                "source_url": "https://example.com/sample-10k.htm",
                "http_etag": "etag-v1",
                "http_last_modified": "Mon, 01 Jan 2025 00:00:00 GMT",
                "ingested_at": "2025-02-02T00:00:00+00:00",
            }
        ],
    }
    context.source_repository.update_source_document(
        SourceDocumentUpsertRequest(
            ticker=ticker,
            document_id=document_id,
            internal_document_id="0000000000-25-000001",
            form_type="10-K",
            primary_document="sample-10k.htm",
            meta=previous_meta,
            files=[stored_file],
        ),
        source_kind=SourceKind.FILING,
    )

    result = rebuild_single_local_filing(
        source_repository=context.source_repository,
        ticker=ticker,
        document_id=document_id,
        previous_meta=previous_meta,
        company_meta=None,
        pipeline_download_version=SEC_PIPELINE_DOWNLOAD_VERSION,
        overwrite_rebuilt_meta=overwrite_rebuilt_meta,
    )

    assert result["status"] == "downloaded"
    rebuilt_meta = context.source_repository.get_source_meta(ticker, document_id, SourceKind.FILING)
    assert rebuilt_meta["document_version"] == "v7"
    assert rebuilt_meta["download_version"] == SEC_PIPELINE_DOWNLOAD_VERSION
    assert rebuilt_meta["source_fingerprint"] == "fingerprint_fixed"
    assert "legacy_field_to_remove" not in rebuilt_meta
    manifest_path = tmp_path / "portfolio" / ticker / "filings" / "filing_manifest.json"
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest_payload["documents"]) == 1
    assert manifest_payload["documents"][0]["fiscal_year"] == 2024
    assert manifest_payload["documents"][0]["fiscal_period"] == "FY"


def test_rebuild_single_local_filing_clears_legacy_6k_fiscal_guess(tmp_path: Path) -> None:
    """6-K 重建在缺少同源 fiscal 证据时应清空历史猜测值。"""

    context = build_fs_storage_test_context(tmp_path)
    ticker = "FUTU"
    document_id = "fil_0001104659-26-026621"

    context.source_repository.create_source_document(
        SourceDocumentUpsertRequest(
            ticker=ticker,
            document_id=document_id,
            internal_document_id="0001104659-26-026621",
            form_type="6-K",
            primary_document="sample-6k.htm",
            meta={},
        ),
        source_kind=SourceKind.FILING,
    )
    handle = context.source_repository.get_source_handle(ticker, document_id, SourceKind.FILING)
    stored_file = context.blob_repository.store_file(
        handle=handle,
        filename="sample-6k.htm",
        data=BytesIO(b"<html>sample 6-k</html>"),
        content_type="text/html",
    )
    previous_meta = {
        "document_id": document_id,
        "internal_document_id": "0001104659-26-026621",
        "accession_number": "0001104659-26-026621",
        "ingest_method": "download",
        "ticker": ticker,
        "company_id": "1768375",
        "form_type": "6-K",
        "fiscal_year": 2026,
        "fiscal_period": "CY",
        "report_kind": None,
        "report_date": "2026-03-12",
        "filing_date": "2026-03-12",
        "first_ingested_at": "2026-03-13T00:00:00+00:00",
        "ingest_complete": True,
        "is_deleted": False,
        "deleted_at": None,
        "document_version": "v1",
        "source_fingerprint": "fingerprint_fixed",
        "amended": False,
        "download_version": "legacy_download_version",
        "created_at": "2026-03-13T00:00:00+00:00",
        "updated_at": "2026-03-13T00:00:00+00:00",
        "files": [
            {
                "name": "sample-6k.htm",
                "uri": stored_file.uri,
                "etag": stored_file.etag,
                "last_modified": stored_file.last_modified,
                "size": stored_file.size,
                "content_type": stored_file.content_type,
                "sha256": stored_file.sha256,
                "source_url": "https://example.com/sample-6k.htm",
                "http_etag": "etag-v1",
                "http_last_modified": "Mon, 12 Mar 2026 00:00:00 GMT",
                "ingested_at": "2026-03-13T00:00:00+00:00",
            }
        ],
    }
    context.source_repository.update_source_document(
        SourceDocumentUpsertRequest(
            ticker=ticker,
            document_id=document_id,
            internal_document_id="0001104659-26-026621",
            form_type="6-K",
            primary_document="sample-6k.htm",
            meta=previous_meta,
            files=[stored_file],
        ),
        source_kind=SourceKind.FILING,
    )

    result = rebuild_single_local_filing(
        source_repository=context.source_repository,
        ticker=ticker,
        document_id=document_id,
        previous_meta=previous_meta,
        company_meta=None,
        pipeline_download_version=SEC_PIPELINE_DOWNLOAD_VERSION,
        overwrite_rebuilt_meta=overwrite_rebuilt_meta,
    )

    assert result["status"] == "downloaded"
    rebuilt_meta = context.source_repository.get_source_meta(ticker, document_id, SourceKind.FILING)
    assert rebuilt_meta["fiscal_year"] is None
    assert rebuilt_meta["fiscal_period"] is None
    manifest_path = tmp_path / "portfolio" / ticker / "filings" / "filing_manifest.json"
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest_payload["documents"]) == 1
    assert manifest_payload["documents"][0]["fiscal_year"] is None
    assert manifest_payload["documents"][0]["fiscal_period"] is None


def test_rebuild_single_local_filing_clears_legacy_6ka_fiscal_guess(tmp_path: Path) -> None:
    """6-K/A 重建在缺少同源 fiscal 证据时也应清空历史猜测值。"""

    context = build_fs_storage_test_context(tmp_path)
    ticker = "FUTU"
    document_id = "fil_0001104659-26-026621a"

    context.source_repository.create_source_document(
        SourceDocumentUpsertRequest(
            ticker=ticker,
            document_id=document_id,
            internal_document_id="0001104659-26-026621a",
            form_type="6-K/A",
            primary_document="sample-6ka.htm",
            meta={},
        ),
        source_kind=SourceKind.FILING,
    )
    handle = context.source_repository.get_source_handle(ticker, document_id, SourceKind.FILING)
    stored_file = context.blob_repository.store_file(
        handle=handle,
        filename="sample-6ka.htm",
        data=BytesIO(b"<html>sample 6-k amendment</html>"),
        content_type="text/html",
    )
    previous_meta = {
        "document_id": document_id,
        "internal_document_id": "0001104659-26-026621a",
        "accession_number": "0001104659-26-026621a",
        "ingest_method": "download",
        "ticker": ticker,
        "company_id": "1768375",
        "form_type": "6-K/A",
        "fiscal_year": 2026,
        "fiscal_period": "CY",
        "report_kind": None,
        "report_date": "2026-03-12",
        "filing_date": "2026-03-12",
        "first_ingested_at": "2026-03-13T00:00:00+00:00",
        "ingest_complete": True,
        "is_deleted": False,
        "deleted_at": None,
        "document_version": "v1",
        "source_fingerprint": "fingerprint_fixed",
        "amended": True,
        "download_version": "legacy_download_version",
        "created_at": "2026-03-13T00:00:00+00:00",
        "updated_at": "2026-03-13T00:00:00+00:00",
        "files": [
            {
                "name": "sample-6ka.htm",
                "uri": stored_file.uri,
                "etag": stored_file.etag,
                "last_modified": stored_file.last_modified,
                "size": stored_file.size,
                "content_type": stored_file.content_type,
                "sha256": stored_file.sha256,
                "source_url": "https://example.com/sample-6ka.htm",
                "http_etag": "etag-v1",
                "http_last_modified": "Mon, 12 Mar 2026 00:00:00 GMT",
                "ingested_at": "2026-03-13T00:00:00+00:00",
            }
        ],
    }
    context.source_repository.update_source_document(
        SourceDocumentUpsertRequest(
            ticker=ticker,
            document_id=document_id,
            internal_document_id="0001104659-26-026621a",
            form_type="6-K/A",
            primary_document="sample-6ka.htm",
            meta=previous_meta,
            files=[stored_file],
        ),
        source_kind=SourceKind.FILING,
    )

    result = rebuild_single_local_filing(
        source_repository=context.source_repository,
        ticker=ticker,
        document_id=document_id,
        previous_meta=previous_meta,
        company_meta=None,
        pipeline_download_version=SEC_PIPELINE_DOWNLOAD_VERSION,
        overwrite_rebuilt_meta=overwrite_rebuilt_meta,
    )

    assert result["status"] == "downloaded"
    rebuilt_meta = context.source_repository.get_source_meta(ticker, document_id, SourceKind.FILING)
    assert rebuilt_meta["fiscal_year"] is None
    assert rebuilt_meta["fiscal_period"] is None
    manifest_path = tmp_path / "portfolio" / ticker / "filings" / "filing_manifest.json"
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest_payload["documents"]) == 1
    assert manifest_payload["documents"][0]["fiscal_year"] is None
    assert manifest_payload["documents"][0]["fiscal_period"] is None


def test_should_preserve_previous_rebuild_fiscal_fields_rejects_6k() -> None:
    """6-K 重建不应沿用 previous_meta 中的 fiscal 猜测值。"""

    assert _should_preserve_previous_rebuild_fiscal_fields("10-K") is True
    assert _should_preserve_previous_rebuild_fiscal_fields("6-K") is False
    assert _should_preserve_previous_rebuild_fiscal_fields("6K") is False
    assert _should_preserve_previous_rebuild_fiscal_fields("6-K/A") is False
