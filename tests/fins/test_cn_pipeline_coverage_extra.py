"""CnPipeline 补充覆盖测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pytest

from alpha.engine.processors.processor_registry import ProcessorRegistry
from alpha.fins.domain.enums import SourceKind
from alpha.fins.pipelines import cn_pipeline as module
from alpha.fins.pipelines.tool_snapshot_export import TOOL_SNAPSHOT_META_FILE_NAME


@pytest.mark.unit
def test_cn_pipeline_requires_processor_registry() -> None:
    """覆盖 __init__ 对 processor_registry 的必填校验。"""

    with pytest.raises(ValueError, match="processor_registry"):
        module.CnPipeline(processor_registry=None)  # type: ignore[arg-type]


@pytest.mark.unit
def test_cn_pipeline_wrappers_and_process_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """覆盖 upload 包装器与 process 的 missing/incomplete/deleted/failed 分支。"""

    pipeline = module.CnPipeline(
        processor_registry=ProcessorRegistry(),
        workspace_root=tmp_path,
    )

    monkeypatch.setattr(module, "_run_async_pipeline_sync", lambda coro: {"status": "ok"})
    monkeypatch.setattr(module, "_collect_upload_result_from_events", lambda stream, stream_name: "coro")

    assert pipeline.upload_filing(
        ticker="000001",
        action="create",
        files=[],
        fiscal_year=2025,
        fiscal_period="FY",
    )["status"] == "ok"
    assert pipeline.upload_material(
        ticker="000001",
        action="create",
        form_type="MATERIAL_OTHER",
        material_name="Deck",
        files=[],
    )["status"] == "ok"

    monkeypatch.setattr(module, "_log_process_document_result_common", lambda **kwargs: None)
    meta_by_document_id: dict[str, dict[str, Any]] = {
        "f_incomplete": {"ingest_complete": False, "form_type": "FY", "fiscal_year": 2025},
        "f_deleted": {"ingest_complete": True, "is_deleted": True, "form_type": "FY", "fiscal_year": 2025},
        "f_error": {"ingest_complete": True, "is_deleted": False, "form_type": "FY", "fiscal_year": 2025},
        "m_incomplete": {"ingest_complete": False, "form_type": "MATERIAL", "fiscal_year": 2025},
        "m_deleted": {"ingest_complete": True, "is_deleted": True, "form_type": "MATERIAL", "fiscal_year": 2025},
        "m_error": {"ingest_complete": True, "is_deleted": False, "form_type": "MATERIAL", "fiscal_year": 2025},
    }

    def _fake_process_filing(**kwargs: Any) -> dict[str, Any]:
        if kwargs["document_id"] == "f_error":
            raise RuntimeError("filing boom")
        return {"document_id": kwargs["document_id"], "status": "processed"}

    def _fake_process_material(**kwargs: Any) -> dict[str, Any]:
        if kwargs["document_id"] == "m_error":
            raise RuntimeError("material boom")
        return {"document_id": kwargs["document_id"], "status": "processed"}

    monkeypatch.setattr(pipeline, "process_filing", _fake_process_filing)
    monkeypatch.setattr(pipeline, "process_material", _fake_process_material)
    monkeypatch.setattr(
        pipeline._source_repository,
        "list_source_document_ids",
        lambda ticker, source_kind: (
            ["f_missing", "f_incomplete", "f_deleted", "f_error"]
            if source_kind == SourceKind.FILING
            else ["m_missing", "m_incomplete", "m_deleted", "m_error"]
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_safe_get_document_meta",
        lambda ticker, document_id, source_kind: meta_by_document_id.get(document_id),
    )

    result = pipeline.process("000001", overwrite=False, ci=False)

    filing_statuses = {item["document_id"]: item["status"] for item in result["filings"]}
    material_statuses = {item["document_id"]: item["status"] for item in result["materials"]}
    assert filing_statuses["f_missing"] == "skipped"
    assert filing_statuses["f_incomplete"] == "skipped"
    assert filing_statuses["f_deleted"] == "skipped"
    assert filing_statuses["f_error"] == "failed"
    assert material_statuses["m_missing"] == "skipped"
    assert material_statuses["m_incomplete"] == "skipped"
    assert material_statuses["m_deleted"] == "skipped"
    assert material_statuses["m_error"] == "failed"


@pytest.mark.unit
def test_cn_pipeline_snapshot_skip_and_cleanup_helpers(tmp_path: Path) -> None:
    """覆盖 snapshot 版本判定、目录匹配、清理与 meta 读取分支。"""

    pipeline = module.CnPipeline(
        processor_registry=ProcessorRegistry(),
        workspace_root=tmp_path,
    )

    base_source_meta = {"document_version": "v1", "source_fingerprint": "fp"}
    snapshot_meta = {
        "snapshot_schema_version": module.TOOL_SNAPSHOT_SCHEMA_VERSION,
        "source_document_version": "v1",
        "source_fingerprint": "fp",
        "parser_signature": "sig",
        "expected_parser_signature": "sig",
    }

    assert pipeline._can_skip_snapshot_export(
        source_meta=base_source_meta,
        snapshot_meta=snapshot_meta,
        overwrite=True,
        expected_parser_signature="sig",
        ci=False,
        ticker="AAPL",
        document_id="d1",
    ) is False

    assert pipeline._can_skip_snapshot_export(
        source_meta=base_source_meta,
        snapshot_meta={**snapshot_meta, "snapshot_schema_version": "bad"},
        overwrite=False,
        expected_parser_signature="sig",
        ci=False,
        ticker="AAPL",
        document_id="d1",
    ) is False
    assert pipeline._can_skip_snapshot_export(
        source_meta={"document_version": "v2", "source_fingerprint": "fp"},
        snapshot_meta=snapshot_meta,
        overwrite=False,
        expected_parser_signature="sig",
        ci=False,
        ticker="AAPL",
        document_id="d1",
    ) is False
    assert pipeline._can_skip_snapshot_export(
        source_meta={"document_version": "v1", "source_fingerprint": "fp2"},
        snapshot_meta=snapshot_meta,
        overwrite=False,
        expected_parser_signature="sig",
        ci=False,
        ticker="AAPL",
        document_id="d1",
    ) is False
    assert pipeline._can_skip_snapshot_export(
        source_meta=base_source_meta,
        snapshot_meta={**snapshot_meta, "expected_parser_signature": "other"},
        overwrite=False,
        expected_parser_signature="sig",
        ci=False,
        ticker="AAPL",
        document_id="d1",
    ) is False

    snapshot_dir = tmp_path / "portfolio" / "AAPL" / "processed" / "d1"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    assert pipeline._match_snapshot_files(ticker="AAPL", document_id="d1", ci=False) is False

    expected_files = module.build_snapshot_file_names(ci=False)
    for name in expected_files:
        (snapshot_dir / name).write_text("{}", encoding="utf-8")
    assert pipeline._match_snapshot_files(ticker="AAPL", document_id="d1", ci=False) is True

    (snapshot_dir / "nested").mkdir()
    assert pipeline._match_snapshot_files(ticker="AAPL", document_id="d1", ci=False) is False

    nested_dir = snapshot_dir / "nested2"
    nested_dir.mkdir(exist_ok=True)
    extra_file = snapshot_dir / "other.json"
    extra_file.write_text("x", encoding="utf-8")
    pipeline._cleanup_processed_snapshot_dir(
        ticker="AAPL",
        document_id="d1",
        allowed_files={expected_files[0]},
    )
    assert not nested_dir.exists()
    assert not extra_file.exists()

    meta_path = snapshot_dir / TOOL_SNAPSHOT_META_FILE_NAME
    meta_path.write_text("not-json", encoding="utf-8")
    assert pipeline._safe_read_snapshot_meta(ticker="AAPL", document_id="d1") is None
    meta_path.write_text("[]", encoding="utf-8")
    assert pipeline._safe_read_snapshot_meta(ticker="AAPL", document_id="d1") is None
