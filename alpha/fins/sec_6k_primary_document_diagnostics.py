"""SEC 6-K 主文件选文诊断。

该模块用于识别另一类常被误归因成 `_classify_6k_text()` 规则缺陷的问题：
同一份 6-K filing 同时包含多个 exhibit，当前 `primary_document` 指向的文件
并不是季度结果正文，但目录中另一个 exhibit 才是当前规则真源应保留的季度
披露文本。

诊断口径保持同源：
- 只读取 active `6-K` filing；
- 只通过仓储协议读取 meta 与文件字节；
- 对每个候选文件都用当前 `_classify_6k_text()` 重新分类；
- 只报告一种严格场景：`primary_document` 当前不是季度结果，但同 filing 下存在
  另一个 exhibit 被真源判成季度结果。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from alpha.fins.domain.document_models import DocumentMeta, SourceFileEntry
from alpha.fins.domain.enums import SourceKind
from alpha.fins.pipelines.sec_6k_rules import (
    _classify_6k_text,
    _extract_head_text,
    _is_positive_6k_classification,
    _score_6k_filename,
)
from alpha.fins.sec_6k_rule_diagnostics import discover_twenty_f_tickers
from alpha.fins.storage import (
    FsCompanyMetaRepository,
    FsDocumentBlobRepository,
    FsSourceDocumentRepository,
)

DEFAULT_OUTPUT_DIRNAME = "sec_6k_primary_document_diagnostics"
DEFAULT_HEAD_TEXT_MAX_LINES = 80


@dataclass(frozen=True, slots=True)
class FilingReference:
    """待诊断的 active 6-K filing 引用。"""

    ticker: str
    document_id: str


@dataclass(frozen=True, slots=True)
class CandidateDocumentDiagnosis:
    """单个 6-K 候选文件的诊断结果。"""

    filename: str
    filename_priority: int
    classification: str
    is_primary_document: bool
    head_text: str


@dataclass(frozen=True, slots=True)
class PrimaryDocumentMismatchSample:
    """当前主文件与季度正文 exhibit 不一致的样本。"""

    ticker: str
    document_id: str
    primary_document: str
    primary_classification: str
    recommended_document: str
    recommended_classification: str
    candidate_count: int
    candidates: tuple[CandidateDocumentDiagnosis, ...]


@dataclass(frozen=True, slots=True)
class Sec6KPrimaryDocumentDiagnosticsReport:
    """6-K 主文件选文诊断报告。"""

    workspace_root: str
    analyzed_filing_count: int
    mismatches: tuple[PrimaryDocumentMismatchSample, ...]


def run_sec_6k_primary_document_diagnostics(
    *,
    workspace_root: Path,
    output_dir: Path | None = None,
    target_tickers: list[str] | None = None,
    target_document_ids: list[str] | None = None,
    head_text_max_lines: int = DEFAULT_HEAD_TEXT_MAX_LINES,
) -> Sec6KPrimaryDocumentDiagnosticsReport:
    """运行 6-K 主文件选文诊断。

    Args:
        workspace_root: workspace 根目录。
        output_dir: 可选输出目录；默认写入 `workspace/tmp/sec_6k_primary_document_diagnostics/`。
        target_tickers: 可选 ticker 子集；为空时按当前 active `20-F` 公司全集扫描。
        target_document_ids: 可选 document_id 子集；为空时扫描目标 ticker 下全部 active `6-K`。
        head_text_max_lines: 抽取候选文件头部文本的最大行数。

    Returns:
        诊断报告。

    Raises:
        OSError: 仓储读取或报告写入失败时抛出。
        ValueError: 传入过滤参数非法时抛出。
    """

    resolved_workspace_root = workspace_root.resolve()
    resolved_output_dir = (
        output_dir.resolve()
        if output_dir is not None
        else resolved_workspace_root / "tmp" / DEFAULT_OUTPUT_DIRNAME
    )
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    source_repository = FsSourceDocumentRepository(resolved_workspace_root)
    blob_repository = FsDocumentBlobRepository(resolved_workspace_root)
    company_repository = FsCompanyMetaRepository(resolved_workspace_root)

    selected_tickers = _select_target_tickers(
        company_repository=company_repository,
        source_repository=source_repository,
        target_tickers=target_tickers,
    )
    selected_document_ids = _normalize_document_ids(target_document_ids)
    filing_refs = _collect_target_filings(
        source_repository=source_repository,
        target_tickers=selected_tickers,
        target_document_ids=selected_document_ids,
    )

    mismatches: list[PrimaryDocumentMismatchSample] = []
    for filing_ref in filing_refs:
        mismatch = _analyze_primary_document_mismatch(
            source_repository=source_repository,
            blob_repository=blob_repository,
            filing_ref=filing_ref,
            head_text_max_lines=head_text_max_lines,
        )
        if mismatch is not None:
            mismatches.append(mismatch)

    mismatches.sort(key=lambda item: (item.ticker, item.document_id))
    report = Sec6KPrimaryDocumentDiagnosticsReport(
        workspace_root=str(resolved_workspace_root),
        analyzed_filing_count=len(filing_refs),
        mismatches=tuple(mismatches),
    )
    _write_diagnostics_outputs(resolved_output_dir, report)
    return report


def _select_target_tickers(
    *,
    company_repository: FsCompanyMetaRepository,
    source_repository: FsSourceDocumentRepository,
    target_tickers: list[str] | None,
) -> list[str]:
    """选择本轮要扫描的 ticker 集合。

    Args:
        company_repository: 公司元数据仓储。
        source_repository: 源文档仓储。
        target_tickers: 可选 ticker 子集。

    Returns:
        规范化后的 ticker 列表。

    Raises:
        ValueError: 传入 ticker 子集但解析后为空时抛出。
    """

    if target_tickers is None:
        return discover_twenty_f_tickers(
            company_repository=company_repository,
            source_repository=source_repository,
        )
    normalized = [ticker.strip().upper() for ticker in target_tickers if ticker.strip()]
    if not normalized:
        raise ValueError("target_tickers 不能为空")
    ordered: list[str] = []
    for ticker in normalized:
        if ticker not in ordered:
            ordered.append(ticker)
    return ordered


def _normalize_document_ids(target_document_ids: list[str] | None) -> set[str] | None:
    """规范化 document_id 过滤集合。

    Args:
        target_document_ids: 可选 document_id 列表。

    Returns:
        去重后的 document_id 集合；未传入时返回 `None`。

    Raises:
        ValueError: 传入非空列表但去空后为空时抛出。
    """

    if target_document_ids is None:
        return None
    normalized = {item.strip() for item in target_document_ids if item.strip()}
    if not normalized:
        raise ValueError("target_document_ids 不能为空")
    return normalized


def _collect_target_filings(
    *,
    source_repository: FsSourceDocumentRepository,
    target_tickers: list[str],
    target_document_ids: set[str] | None,
) -> list[FilingReference]:
    """收集待诊断的 active 6-K filing。

    Args:
        source_repository: 源文档仓储。
        target_tickers: 目标 ticker 列表。
        target_document_ids: 可选 document_id 过滤集合。

    Returns:
        filing 引用列表。

    Raises:
        OSError: 仓储读取失败时抛出。
    """

    filings: list[FilingReference] = []
    for ticker in target_tickers:
        for document_id in source_repository.list_source_document_ids(ticker, SourceKind.FILING):
            if target_document_ids is not None and document_id not in target_document_ids:
                continue
            meta = source_repository.get_source_meta(ticker, document_id, SourceKind.FILING)
            if bool(meta.get("is_deleted", False)):
                continue
            if str(meta.get("form_type", "")).strip().upper() != "6-K":
                continue
            filings.append(FilingReference(ticker=ticker, document_id=document_id))
    filings.sort(key=lambda item: (item.ticker, item.document_id))
    return filings


def _analyze_primary_document_mismatch(
    *,
    source_repository: FsSourceDocumentRepository,
    blob_repository: FsDocumentBlobRepository,
    filing_ref: FilingReference,
    head_text_max_lines: int,
) -> PrimaryDocumentMismatchSample | None:
    """分析单个 filing 是否存在主文件选文错位。

    Args:
        source_repository: 源文档仓储。
        blob_repository: 文件对象仓储。
        filing_ref: filing 引用。
        head_text_max_lines: 候选文件头部文本最大行数。

    Returns:
        若存在“主文件非季度、替代 exhibit 为季度”的同源证据，则返回 mismatch 样本；
        否则返回 `None`。

    Raises:
        OSError: 仓储读取失败时抛出。
    """

    meta = source_repository.get_source_meta(
        filing_ref.ticker,
        filing_ref.document_id,
        SourceKind.FILING,
    )
    primary_document = str(meta.get("primary_document", "")).strip()
    if not primary_document:
        return None
    handle = source_repository.get_source_handle(
        filing_ref.ticker,
        filing_ref.document_id,
        SourceKind.FILING,
    )
    candidate_names = _collect_candidate_names(meta, primary_document)
    candidate_diagnostics: list[CandidateDocumentDiagnosis] = []
    primary_diagnosis: CandidateDocumentDiagnosis | None = None

    for candidate_name in candidate_names:
        try:
            payload = blob_repository.read_file_bytes(handle, candidate_name)
        except OSError:
            continue
        head_text = _extract_head_text(payload, max_lines=head_text_max_lines)
        diagnosis = CandidateDocumentDiagnosis(
            filename=candidate_name,
            filename_priority=_score_6k_filename(candidate_name, primary_document)[0],
            classification=_classify_6k_text(head_text),
            is_primary_document=candidate_name.lower() == primary_document.lower(),
            head_text=head_text,
        )
        candidate_diagnostics.append(diagnosis)
        if diagnosis.is_primary_document:
            primary_diagnosis = diagnosis

    if primary_diagnosis is None:
        return None
    if _is_positive_6k_classification(primary_diagnosis.classification):
        return None

    positive_candidates = [
        item for item in candidate_diagnostics if _is_positive_6k_classification(item.classification)
    ]
    if not positive_candidates:
        return None
    recommended = min(
        positive_candidates,
        key=lambda item: (item.filename_priority, item.filename.lower()),
    )
    if recommended.filename.lower() == primary_document.lower():
        return None
    ordered_candidates = tuple(
        sorted(
            candidate_diagnostics,
            key=lambda item: (item.filename_priority, item.filename.lower()),
        )
    )
    return PrimaryDocumentMismatchSample(
        ticker=filing_ref.ticker,
        document_id=filing_ref.document_id,
        primary_document=primary_document,
        primary_classification=primary_diagnosis.classification,
        recommended_document=recommended.filename,
        recommended_classification=recommended.classification,
        candidate_count=len(ordered_candidates),
        candidates=ordered_candidates,
    )


def _collect_candidate_names(meta: DocumentMeta, primary_document: str) -> list[str]:
    """从 source meta 收集本次要比对的候选文件名。

    Args:
        meta: source meta。
        primary_document: 当前主文件名。

    Returns:
        去重并排序后的候选文件名列表。

    Raises:
        无。
    """

    candidates: set[str] = set()
    primary = primary_document.strip()
    if primary:
        candidates.add(primary)
    raw_files = meta.get("files", [])
    if not isinstance(raw_files, list):
        return sorted(candidates, key=str.lower)
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        try:
            entry = SourceFileEntry.from_dict(item)
        except (KeyError, ValueError):
            continue
        if entry.name.lower().endswith((".htm", ".html")):
            candidates.add(entry.name)
    return sorted(candidates, key=str.lower)


def _write_diagnostics_outputs(
    output_dir: Path,
    report: Sec6KPrimaryDocumentDiagnosticsReport,
) -> None:
    """写出诊断产物。

    Args:
        output_dir: 输出目录。
        report: 诊断报告。

    Returns:
        无。

    Raises:
        OSError: 文件写入失败时抛出。
    """

    summary = {
        "workspace_root": report.workspace_root,
        "analyzed_filing_count": report.analyzed_filing_count,
        "mismatch_count": len(report.mismatches),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "mismatch_samples.json").write_text(
        json.dumps([asdict(item) for item in report.mismatches], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "summary.md").write_text(
        _build_summary_markdown(report),
        encoding="utf-8",
    )


def _build_summary_markdown(report: Sec6KPrimaryDocumentDiagnosticsReport) -> str:
    """构建 Markdown 摘要。

    Args:
        report: 诊断报告。

    Returns:
        Markdown 文本。

    Raises:
        无。
    """

    lines = [
        "# SEC 6-K primary_document 诊断摘要",
        "",
        f"- workspace: `{report.workspace_root}`",
        f"- 扫描 active 6-K 数量: **{report.analyzed_filing_count}**",
        f"- 发现主文件错位样本数: **{len(report.mismatches)}**",
        "",
        "## 主文件错位样本",
    ]
    if not report.mismatches:
        lines.append("- 无")
        lines.append("")
        return "\n".join(lines)
    for sample in report.mismatches[:20]:
        lines.append(
            "- "
            f"`{sample.ticker} {sample.document_id}`: "
            f"primary=`{sample.primary_document}` ({sample.primary_classification}) -> "
            f"recommended=`{sample.recommended_document}` ({sample.recommended_classification})"
        )
    lines.append("")
    return "\n".join(lines)