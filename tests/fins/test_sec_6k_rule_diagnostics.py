"""SEC 6-K 规则诊断模块测试。"""

from __future__ import annotations

import asyncio
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from alpha.fins.domain.document_models import (
    CompanyMeta,
    RejectedFilingArtifactUpsertRequest,
    SourceDocumentUpsertRequest,
    SourceFileEntry,
    now_iso8601,
)
from alpha.fins.domain.enums import SourceKind
from alpha.fins.sec_6k_rule_diagnostics import (
    FalsePositive6KSample,
    ProcessProgressUpdate,
    ProcessRunResult,
    _default_process_runner,
    _build_false_negative_evidence,
    _list_active_6k_document_ids,
    discover_twenty_f_tickers,
    run_sec_6k_rule_diagnostics,
)
from alpha.fins.pipelines.sec_pipeline import SEC_PIPELINE_DOWNLOAD_VERSION
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


def _create_source_document(
    context: FsStorageTestContext,
    *,
    ticker: str,
    document_id: str,
    form_type: str,
    primary_document: str,
    report_date: str | None = None,
) -> None:
    """创建测试 source 文档。

    Args:
        context: 存储上下文。
        ticker: 股票代码。
        document_id: 文档 ID。
        form_type: 表单类型。
        primary_document: 主文件名。
        report_date: 可选报告日期。

    Returns:
        无。

    Raises:
        OSError: 写入失败时抛出。
    """

    context.source_repository.create_source_document(
        SourceDocumentUpsertRequest(
            ticker=ticker,
            document_id=document_id,
            internal_document_id=document_id.replace("fil_", ""),
            form_type=form_type,
            primary_document=primary_document,
            meta={
                "form_type": form_type,
                "report_date": report_date,
                "is_deleted": False,
            },
        ),
        source_kind=SourceKind.FILING,
    )


def _attach_primary_source(
    context: FsStorageTestContext,
    *,
    ticker: str,
    document_id: str,
    filename: str,
    content: bytes,
) -> None:
    """为测试 source 文档补充主文件。

    Args:
        context: 存储上下文。
        ticker: 股票代码。
        document_id: 文档 ID。
        filename: 文件名。
        content: 文件内容。

    Returns:
        无。

    Raises:
        OSError: 写入失败时抛出。
    """

    handle = context.source_repository.get_source_handle(ticker, document_id, SourceKind.FILING)
    file_meta = context.blob_repository.store_file(
        handle=handle,
        filename=filename,
        data=BytesIO(content),
        content_type="text/html",
    )
    context.source_repository.update_source_document(
        SourceDocumentUpsertRequest(
            ticker=ticker,
            document_id=document_id,
            internal_document_id=document_id.replace("fil_", ""),
            form_type="6-K",
            primary_document=filename,
            meta={
                "form_type": "6-K",
                "report_date": "2025-03-31",
                "is_deleted": False,
            },
            files=[file_meta],
        ),
        source_kind=SourceKind.FILING,
    )


def _create_rejected_artifact(
    context: FsStorageTestContext,
    *,
    ticker: str,
    document_id: str,
    classification_version: str,
) -> None:
    """创建测试 rejected artifact。

    Args:
        context: 存储上下文。
        ticker: 股票代码。
        document_id: 文档 ID。
        classification_version: 规则版本。

    Returns:
        无。

    Raises:
        OSError: 写入失败时抛出。
    """

    file_meta = context.filing_maintenance_repository.store_rejected_filing_file(
        ticker=ticker,
        document_id=document_id,
        filename="reject.htm",
        data=BytesIO(b"Interim financial results for the six months ended June 30, 2025"),
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
            primary_document="reject.htm",
            selected_primary_document="reject.htm",
            rejection_reason="6k_filtered",
            rejection_category="NO_MATCH",
            classification_version=classification_version,
            source_fingerprint="fp",
            files=[
                SourceFileEntry(
                    name="reject.htm",
                    uri=file_meta.uri,
                    etag=file_meta.etag,
                    last_modified=file_meta.last_modified,
                    size=file_meta.size,
                    content_type=file_meta.content_type,
                    sha256=file_meta.sha256,
                )
            ],
        )
    )


@pytest.mark.unit
def test_discover_twenty_f_tickers_uses_active_filings(tmp_path: Path) -> None:
    """验证 20-F ticker 发现基于 active filings。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "AAA")
    _upsert_company(context, "BBB")
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_20f_a",
        form_type="20-F",
        primary_document="annual.htm",
        report_date="2024-12-31",
    )
    _create_source_document(
        context,
        ticker="BBB",
        document_id="fil_10k_b",
        form_type="10-K",
        primary_document="annual.htm",
        report_date="2024-12-31",
    )

    tickers = discover_twenty_f_tickers(
        company_repository=context.company_repository,
        source_repository=context.source_repository,
    )

    assert tickers == ["AAA"]


@pytest.mark.unit
def test_discover_twenty_f_tickers_skips_filing_dirs_missing_meta(tmp_path: Path) -> None:
    """验证 20-F ticker 发现会跳过缺失 meta.json 的坏目录。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "AAA")
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_20f_a",
        form_type="20-F",
        primary_document="annual.htm",
        report_date="2024-12-31",
    )
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_broken",
        form_type="6-K",
        primary_document="broken.htm",
        report_date="2025-03-31",
    )
    broken_meta_path = tmp_path / "portfolio" / "AAA" / "filings" / "fil_broken" / "meta.json"
    broken_meta_path.unlink()

    tickers = discover_twenty_f_tickers(
        company_repository=context.company_repository,
        source_repository=context.source_repository,
    )

    assert tickers == ["AAA"]


@pytest.mark.unit
def test_list_active_6k_document_ids_skips_filing_dirs_missing_meta(tmp_path: Path) -> None:
    """验证 active 6-K 列举会跳过缺失 meta.json 的坏目录。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "AAA")
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_6k_a",
        form_type="6-K",
        primary_document="q1.htm",
        report_date="2025-03-31",
    )
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_broken",
        form_type="6-K",
        primary_document="broken.htm",
        report_date="2025-06-30",
    )
    broken_meta_path = tmp_path / "portfolio" / "AAA" / "filings" / "fil_broken" / "meta.json"
    broken_meta_path.unlink()

    document_ids = _list_active_6k_document_ids(
        source_repository=context.source_repository,
        ticker="AAA",
    )

    assert document_ids == ["fil_6k_a"]


@pytest.mark.unit
def test_build_false_negative_evidence_excludes_hgf_and_old_rejections(tmp_path: Path) -> None:
    """验证 false negative 统计会排除 HGF filing，并忽略旧版本 reject。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "AAA")
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_20f_a",
        form_type="20-F",
        primary_document="annual.htm",
        report_date="2024-12-31",
    )
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_6k_1",
        form_type="6-K",
        primary_document="q1.htm",
        report_date="2025-03-31",
    )
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_6k_2",
        form_type="6-K",
        primary_document="q2.htm",
        report_date="2025-06-30",
    )
    _create_rejected_artifact(
        context,
        ticker="AAA",
        document_id="fil_rej_current",
        classification_version=SEC_PIPELINE_DOWNLOAD_VERSION,
    )
    _create_rejected_artifact(
        context,
        ticker="AAA",
        document_id="fil_rej_old",
        classification_version="sec_pipeline_download_v1.0.0",
    )

    evidence = _build_false_negative_evidence(
        twenty_f_tickers=["AAA"],
        source_repository=context.source_repository,
        maintenance_repository=context.filing_maintenance_repository,
        false_positive_samples=[
            FalsePositive6KSample(
                ticker="AAA",
                document_id="fil_6k_2",
                total_score=50.0,
                hard_gate_reasons=["HGF"],
                current_classification="NO_MATCH",
                head_text="Announcement from Example Holdings",
            )
        ],
    )

    assert len(evidence) == 1
    assert evidence[0].active_quarterly_count_excluding_hgf == 1
    assert evidence[0].excluded_hgf_document_ids == ["fil_6k_2"]
    assert [item.document_id for item in evidence[0].rejected_samples] == ["fil_rej_current"]


@pytest.mark.unit
def test_build_false_negative_evidence_ignores_rejected_artifacts_already_restored_active(
    tmp_path: Path,
) -> None:
    """验证 false negative 统计不会把已经 active 的同 document_id rejected artifact 再算一遍。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "AAA")
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_20f_a",
        form_type="20-F",
        primary_document="annual.htm",
        report_date="2024-12-31",
    )
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_6k_active",
        form_type="6-K",
        primary_document="q1.htm",
        report_date="2025-03-31",
    )
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_6k_other",
        form_type="6-K",
        primary_document="q2.htm",
        report_date="2025-06-30",
    )
    _create_rejected_artifact(
        context,
        ticker="AAA",
        document_id="fil_6k_active",
        classification_version=SEC_PIPELINE_DOWNLOAD_VERSION,
    )
    _create_rejected_artifact(
        context,
        ticker="AAA",
        document_id="fil_rej_current",
        classification_version=SEC_PIPELINE_DOWNLOAD_VERSION,
    )

    evidence = _build_false_negative_evidence(
        twenty_f_tickers=["AAA"],
        source_repository=context.source_repository,
        maintenance_repository=context.filing_maintenance_repository,
        false_positive_samples=[],
    )

    assert len(evidence) == 1
    assert evidence[0].active_quarterly_document_ids == ["fil_6k_active", "fil_6k_other"]
    assert [item.document_id for item in evidence[0].rejected_samples] == ["fil_rej_current"]


@pytest.mark.unit
def test_build_false_negative_evidence_keeps_non_hgf_hard_gate_failures(tmp_path: Path) -> None:
    """验证 false negative 统计不会把非 HGF hard-gate 失败排除出 active 计数。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "AAA")
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_20f_a",
        form_type="20-F",
        primary_document="annual.htm",
        report_date="2024-12-31",
    )
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_6k_1",
        form_type="6-K",
        primary_document="q1.htm",
        report_date="2025-03-31",
    )
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_6k_2",
        form_type="6-K",
        primary_document="q2.htm",
        report_date="2025-06-30",
    )
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_6k_3",
        form_type="6-K",
        primary_document="q3.htm",
        report_date="2025-09-30",
    )

    evidence = _build_false_negative_evidence(
        twenty_f_tickers=["AAA"],
        source_repository=context.source_repository,
        maintenance_repository=context.filing_maintenance_repository,
        false_positive_samples=[
            FalsePositive6KSample(
                ticker="AAA",
                document_id="fil_6k_3",
                total_score=55.0,
                hard_gate_reasons=["D3 fail"],
                current_classification="RESULTS_RELEASE",
                head_text="Quarterly results",
            )
        ],
    )

    assert evidence == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_default_process_runner_passes_workspace_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证默认 process runner 会把 workspace_root 透传给 CLI。"""

    captured: dict[str, object] = {}

    class _FakeProcess:
        """最小子进程桩。"""

        def __init__(self) -> None:
            self.returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            """返回固定输出。"""

            return (b"ok", b"")

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> _FakeProcess:
        """记录 CLI 命令行参数。"""

        captured["command"] = list(command)
        captured["cwd"] = kwargs.get("cwd")
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = tmp_path / "custom-workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)

    result = await _default_process_runner(
        workspace_root=workspace_root,
        log_dir=log_dir,
        ticker="AAA",
        document_ids=["fil_001", "fil_002"],
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--base" in command
    assert str(workspace_root) == command[command.index("--base") + 1]
    assert result.return_code == 0
    assert Path(result.log_path).read_text(encoding="utf-8") == "ok"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_sec_6k_rule_diagnostics_writes_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证诊断入口会写出约定输出文件。"""

    context = build_fs_storage_test_context(tmp_path)
    _upsert_company(context, "AAA")
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_20f_a",
        form_type="20-F",
        primary_document="annual.htm",
        report_date="2024-12-31",
    )
    _create_source_document(
        context,
        ticker="AAA",
        document_id="fil_6k_a",
        form_type="6-K",
        primary_document="primary.htm",
        report_date="2025-03-31",
    )
    _attach_primary_source(
        context,
        ticker="AAA",
        document_id="fil_6k_a",
        filename="primary.htm",
        content=b"Announcement from Example Holdings",
    )
    reported_updates: list[ProcessProgressUpdate] = []

    async def fake_runner(
        workspace_root: Path,
        log_dir: Path,
        ticker: str,
        document_ids: list[str],
    ) -> ProcessRunResult:
        assert workspace_root == tmp_path
        log_path = log_dir / f"{ticker}.log"
        log_path.write_text("ok", encoding="utf-8")
        return ProcessRunResult(
            ticker=ticker,
            document_ids=document_ids,
            return_code=0,
            log_path=str(log_path),
        )

    monkeypatch.setattr(
        "alpha.fins.sec_6k_rule_diagnostics.score_batch",
        lambda **kwargs: SimpleNamespace(
            documents=[
                SimpleNamespace(
                    ticker="AAA",
                    document_id="fil_6k_a",
                    total_score=55.0,
                    hard_gate=SimpleNamespace(passed=False, reasons=["D3 fail"]),
                )
            ]
        ),
    )

    output_dir = tmp_path / "tmp" / "diag"
    report = await run_sec_6k_rule_diagnostics(
        workspace_root=tmp_path,
        output_dir=output_dir,
        max_concurrency=2,
        process_runner=fake_runner,
        progress_reporter=reported_updates.append,
    )

    assert report.twenty_f_tickers == ["AAA"]
    assert report.process_runs[0].document_ids == ["fil_6k_a"]
    assert [item.phase for item in reported_updates] == ["started", "completed"]
    assert reported_updates[0].document_ids == ["fil_6k_a"]
    assert (output_dir / "summary.json").exists()
    assert (output_dir / "summary.md").exists()
    assert (output_dir / "false_positive_6k.json").exists()
    assert (output_dir / "false_negative_6k.json").exists()
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["twenty_f_ticker_count"] == 1
    assert summary["false_positive_6k_count"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_sec_6k_rule_diagnostics_can_limit_target_tickers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证诊断入口支持只运行指定 ticker 子集。"""

    context = build_fs_storage_test_context(tmp_path)
    for ticker in ("AAA", "BBB"):
        _upsert_company(context, ticker)
        _create_source_document(
            context,
            ticker=ticker,
            document_id=f"fil_20f_{ticker.lower()}",
            form_type="20-F",
            primary_document="annual.htm",
            report_date="2024-12-31",
        )
        _create_source_document(
            context,
            ticker=ticker,
            document_id=f"fil_6k_{ticker.lower()}",
            form_type="6-K",
            primary_document="primary.htm",
            report_date="2025-03-31",
        )
        _attach_primary_source(
            context,
            ticker=ticker,
            document_id=f"fil_6k_{ticker.lower()}",
            filename="primary.htm",
            content=b"Announcement from Example Holdings",
        )

    observed_process_tickers: list[str] = []
    observed_score_tickers: list[str] = []

    async def fake_runner(
        workspace_root: Path,
        log_dir: Path,
        ticker: str,
        document_ids: list[str],
    ) -> ProcessRunResult:
        del workspace_root
        log_path = log_dir / f"{ticker}.log"
        log_path.write_text("ok", encoding="utf-8")
        observed_process_tickers.append(ticker)
        return ProcessRunResult(
            ticker=ticker,
            document_ids=document_ids,
            return_code=0,
            log_path=str(log_path),
        )

    def fake_score_batch(**kwargs: object) -> SimpleNamespace:
        observed_score_tickers.extend(cast(list[str], kwargs["tickers"]))
        return SimpleNamespace(
            documents=[
                SimpleNamespace(
                    ticker="BBB",
                    document_id="fil_6k_bbb",
                    total_score=55.0,
                    hard_gate=SimpleNamespace(passed=False, reasons=["D3 fail"]),
                )
            ]
        )

    monkeypatch.setattr(
        "alpha.fins.sec_6k_rule_diagnostics.score_batch",
        fake_score_batch,
    )

    report = await run_sec_6k_rule_diagnostics(
        workspace_root=tmp_path,
        output_dir=tmp_path / "tmp" / "diag_subset",
        max_concurrency=2,
        target_tickers=["bbb"],
        process_runner=fake_runner,
    )

    assert report.twenty_f_tickers == ["BBB"]
    assert observed_process_tickers == ["BBB"]
    assert observed_score_tickers == ["BBB"]
    assert [sample.ticker for sample in report.false_positive_6k] == ["BBB"]
