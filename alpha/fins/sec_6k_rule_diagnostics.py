"""SEC 6-K 规则诊断闭环。

该模块负责围绕 6-K 预筛选规则构建可复用的工程化闭环：
- 发现当前 workspace active filings 中存在 20-F 的 ticker
- 仅对 active `6-K` 文档并发重跑 `process --ci --overwrite`
- 基于 6-K CI 评分提取 hard-gate fail 样本
- 结合 `.rejections/` 中的 reject artifact 提取季报误 reject 样本
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import sys
from typing import Awaitable, Callable, Literal, Optional

from alpha.fins.domain.document_models import DocumentMeta, RejectedFilingArtifact
from alpha.fins.domain.enums import SourceKind
from alpha.fins.pipelines.sec_6k_rules import _classify_6k_text, _extract_head_text
from alpha.fins.pipelines.sec_pipeline import SEC_PIPELINE_DOWNLOAD_VERSION
from alpha.fins.score_sec_ci import ScoreConfig, score_batch
from alpha.fins.storage import (
    CompanyMetaRepositoryProtocol,
    FilingMaintenanceRepositoryProtocol,
    FsCompanyMetaRepository,
    FsFilingMaintenanceRepository,
    FsSourceDocumentRepository,
    SourceDocumentRepositoryProtocol,
)

DEFAULT_MAX_CONCURRENCY = 26
DEFAULT_OUTPUT_DIRNAME = "sec_6k_rule_diagnostics"


@dataclass(frozen=True, slots=True)
class ProcessRunResult:
    """单个 ticker 的 process 执行结果。"""

    ticker: str
    document_ids: list[str]
    return_code: int
    log_path: str


@dataclass(frozen=True, slots=True)
class ProcessProgressUpdate:
    """单个 ticker 的 process 进度更新。"""

    ticker: str
    document_ids: list[str]
    phase: Literal["started", "completed"]
    return_code: Optional[int] = None
    log_path: Optional[str] = None


@dataclass(frozen=True, slots=True)
class FalsePositive6KSample:
    """非季报误落盘样本。"""

    ticker: str
    document_id: str
    total_score: float
    hard_gate_reasons: list[str]
    current_classification: str
    head_text: str


@dataclass(frozen=True, slots=True)
class Rejected6KSample:
    """季报误 reject 的 rejected artifact 样本。"""

    document_id: str
    rejection_reason: str
    rejection_category: str
    classification_version: str
    selected_primary_document: str
    current_classification: str
    head_text: str


@dataclass(frozen=True, slots=True)
class FalseNegative6KTickerEvidence:
    """季报误 reject 的 ticker 级证据。"""

    ticker: str
    active_quarterly_count_excluding_hgf: int
    excluded_hgf_document_ids: list[str]
    active_quarterly_document_ids: list[str]
    rejected_samples: list[Rejected6KSample]


@dataclass(frozen=True, slots=True)
class Sec6KRuleDiagnosticsReport:
    """6-K 规则诊断结果。"""

    workspace_root: str
    process_concurrency: int
    twenty_f_tickers: list[str]
    process_runs: list[ProcessRunResult] = field(default_factory=list)
    false_positive_6k: list[FalsePositive6KSample] = field(default_factory=list)
    false_negative_6k: list[FalseNegative6KTickerEvidence] = field(default_factory=list)


ProcessRunner = Callable[[Path, Path, str, list[str]], Awaitable[ProcessRunResult]]
ProcessProgressReporter = Callable[[ProcessProgressUpdate], None]


async def run_sec_6k_rule_diagnostics(
    *,
    workspace_root: Path,
    output_dir: Optional[Path] = None,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    target_tickers: Optional[list[str]] = None,
    process_runner: Optional[ProcessRunner] = None,
    progress_reporter: Optional[ProcessProgressReporter] = None,
) -> Sec6KRuleDiagnosticsReport:
    """执行 6-K 规则诊断闭环。

    Args:
        workspace_root: workspace 根目录。
        output_dir: 可选输出目录；默认写入 `workspace/tmp/sec_6k_rule_diagnostics/`。
        max_concurrency: `process --ci` 最大并发数。
        target_tickers: 可选 ticker 子集；仅对该集合与 20-F ticker 的交集执行诊断。
        process_runner: 可选 process 执行器，便于测试替换。
        progress_reporter: 可选进度回调；用于实时上报每个 ticker 的开始/结束。

    Returns:
        诊断报告对象。

    Raises:
        OSError: 输出目录创建或报告写入失败时抛出。
    """

    resolved_workspace_root = workspace_root.resolve()
    resolved_output_dir = (
        output_dir.resolve()
        if output_dir is not None
        else resolved_workspace_root / "tmp" / DEFAULT_OUTPUT_DIRNAME
    )
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    company_repository = FsCompanyMetaRepository(resolved_workspace_root)
    source_repository = FsSourceDocumentRepository(resolved_workspace_root)
    maintenance_repository = FsFilingMaintenanceRepository(resolved_workspace_root)

    twenty_f_tickers = discover_twenty_f_tickers(
        company_repository=company_repository,
        source_repository=source_repository,
    )
    if target_tickers is not None:
        requested_tickers = {
            ticker.strip().upper()
            for ticker in target_tickers
            if ticker.strip()
        }
        twenty_f_tickers = [
            ticker
            for ticker in twenty_f_tickers
            if ticker.strip().upper() in requested_tickers
        ]
    active_6k_document_ids_by_ticker = {
        ticker: _list_active_6k_document_ids(
            source_repository=source_repository,
            ticker=ticker,
        )
        for ticker in twenty_f_tickers
    }
    runner = process_runner or _default_process_runner
    process_runs = await _run_process_ci_for_tickers(
        workspace_root=resolved_workspace_root,
        output_dir=resolved_output_dir,
        ticker_document_ids={
            ticker: document_ids
            for ticker, document_ids in active_6k_document_ids_by_ticker.items()
            if document_ids
        },
        max_concurrency=max_concurrency,
        runner=runner,
        progress_reporter=progress_reporter,
    )

    batch = score_batch(
        base=str(resolved_workspace_root),
        tickers=twenty_f_tickers,
        cfg=ScoreConfig(),
        form_type="6-K",
    )
    false_positive_6k = _build_false_positive_samples(
        batch=batch,
        source_repository=source_repository,
    )
    false_negative_6k = _build_false_negative_evidence(
        twenty_f_tickers=twenty_f_tickers,
        source_repository=source_repository,
        maintenance_repository=maintenance_repository,
        false_positive_samples=false_positive_6k,
    )

    report = Sec6KRuleDiagnosticsReport(
        workspace_root=str(resolved_workspace_root),
        process_concurrency=max_concurrency,
        twenty_f_tickers=twenty_f_tickers,
        process_runs=process_runs,
        false_positive_6k=false_positive_6k,
        false_negative_6k=false_negative_6k,
    )
    _write_diagnostics_outputs(resolved_output_dir, report)
    return report


def discover_twenty_f_tickers(
    *,
    company_repository: CompanyMetaRepositoryProtocol,
    source_repository: SourceDocumentRepositoryProtocol,
) -> list[str]:
    """发现当前 active filings 中拥有 20-F 的 ticker。

    Args:
        company_repository: 公司级元数据仓储。
        source_repository: 源文档仓储。

    Returns:
        按字母序排序的 ticker 列表。

    Raises:
        OSError: 仓储读取失败时抛出。
        ValueError: 元数据内容非法时抛出。
    """

    tickers: list[str] = []
    for entry in company_repository.scan_company_meta_inventory():
        if entry.status != "available" or entry.company_meta is None:
            continue
        ticker = entry.company_meta.ticker
        for document_id in source_repository.list_source_document_ids(ticker, SourceKind.FILING):
            meta = _get_source_meta_if_present(
                source_repository=source_repository,
                ticker=ticker,
                document_id=document_id,
            )
            if meta is None:
                continue
            if bool(meta.get("is_deleted", False)):
                continue
            if str(meta.get("form_type", "")).strip().upper() == "20-F":
                tickers.append(ticker)
                break
    return sorted(set(tickers))


async def _run_process_ci_for_tickers(
    *,
    workspace_root: Path,
    output_dir: Path,
    ticker_document_ids: dict[str, list[str]],
    max_concurrency: int,
    runner: ProcessRunner,
    progress_reporter: Optional[ProcessProgressReporter] = None,
) -> list[ProcessRunResult]:
    """并发执行仅针对 active `6-K` 的 `process --ci --overwrite`。

    Args:
        workspace_root: workspace 根目录。
        output_dir: 输出目录。
        ticker_document_ids: ticker 到 active `6-K` document_ids 的映射。
        max_concurrency: 最大并发数。
        runner: 单 ticker 执行器。
        progress_reporter: 可选进度回调。

    Returns:
        执行结果列表。

    Raises:
        OSError: 日志目录创建失败时抛出。
    """

    log_dir = output_dir / "process_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _run_single(ticker: str, document_ids: list[str]) -> ProcessRunResult:
        """在并发限制内执行单个 ticker。"""

        async with semaphore:
            if progress_reporter is not None:
                progress_reporter(
                    ProcessProgressUpdate(
                        ticker=ticker,
                        document_ids=document_ids,
                        phase="started",
                    )
                )
            try:
                result = await runner(workspace_root, log_dir, ticker, document_ids)
            except Exception as exc:
                log_path = log_dir / f"{ticker}.log"
                log_path.write_text(str(exc), encoding="utf-8")
                result = ProcessRunResult(
                    ticker=ticker,
                    document_ids=list(document_ids),
                    return_code=1,
                    log_path=str(log_path),
                )
            if progress_reporter is not None:
                progress_reporter(
                    ProcessProgressUpdate(
                        ticker=ticker,
                        document_ids=result.document_ids,
                        phase="completed",
                        return_code=result.return_code,
                        log_path=result.log_path,
                    )
                )
            return result

    tasks = [
        _run_single(ticker, list(document_ids))
        for ticker, document_ids in sorted(ticker_document_ids.items())
    ]
    return await asyncio.gather(*tasks)


async def _default_process_runner(
    workspace_root: Path,
    log_dir: Path,
    ticker: str,
    document_ids: list[str],
) -> ProcessRunResult:
    """默认的 `process --ci --overwrite` 执行器。

    Args:
        workspace_root: workspace 根目录。
        log_dir: 日志目录。
        ticker: 股票代码。
        document_ids: 仅需重跑的文档 ID 列表。

    Returns:
        执行结果。

    Raises:
        OSError: 子进程启动或日志写入失败时抛出。
    """

    command = [
        sys.executable,
        "-m",
        "alpha.cli",
        "process",
        "--ci",
        "--overwrite",
        "--base",
        str(workspace_root),
        "--ticker",
        ticker,
    ]
    for document_id in document_ids:
        command.extend(["--document-id", document_id])
    project_root = Path(__file__).resolve().parents[2]
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(project_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await process.communicate()
    log_path = log_dir / f"{ticker}.log"
    log_path.write_text(stdout.decode("utf-8", errors="ignore"), encoding="utf-8")
    return ProcessRunResult(
        ticker=ticker,
        document_ids=list(document_ids),
        return_code=int(process.returncode or 0),
        log_path=str(log_path),
    )


def _build_false_positive_samples(
    *,
    batch: object,
    source_repository: SourceDocumentRepositoryProtocol,
) -> list[FalsePositive6KSample]:
    """构建 6-K 非季报误落盘样本。

    Args:
        batch: `score_batch()` 返回对象。
        source_repository: 源文档仓储。

    Returns:
        false positive 样本列表。

    Raises:
        OSError: 仓储读取失败时抛出。
        ValueError: 元数据内容非法时抛出。
    """

    documents = list(getattr(batch, "documents", []))
    samples: list[FalsePositive6KSample] = []
    for document in documents:
        hard_gate = getattr(document, "hard_gate", None)
        if hard_gate is None or bool(getattr(hard_gate, "passed", True)):
            continue
        ticker = str(getattr(document, "ticker", "")).strip()
        document_id = str(getattr(document, "document_id", "")).strip()
        head_text = _read_active_filing_head_text(
            source_repository=source_repository,
            ticker=ticker,
            document_id=document_id,
        )
        samples.append(
            FalsePositive6KSample(
                ticker=ticker,
                document_id=document_id,
                total_score=float(getattr(document, "total_score", 0.0)),
                hard_gate_reasons=[
                    str(item)
                    for item in list(getattr(hard_gate, "reasons", []))
                    if str(item).strip()
                ],
                current_classification=_classify_6k_text(head_text),
                head_text=head_text,
            )
        )
    samples.sort(key=lambda item: (item.ticker, item.document_id))
    return samples


def _build_false_negative_evidence(
    *,
    twenty_f_tickers: list[str],
    source_repository: SourceDocumentRepositoryProtocol,
    maintenance_repository: FilingMaintenanceRepositoryProtocol,
    false_positive_samples: list[FalsePositive6KSample],
) -> list[FalseNegative6KTickerEvidence]:
    """构建季报误 reject 证据。

    Args:
        twenty_f_tickers: 20-F ticker 列表。
        source_repository: 源文档仓储。
        maintenance_repository: filing 维护治理仓储。
        false_positive_samples: false positive 样本列表。

    Returns:
        false negative ticker 级证据列表。

    Raises:
        OSError: 仓储读取失败时抛出。
        ValueError: 元数据内容非法时抛出。
    """

    hgf_by_ticker: dict[str, set[str]] = {}
    for sample in false_positive_samples:
        if not _is_hgf_false_positive_sample(sample):
            continue
        hgf_by_ticker.setdefault(sample.ticker, set()).add(sample.document_id)

    results: list[FalseNegative6KTickerEvidence] = []
    for ticker in twenty_f_tickers:
        active_quarterly_document_ids = _list_active_6k_document_ids(
            source_repository=source_repository,
            ticker=ticker,
        )
        active_quarterly_document_id_set = set(active_quarterly_document_ids)
        excluded_hgf_document_ids = sorted(hgf_by_ticker.get(ticker, set()))
        effective_document_ids = [
            document_id
            for document_id in active_quarterly_document_ids
            if document_id not in hgf_by_ticker.get(ticker, set())
        ]
        if len(effective_document_ids) >= 3:
            continue
        rejected_samples: list[Rejected6KSample] = []
        for artifact in maintenance_repository.list_rejected_filing_artifacts(ticker):
            if artifact.form_type != "6-K":
                continue
            if artifact.classification_version != SEC_PIPELINE_DOWNLOAD_VERSION:
                continue
            if artifact.document_id in active_quarterly_document_id_set:
                continue
            head_text = _read_rejected_filing_head_text(
                maintenance_repository=maintenance_repository,
                artifact=artifact,
            )
            rejected_samples.append(
                Rejected6KSample(
                    document_id=artifact.document_id,
                    rejection_reason=artifact.rejection_reason,
                    rejection_category=artifact.rejection_category,
                    classification_version=artifact.classification_version,
                    selected_primary_document=artifact.selected_primary_document,
                    current_classification=_classify_6k_text(head_text),
                    head_text=head_text,
                )
            )
        rejected_samples.sort(key=lambda item: item.document_id)
        results.append(
            FalseNegative6KTickerEvidence(
                ticker=ticker,
                active_quarterly_count_excluding_hgf=len(effective_document_ids),
                excluded_hgf_document_ids=excluded_hgf_document_ids,
                active_quarterly_document_ids=sorted(active_quarterly_document_ids),
                rejected_samples=rejected_samples,
            )
        )
    results.sort(key=lambda item: item.ticker)
    return results


def _is_hgf_false_positive_sample(sample: FalsePositive6KSample) -> bool:
    """判断 false positive 样本是否属于 HGF filing。

    Args:
        sample: false positive 6-K 样本。

    Returns:
        当前样本的硬门禁原因中明确包含 `HGF` 时返回 `True`，否则返回 `False`。

    Raises:
        无。
    """

    for reason in sample.hard_gate_reasons:
        if "HGF" in str(reason).upper():
            return True
    return False


def _get_source_meta_if_present(
    *,
    source_repository: SourceDocumentRepositoryProtocol,
    ticker: str,
    document_id: str,
) -> Optional[DocumentMeta]:
    """安全读取 source 文档元数据。

    6-K 规则诊断需要遍历 active filing 目录，但工作区里可能残留
    “目录存在、meta.json 缺失”的坏样本。诊断闭环需要跳过这类目录，
    避免单个脏数据阻断整批样本分析。

    Args:
        source_repository: 源文档仓储。
        ticker: 股票代码。
        document_id: 文档 ID。

    Returns:
        成功读取时返回源文档元数据；若 `meta.json` 缺失则返回 `None`。

    Raises:
        OSError: 仓储读取失败时抛出。
        ValueError: 元数据内容非法时抛出。
    """

    try:
        return source_repository.get_source_meta(ticker, document_id, SourceKind.FILING)
    except FileNotFoundError:
        return None


def _list_active_6k_document_ids(
    *,
    source_repository: SourceDocumentRepositoryProtocol,
    ticker: str,
) -> list[str]:
    """列出 active 6-K 文档 ID。

    Args:
        source_repository: 源文档仓储。
        ticker: 股票代码。

    Returns:
        active 6-K 文档 ID 列表。

    Raises:
        OSError: 仓储读取失败时抛出。
        ValueError: 元数据内容非法时抛出。
    """

    result: list[str] = []
    for document_id in source_repository.list_source_document_ids(ticker, SourceKind.FILING):
        meta = _get_source_meta_if_present(
            source_repository=source_repository,
            ticker=ticker,
            document_id=document_id,
        )
        if meta is None:
            continue
        if bool(meta.get("is_deleted", False)):
            continue
        if str(meta.get("form_type", "")).strip().upper() != "6-K":
            continue
        result.append(document_id)
    result.sort()
    return result


def _read_active_filing_head_text(
    *,
    source_repository: SourceDocumentRepositoryProtocol,
    ticker: str,
    document_id: str,
) -> str:
    """读取 active filing 的头部文本。

    Args:
        source_repository: 源文档仓储。
        ticker: 股票代码。
        document_id: 文档 ID。

    Returns:
        头部文本；读取失败时返回空字符串。

    Raises:
        无。
    """

    try:
        source = source_repository.get_primary_source(ticker, document_id, SourceKind.FILING)
    except (FileNotFoundError, ValueError, OSError):
        return ""
    with source.open() as stream:
        return _extract_head_text(stream.read(), max_lines=120)


def _read_rejected_filing_head_text(
    *,
    maintenance_repository: FilingMaintenanceRepositoryProtocol,
    artifact: RejectedFilingArtifact,
) -> str:
    """读取 rejected filing 的头部文本。

    Args:
        maintenance_repository: filing 维护治理仓储。
        artifact: rejected artifact。

    Returns:
        头部文本；读取失败时返回空字符串。

    Raises:
        无。
    """

    candidate_names = [
        artifact.selected_primary_document,
        artifact.primary_document,
    ]
    if not candidate_names:
        return ""
    for filename in candidate_names:
        normalized = str(filename).strip()
        if not normalized:
            continue
        try:
            payload = maintenance_repository.read_rejected_filing_file_bytes(
                ticker=artifact.ticker,
                document_id=artifact.document_id,
                filename=normalized,
            )
        except (FileNotFoundError, ValueError, OSError):
            continue
        return _extract_head_text(payload, max_lines=120)
    return ""


def _write_diagnostics_outputs(output_dir: Path, report: Sec6KRuleDiagnosticsReport) -> None:
    """写出诊断结果文件。

    Args:
        output_dir: 输出目录。
        report: 诊断报告。

    Returns:
        无。

    Raises:
        OSError: 写文件失败时抛出。
    """

    summary_payload = {
        "workspace_root": report.workspace_root,
        "process_concurrency": report.process_concurrency,
        "twenty_f_ticker_count": len(report.twenty_f_tickers),
        "false_positive_6k_count": len(report.false_positive_6k),
        "false_negative_6k_ticker_count": len(report.false_negative_6k),
        "process_runs": [asdict(item) for item in report.process_runs],
        "twenty_f_tickers": report.twenty_f_tickers,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "false_positive_6k.json").write_text(
        json.dumps([asdict(item) for item in report.false_positive_6k], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "false_negative_6k.json").write_text(
        json.dumps([asdict(item) for item in report.false_negative_6k], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "summary.md").write_text(_render_summary_markdown(report), encoding="utf-8")


def _render_summary_markdown(report: Sec6KRuleDiagnosticsReport) -> str:
    """渲染 Markdown 摘要。

    Args:
        report: 诊断报告。

    Returns:
        Markdown 文本。

    Raises:
        无。
    """

    lines = [
        "# SEC 6-K 规则诊断摘要",
        "",
        f"- workspace: `{report.workspace_root}`",
        f"- 20-F ticker 数量: **{len(report.twenty_f_tickers)}**",
        f"- process 并发上限: **{report.process_concurrency}**",
        f"- 非季报误落盘样本数: **{len(report.false_positive_6k)}**",
        f"- 季报误 reject ticker 数量: **{len(report.false_negative_6k)}**",
        "",
        "## 非季报误落盘",
    ]
    if not report.false_positive_6k:
        lines.append("- 无")
    else:
        for sample in report.false_positive_6k[:20]:
            lines.append(
                f"- `{sample.ticker} {sample.document_id}`: "
                f"classify={sample.current_classification} "
                f"gate={'; '.join(sample.hard_gate_reasons)}"
            )
    lines.append("")
    lines.append("## 季报误 reject")
    if not report.false_negative_6k:
        lines.append("- 无")
    else:
        for evidence in report.false_negative_6k[:20]:
            lines.append(
                f"- `{evidence.ticker}`: active_6k_excluding_hgf="
                f"{evidence.active_quarterly_count_excluding_hgf}, "
                f"rejections={len(evidence.rejected_samples)}"
            )
    lines.append("")
    lines.append("## Process 执行结果")
    failed_runs = [item for item in report.process_runs if item.return_code != 0]
    if not failed_runs:
        lines.append("- 全部 `process --ci --overwrite` 成功退出")
    else:
        for item in failed_runs[:20]:
            lines.append(f"- `{item.ticker}`: return_code={item.return_code}, log={item.log_path}")
    lines.append("")
    return "\n".join(lines)
