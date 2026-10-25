#!/usr/bin/env python3
"""LLM CI 优化用批量 score 与缺口诊断脚本。

该脚本把 Step 1 / Step 2 / Step 3 中重复出现的评分动作标准化为一条固定路径：

- 使用 storage 仓储扫描本轮应纳入 CI 的 active filing 文档全集。
- 对每个 form 调用 `python -m alpha.fins.score_sec_ci` 并落盘 JSON / Markdown / stdout。
- 额外输出 form 级 `summary.json` 与全局 `overall_summary.json`。
- 对照文档全集与 score JSON，补充“未纳入评分”的缺口原因诊断。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from typing import Literal, Mapping, TypeAlias, TypedDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alpha.fins.domain.document_models import DocumentQuery, ProcessedHandle
from alpha.fins.domain.enums import SourceKind
from alpha.fins.score_sec_ci import (
    FORM_PROFILES,
    ProcessedSnapshotDocument,
    ScoreConfig,
    _normalize_form_type,
    score_document,
)
from alpha.fins.storage import (
    FsCompanyMetaRepository,
    FsDocumentBlobRepository,
    FsProcessedDocumentRepository,
    FsSourceDocumentRepository,
)

DEFAULT_BASE = "workspace"
DEFAULT_TAG = "manual"
DEFAULT_FORMS = ("10-K", "10-Q", "20-F", "6-K", "8-K", "SC 13G", "DEF 14A")
DEFAULT_SCORE_DIRNAME = "ci_score"
AVAILABLE_STATUS = "available"
PROBE_READY = "ready"
PROBE_MISSING_PROCESSED = "missing_processed"
PROBE_MISSING_SNAPSHOT = "missing_snapshot"
PROBE_INVALID_SNAPSHOT = "invalid_snapshot"

ProbeStatus = Literal[
    "ready",
    "missing_processed",
    "missing_snapshot",
    "invalid_snapshot",
]


@dataclass(frozen=True, slots=True)
class FilingUniverseDocument:
    """应纳入当前 form CI 的 active filing 文档。"""

    ticker: str
    document_id: str
    form_type: str


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """文档级评分可用性探针结果。"""

    ticker: str
    document_id: str
    form_type: str
    status: ProbeStatus
    detail: str


@dataclass(frozen=True, slots=True)
class FormScoreRunResult:
    """单个 form 的 score 执行结果。"""

    form_type: str
    return_code: int
    output_json: Path
    output_md: Path
    output_txt: Path
    probe_json: Path
    universe_documents: tuple[FilingUniverseDocument, ...]
    probe_results: tuple[ProbeResult, ...]
    score_payload: "LoadedScorePayload"
    form_summary: "FormSummary"


@dataclass(frozen=True, slots=True)
class ScoreDocumentRecord:
    """score JSON 中单文档所需的最小字段。"""

    ticker: str
    document_id: str
    total_score: float


@dataclass(frozen=True, slots=True)
class ScoreSummaryRecord:
    """score JSON 中批量摘要的最小字段。"""

    average_score: float
    p10_score: float
    hard_gate_failures: int
    document_count: int


@dataclass(frozen=True, slots=True)
class LoadedScorePayload:
    """从 score JSON 提取后的强类型负载。"""

    summary: ScoreSummaryRecord | None
    documents: tuple[ScoreDocumentRecord, ...]


@dataclass(frozen=True, slots=True)
class MissingDocumentGap:
    """文档全集与 score 结果之间的缺口记录。"""

    ticker: str
    document_id: str
    status: ProbeStatus
    detail: str


@dataclass(frozen=True, slots=True)
class FormSummary:
    """单个 form 的摘要。"""

    form_type: str
    avg: float
    p10: float
    hard_gate_failures: int
    document_count: int
    universe_document_count: int
    missing_from_score_count: int
    missing_processed_count: int
    missing_snapshot_count: int
    invalid_snapshot_count: int
    score_return_code: int
    missing_from_score: tuple[MissingDocumentGap, ...]


@dataclass(frozen=True, slots=True)
class OverallSummary:
    """跨 form 全局摘要。"""

    overall_avg: float
    overall_p10: float
    overall_hard_gate_failures: int
    overall_document_count: int
    overall_universe_document_count: int
    overall_missing_from_score_count: int
    forms_included: tuple[str, ...]


class ProbePayloadDocument(TypedDict):
    """probe JSON 中的单文档结构。"""

    ticker: str
    document_id: str
    form_type: str
    status: str
    detail: str


class MissingFromScorePayload(TypedDict):
    """form 摘要中缺口文档的 JSON 结构。"""

    ticker: str
    document_id: str
    status: str
    detail: str


class FormSummaryPayload(TypedDict):
    """单个 form 摘要的 JSON 结构。"""

    form_type: str
    avg: float
    p10: float
    hard_gate_failures: int
    document_count: int
    universe_document_count: int
    missing_from_score_count: int
    missing_processed_count: int
    missing_snapshot_count: int
    invalid_snapshot_count: int
    score_return_code: int
    missing_from_score: list[MissingFromScorePayload]


class OverallSummaryPayload(TypedDict):
    """跨 form 全局摘要的 JSON 结构。"""

    overall_avg: float
    overall_p10: float
    overall_hard_gate_failures: int
    overall_document_count: int
    overall_universe_document_count: int
    overall_missing_from_score_count: int
    forms_included: list[str]


SummaryJsonPayload: TypeAlias = Mapping[str, FormSummaryPayload] | OverallSummaryPayload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行参数列表；为 `None` 时读取 `sys.argv`。

    Returns:
        参数命名空间。

    Raises:
        SystemExit: 参数非法时由 `argparse` 抛出。
    """

    parser = argparse.ArgumentParser(description="LLM CI 批量 score 与缺口诊断")
    parser.add_argument(
        "--base",
        default=DEFAULT_BASE,
        help="workspace 根目录或 portfolio 目录；默认 workspace",
    )
    parser.add_argument(
        "--forms",
        default=",".join(DEFAULT_FORMS),
        help="逗号分隔 form 列表；默认 10-K,10-Q,20-F,6-K,8-K,SC 13G,DEF 14A",
    )
    parser.add_argument(
        "--tickers",
        default=None,
        help="逗号分隔 ticker 列表；未传时自动扫描当前 workspace 全部可用 ticker",
    )
    parser.add_argument(
        "--tag",
        default=DEFAULT_TAG,
        help="本轮评分标签；输出目录为 workspace/tmp/ci_score/{tag}",
    )
    return parser.parse_args(argv)


def _resolve_workspace_root(base: str) -> Path:
    """把 CLI `--base` 解析为 workspace 根目录。

    Args:
        base: CLI 传入路径。

    Returns:
        workspace 根目录绝对路径。

    Raises:
        无。
    """

    normalized = Path(base).resolve()
    if normalized.name == "portfolio":
        return normalized.parent
    return normalized


def _resolve_project_root() -> Path:
    """解析仓库根目录。

    Args:
        无。

    Returns:
        仓库根目录绝对路径。

    Raises:
        无。
    """

    return Path(__file__).resolve().parents[1]


def _parse_csv_tokens(raw: str | None) -> list[str]:
    """解析逗号分隔字符串。

    Args:
        raw: 原始字符串。

    Returns:
        去空、去重后的 token 列表。

    Raises:
        无。
    """

    if raw is None:
        return []
    tokens = [token.strip() for token in raw.split(",") if token.strip()]
    return list(dict.fromkeys(tokens))


def _discover_available_tickers(workspace_root: Path) -> list[str]:
    """通过公司元数据仓储扫描全部可用 ticker。

    Args:
        workspace_root: workspace 根目录。

    Returns:
        已排序 ticker 列表。

    Raises:
        OSError: 仓储读取失败时抛出。
        ValueError: 元数据非法时抛出。
    """

    repository = FsCompanyMetaRepository(workspace_root)
    tickers: list[str] = []
    for entry in repository.scan_company_meta_inventory():
        if entry.status != AVAILABLE_STATUS or entry.company_meta is None:
            continue
        tickers.append(entry.company_meta.ticker.upper())
    return sorted(set(tickers))


def _resolve_tickers(workspace_root: Path, tickers_arg: str | None) -> list[str]:
    """解析本轮评分 ticker 集合。

    Args:
        workspace_root: workspace 根目录。
        tickers_arg: 原始 `--tickers` 参数。

    Returns:
        ticker 列表。

    Raises:
        OSError: 仓储扫描失败时抛出。
    """

    parsed = [ticker.upper() for ticker in _parse_csv_tokens(tickers_arg)]
    if parsed:
        return parsed
    return _discover_available_tickers(workspace_root)


def _resolve_forms(forms_arg: str) -> list[str]:
    """解析 form 列表并做标准化。

    Args:
        forms_arg: 原始 `--forms` 字符串。

    Returns:
        标准化 form 列表。

    Raises:
        ValueError: form 不受支持时抛出。
    """

    resolved: list[str] = []
    for raw_form in _parse_csv_tokens(forms_arg):
        normalized = _normalize_form_type(raw_form)
        if normalized not in FORM_PROFILES:
            raise ValueError(f"不支持的 form: {raw_form}")
        if normalized in resolved:
            continue
        resolved.append(normalized)
    return resolved or list(DEFAULT_FORMS)


def _slugify_form(form_type: str) -> str:
    """把 form 类型转换为稳定文件名片段。

    Args:
        form_type: 表单类型。

    Returns:
        文件名 slug。

    Raises:
        无。
    """

    return form_type.lower().replace("-", "").replace(" ", "")


def _build_output_paths(tag_dir: Path, form_type: str) -> tuple[Path, Path, Path, Path]:
    """构造单个 form 的全部输出路径。

    Args:
        tag_dir: `workspace/tmp/ci_score/{tag}` 目录。
        form_type: 表单类型。

    Returns:
        `json, md, txt, probe_json` 路径元组。

    Raises:
        无。
    """

    slug = _slugify_form(form_type)
    return (
        tag_dir / f"score_{slug}.json",
        tag_dir / f"score_{slug}.md",
        tag_dir / f"score_{slug}.txt",
        tag_dir / f"probe_{slug}.json",
    )


def _scan_form_universe(
    *,
    workspace_root: Path,
    tickers: list[str],
    form_type: str,
) -> list[FilingUniverseDocument]:
    """扫描指定 form 的 active filing 文档全集。

    Args:
        workspace_root: workspace 根目录。
        tickers: ticker 列表。
        form_type: 目标表单类型。

    Returns:
        文档全集列表。

    Raises:
        OSError: 仓储读取失败时抛出。
        ValueError: 元数据非法时抛出。
    """

    source_repository = FsSourceDocumentRepository(workspace_root)
    target_form = _normalize_form_type(form_type)
    results: list[FilingUniverseDocument] = []
    for ticker in tickers:
        for document_id in source_repository.list_source_document_ids(ticker, SourceKind.FILING):
            try:
                meta = source_repository.get_source_meta(ticker, document_id, SourceKind.FILING)
            except FileNotFoundError:
                continue
            if bool(meta.get("is_deleted", False)):
                continue
            current_form = _normalize_form_type(str(meta.get("form_type", "")).strip())
            if current_form != target_form:
                continue
            results.append(
                FilingUniverseDocument(
                    ticker=ticker,
                    document_id=document_id,
                    form_type=current_form,
                )
            )
    return sorted(results, key=lambda item: (item.ticker, item.document_id))


def _build_processed_presence_map(
    *,
    workspace_root: Path,
    tickers: list[str],
) -> dict[tuple[str, str], bool]:
    """构造 processed 文档存在性映射。

    Args:
        workspace_root: workspace 根目录。
        tickers: ticker 列表。

    Returns:
        `(ticker, document_id) -> processed 是否存在` 映射。

    Raises:
        OSError: 仓储读取失败时抛出。
    """

    processed_repository = FsProcessedDocumentRepository(workspace_root)
    results: dict[tuple[str, str], bool] = {}
    for ticker in tickers:
        summaries = processed_repository.list_processed_documents(
            ticker,
            DocumentQuery(source_kind=SourceKind.FILING.value),
        )
        for summary in summaries:
            results[(ticker, summary.document_id)] = True
    return results


def _classify_probe_exception(exc: Exception) -> tuple[ProbeStatus, str]:
    """把评分异常归类为缺口状态。

    Args:
        exc: 评分阶段抛出的异常。

    Returns:
        `status, detail` 二元组。

    Raises:
        无。
    """

    detail = str(exc).strip() or exc.__class__.__name__
    if "tool_snapshot_meta.json" in detail or "缺少" in detail:
        return PROBE_MISSING_SNAPSHOT, detail
    return PROBE_INVALID_SNAPSHOT, detail


def _probe_form_documents(
    *,
    workspace_root: Path,
    documents: list[FilingUniverseDocument],
    form_type: str,
) -> list[ProbeResult]:
    """对指定 form 文档执行评分可用性探针。

    Args:
        workspace_root: workspace 根目录。
        documents: 当前 form 的文档全集。
        form_type: 目标表单类型。

    Returns:
        探针结果列表。

    Raises:
        OSError: 仓储读取失败时抛出。
        ValueError: 评分配置非法时抛出。
    """

    processed_presence = _build_processed_presence_map(
        workspace_root=workspace_root,
        tickers=sorted({item.ticker for item in documents}),
    )
    blob_repository = FsDocumentBlobRepository(workspace_root)
    profile = FORM_PROFILES[form_type]
    config = ScoreConfig()
    results: list[ProbeResult] = []
    for item in documents:
        key = (item.ticker, item.document_id)
        if not processed_presence.get(key, False):
            results.append(
                ProbeResult(
                    ticker=item.ticker,
                    document_id=item.document_id,
                    form_type=item.form_type,
                    status=PROBE_MISSING_PROCESSED,
                    detail="processed manifest 中不存在该文档",
                )
            )
            continue
        snapshot = ProcessedSnapshotDocument(
            ticker=item.ticker,
            document_id=item.document_id,
            handle=ProcessedHandle(ticker=item.ticker, document_id=item.document_id),
        )
        try:
            score_document(snapshot, blob_repository, config, profile)
        except Exception as exc:  # noqa: BLE001 - 需要记录 scorer 真源异常。
            status, detail = _classify_probe_exception(exc)
            results.append(
                ProbeResult(
                    ticker=item.ticker,
                    document_id=item.document_id,
                    form_type=item.form_type,
                    status=status,
                    detail=detail,
                )
            )
            continue
        results.append(
            ProbeResult(
                ticker=item.ticker,
                document_id=item.document_id,
                form_type=item.form_type,
                status=PROBE_READY,
                detail="可进入 score_sec_ci 评分",
            )
        )
    return results


def _serialize_probe_result(item: ProbeResult) -> dict[str, str]:
    """序列化单个探针结果。

    Args:
        item: 探针结果。

    Returns:
        JSON 可序列化字典。

    Raises:
        无。
    """

    return {
        "ticker": item.ticker,
        "document_id": item.document_id,
        "form_type": item.form_type,
        "status": item.status,
        "detail": item.detail,
    }


def _write_probe_json(
    *,
    path: Path,
    form_type: str,
    universe_documents: list[FilingUniverseDocument],
    probe_results: list[ProbeResult],
) -> None:
    """写出 form 级 probe JSON。

    Args:
        path: 输出路径。
        form_type: 表单类型。
        universe_documents: 文档全集。
        probe_results: 探针结果列表。

    Returns:
        无。

    Raises:
        OSError: 文件写入失败时抛出。
    """

    counts = {
        PROBE_READY: sum(1 for item in probe_results if item.status == PROBE_READY),
        PROBE_MISSING_PROCESSED: sum(
            1 for item in probe_results if item.status == PROBE_MISSING_PROCESSED
        ),
        PROBE_MISSING_SNAPSHOT: sum(
            1 for item in probe_results if item.status == PROBE_MISSING_SNAPSHOT
        ),
        PROBE_INVALID_SNAPSHOT: sum(
            1 for item in probe_results if item.status == PROBE_INVALID_SNAPSHOT
        ),
    }
    payload = {
        "form_type": form_type,
        "universe_document_count": len(universe_documents),
        "probe_counts": counts,
        "documents": [_serialize_probe_result(item) for item in probe_results],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_score_command(
    *,
    workspace_root: Path,
    project_root: Path,
    tickers: list[str],
    form_type: str,
    output_json: Path,
    output_md: Path,
    output_txt: Path,
) -> int:
    """执行单个 form 的 `score_sec_ci` 命令。

    Args:
        workspace_root: workspace 根目录。
        project_root: 仓库根目录。
        tickers: ticker 列表。
        form_type: 表单类型。
        output_json: JSON 输出路径。
        output_md: Markdown 输出路径。
        output_txt: stdout/stderr 文本输出路径。

    Returns:
        score 命令退出码。

    Raises:
        OSError: 子进程启动或输出写入失败时抛出。
    """

    command = [
        sys.executable,
        "-m",
        "alpha.fins.score_sec_ci",
        "--form",
        form_type,
        "--base",
        str(workspace_root),
        "--tickers",
        ",".join(tickers),
        "--output-json",
        str(output_json),
        "--output-md",
        str(output_md),
    ]
    completed = subprocess.run(
        command,
        cwd=str(project_root),
        capture_output=True,
        text=True,
        check=False,
    )
    output_txt.write_text(
        (completed.stdout or "") + (completed.stderr or ""),
        encoding="utf-8",
    )
    return int(completed.returncode)


def _serialize_form_summary(summary: FormSummary) -> FormSummaryPayload:
    """序列化单个 form 摘要。

    Args:
        summary: form 摘要对象。

    Returns:
        JSON 可序列化字典。

    Raises:
        无。
    """

    return {
        "form_type": summary.form_type,
        "avg": summary.avg,
        "p10": summary.p10,
        "hard_gate_failures": summary.hard_gate_failures,
        "document_count": summary.document_count,
        "universe_document_count": summary.universe_document_count,
        "missing_from_score_count": summary.missing_from_score_count,
        "missing_processed_count": summary.missing_processed_count,
        "missing_snapshot_count": summary.missing_snapshot_count,
        "invalid_snapshot_count": summary.invalid_snapshot_count,
        "score_return_code": summary.score_return_code,
        "missing_from_score": [
            {
                "ticker": item.ticker,
                "document_id": item.document_id,
                "status": item.status,
                "detail": item.detail,
            }
            for item in summary.missing_from_score
        ],
    }


def _serialize_overall_summary(summary: OverallSummary) -> OverallSummaryPayload:
    """序列化全局摘要。

    Args:
        summary: 全局摘要对象。

    Returns:
        JSON 可序列化字典。

    Raises:
        无。
    """

    return {
        "overall_avg": summary.overall_avg,
        "overall_p10": summary.overall_p10,
        "overall_hard_gate_failures": summary.overall_hard_gate_failures,
        "overall_document_count": summary.overall_document_count,
        "overall_universe_document_count": summary.overall_universe_document_count,
        "overall_missing_from_score_count": summary.overall_missing_from_score_count,
        "forms_included": list(summary.forms_included),
    }


def _load_score_json(path: Path) -> LoadedScorePayload:
    """读取单个 form 的 score JSON。

    Args:
        path: JSON 文件路径。

    Returns:
        强类型 score 负载；文件不存在时返回空负载。

    Raises:
        OSError: 文件读取失败时抛出。
        ValueError: JSON 非法时抛出。
    """

    if not path.exists():
        return LoadedScorePayload(summary=None, documents=tuple())
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"score JSON 根节点必须是对象: {path}")
    raw_summary = payload.get("summary")
    summary: ScoreSummaryRecord | None = None
    if isinstance(raw_summary, dict):
        summary = ScoreSummaryRecord(
            average_score=float(raw_summary.get("average_score", 0.0)),
            p10_score=float(raw_summary.get("p10_score", 0.0)),
            hard_gate_failures=int(raw_summary.get("hard_gate_failures", 0)),
            document_count=int(raw_summary.get("document_count", 0)),
        )
    raw_documents = payload.get("documents", [])
    documents: list[ScoreDocumentRecord] = []
    if isinstance(raw_documents, list):
        for item in raw_documents:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker", "")).strip().upper()
            document_id = str(item.get("document_id", "")).strip()
            total_score = item.get("total_score")
            if not ticker or not document_id or not isinstance(total_score, int | float):
                continue
            documents.append(
                ScoreDocumentRecord(
                    ticker=ticker,
                    document_id=document_id,
                    total_score=float(total_score),
                )
            )
    return LoadedScorePayload(summary=summary, documents=tuple(documents))


def _extract_scored_document_keys(payload: LoadedScorePayload) -> set[tuple[str, str]]:
    """提取 score JSON 中的文档键集合。

    Args:
        payload: score JSON 负载。

    Returns:
        `(ticker, document_id)` 集合。

    Raises:
        无。
    """

    return {(item.ticker, item.document_id) for item in payload.documents}


def _build_probe_index(probe_results: list[ProbeResult]) -> dict[tuple[str, str], ProbeResult]:
    """把探针结果收敛为索引。

    Args:
        probe_results: 探针结果列表。

    Returns:
        `(ticker, document_id)` 到探针结果的映射。

    Raises:
        无。
    """

    return {
        (item.ticker, item.document_id): item
        for item in probe_results
    }


def _build_form_summary(
    *,
    form_type: str,
    score_payload: LoadedScorePayload,
    probe_results: list[ProbeResult],
    universe_documents: list[FilingUniverseDocument],
    return_code: int,
) -> FormSummary:
    """构建单个 form 的摘要。

    Args:
        form_type: 表单类型。
        score_payload: score JSON 负载。
        probe_results: 探针结果列表。
        universe_documents: 当前 form 的文档全集。
        return_code: score 命令退出码。

    Returns:
        form 级摘要对象。

    Raises:
        无。
    """

    scored_keys = _extract_scored_document_keys(score_payload)
    probe_index = _build_probe_index(probe_results)
    missing_from_score: list[MissingDocumentGap] = []
    for item in universe_documents:
        key = (item.ticker, item.document_id)
        if key in scored_keys:
            continue
        probe = probe_index.get(key)
        status = probe.status if probe is not None else PROBE_INVALID_SNAPSHOT
        detail = probe.detail if probe is not None else "文档未出现在 score JSON 中"
        missing_from_score.append(
            MissingDocumentGap(
                ticker=item.ticker,
                document_id=item.document_id,
                status=status,
                detail=detail,
            )
        )
    summary = score_payload.summary
    return FormSummary(
        form_type=form_type,
        avg=summary.average_score if summary is not None else 0.0,
        p10=summary.p10_score if summary is not None else 0.0,
        hard_gate_failures=summary.hard_gate_failures if summary is not None else 0,
        document_count=summary.document_count if summary is not None else 0,
        universe_document_count=len(universe_documents),
        missing_from_score_count=len(missing_from_score),
        missing_processed_count=sum(
            1 for item in probe_results if item.status == PROBE_MISSING_PROCESSED
        ),
        missing_snapshot_count=sum(
            1 for item in probe_results if item.status == PROBE_MISSING_SNAPSHOT
        ),
        invalid_snapshot_count=sum(
            1 for item in probe_results if item.status == PROBE_INVALID_SNAPSHOT
        ),
        score_return_code=return_code,
        missing_from_score=tuple(missing_from_score),
    )


def _write_summary_json(
    path: Path,
    payload: SummaryJsonPayload,
) -> None:
    """写出 JSON 摘要文件。

    Args:
        path: 输出路径。
        payload: JSON 负载。

    Returns:
        无。

    Raises:
        OSError: 文件写入失败时抛出。
    """

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_overall_summary(
    *,
    form_summaries: list[FormSummary],
    form_payloads: list[LoadedScorePayload],
) -> OverallSummary:
    """构建跨 form 全局摘要。

    Args:
        form_summaries: form 级摘要列表。
        form_payloads: form 级 score JSON 负载列表。

    Returns:
        overall 摘要对象。

    Raises:
        无。
    """

    scores: list[float] = []
    overall_hard_gate_failures = 0
    overall_document_count = 0
    for payload in form_payloads:
        scores.extend(item.total_score for item in payload.documents)
    for summary in form_summaries:
        overall_hard_gate_failures += summary.hard_gate_failures
        overall_document_count += summary.document_count
    overall_avg = round(sum(scores) / len(scores), 2) if scores else 0.0
    if not scores:
        overall_p10 = 0.0
    elif len(scores) == 1:
        overall_p10 = round(float(scores[0]), 2)
    else:
        sorted_scores = sorted(scores)
        position = 0.1 * (len(sorted_scores) - 1)
        lower = int(position)
        upper = min(lower + 1, len(sorted_scores) - 1)
        ratio = position - lower
        interpolated = sorted_scores[lower] * (1 - ratio) + sorted_scores[upper] * ratio
        overall_p10 = round(float(interpolated), 2)
    return OverallSummary(
        overall_avg=overall_avg,
        overall_p10=overall_p10,
        overall_hard_gate_failures=overall_hard_gate_failures,
        overall_document_count=overall_document_count,
        overall_universe_document_count=sum(
            item.universe_document_count for item in form_summaries
        ),
        overall_missing_from_score_count=sum(
            item.missing_from_score_count for item in form_summaries
        ),
        forms_included=tuple(item.form_type for item in form_summaries),
    )


def _run_single_form(
    *,
    workspace_root: Path,
    project_root: Path,
    tag_dir: Path,
    tickers: list[str],
    form_type: str,
) -> FormScoreRunResult:
    """执行单个 form 的 probe 与 score。

    Args:
        workspace_root: workspace 根目录。
        project_root: 仓库根目录。
        tag_dir: 当前 tag 的输出目录。
        tickers: ticker 列表。
        form_type: 表单类型。

    Returns:
        单个 form 的执行结果。

    Raises:
        OSError: 仓储读取、文件写入或子进程执行失败时抛出。
        ValueError: form 非法时抛出。
    """

    output_json, output_md, output_txt, probe_json = _build_output_paths(tag_dir, form_type)
    universe_documents = _scan_form_universe(
        workspace_root=workspace_root,
        tickers=tickers,
        form_type=form_type,
    )
    probe_results = _probe_form_documents(
        workspace_root=workspace_root,
        documents=universe_documents,
        form_type=form_type,
    )
    _write_probe_json(
        path=probe_json,
        form_type=form_type,
        universe_documents=universe_documents,
        probe_results=probe_results,
    )
    return_code = _run_score_command(
        workspace_root=workspace_root,
        project_root=project_root,
        tickers=tickers,
        form_type=form_type,
        output_json=output_json,
        output_md=output_md,
        output_txt=output_txt,
    )
    score_payload = _load_score_json(output_json)
    form_summary = _build_form_summary(
        form_type=form_type,
        score_payload=score_payload,
        probe_results=probe_results,
        universe_documents=universe_documents,
        return_code=return_code,
    )
    return FormScoreRunResult(
        form_type=form_type,
        return_code=return_code,
        output_json=output_json,
        output_md=output_md,
        output_txt=output_txt,
        probe_json=probe_json,
        universe_documents=tuple(universe_documents),
        probe_results=tuple(probe_results),
        score_payload=score_payload,
        form_summary=form_summary,
    )

def main(argv: list[str] | None = None) -> int:
    """脚本入口。

    Args:
        argv: 命令行参数列表；为 `None` 时读取 `sys.argv`。

    Returns:
        固定返回 `0`；评分是否通过由产出 JSON 自行表达。

    Raises:
        OSError: 文件系统、仓储或子进程失败时抛出。
        ValueError: 参数非法时抛出。
    """

    args = parse_args(argv)
    workspace_root = _resolve_workspace_root(str(args.base))
    project_root = _resolve_project_root()
    forms = _resolve_forms(str(args.forms))
    tickers = _resolve_tickers(workspace_root, args.tickers)
    tag_dir = workspace_root / "tmp" / DEFAULT_SCORE_DIRNAME / str(args.tag)
    tag_dir.mkdir(parents=True, exist_ok=True)

    summary_payload: dict[str, FormSummaryPayload] = {}
    form_payloads: list[LoadedScorePayload] = []
    form_summaries: list[FormSummary] = []
    for form_type in forms:
        run_result = _run_single_form(
            workspace_root=workspace_root,
            project_root=project_root,
            tag_dir=tag_dir,
            tickers=tickers,
            form_type=form_type,
        )
        summary_payload[form_type] = _serialize_form_summary(run_result.form_summary)
        form_payloads.append(run_result.score_payload)
        form_summaries.append(run_result.form_summary)

    _write_summary_json(tag_dir / "summary.json", summary_payload)
    overall_summary = _build_overall_summary(
        form_summaries=form_summaries,
        form_payloads=form_payloads,
    )
    _write_summary_json(
        tag_dir / "overall_summary.json",
        _serialize_overall_summary(overall_summary),
    )
    print(tag_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
