#!/usr/bin/env python3
"""LLM CI 优化用最小增量 process 执行器。

该脚本只负责把 CI 优化需要的 `process --ci --overwrite` 调度固化下来，
避免人工批量拼命令时出现：

- ticker 级别重复启动
- 文档 ID 聚合不稳定
- 并发数漂移
- 超时与日志落盘口径不一致

脚本默认行为：

- 未传 `--documents-json` 且未传 `--tickers` 时，自动通过
  `CompanyMetaRepositoryProtocol.scan_company_meta_inventory()` 扫描当前 workspace
  内全部可用 ticker。
- 若传 `--documents-json`，则先按 ticker 聚合；当单个 ticker 的文档数过多时，
  会按稳定顺序切成多个批次，避免 300 秒子任务超时。
- ticker 级固定并发 `27`。
- 单任务超时固定 `300` 秒。
- 日志输出到 `workspace/tmp/process_logs/{tag}/`。
- 汇总输出到 `workspace/tmp/process_runs/{tag}.json`。
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
from time import perf_counter, time
from typing import TypedDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alpha.fins.storage import FsCompanyMetaRepository

DEFAULT_BASE = "workspace"
DEFAULT_CONCURRENCY = 27
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_MAX_DOCUMENTS_PER_JOB = 4
DEFAULT_LOGS_DIRNAME = "process_logs"
DEFAULT_RUNS_DIRNAME = "process_runs"
AVAILABLE_STATUS = "available"
_FAILED_DOCUMENT_LINE_RE = re.compile(r"(?m)^\s*-\s+.+\|\s*status=failed\b")


class DocumentSelectorEntry(TypedDict):
    """`--documents-json` 允许的输入项。"""

    ticker: str
    document_id: str


@dataclass(frozen=True, slots=True)
class ProcessJob:
    """单个 ticker 的 process 作业。"""

    ticker: str
    document_ids: tuple[str, ...]
    batch_index: int = 1


@dataclass(frozen=True, slots=True)
class ProcessRunResult:
    """单个 ticker 的执行结果。"""

    ticker: str
    document_ids: tuple[str, ...]
    command: tuple[str, ...]
    return_code: int
    duration_seconds: float
    timed_out: bool
    log_path: str
    batch_index: int
    reported_failed_documents: int


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行参数列表；为 `None` 时读取 `sys.argv`。

    Returns:
        参数命名空间。

    Raises:
        SystemExit: 参数非法时由 `argparse` 抛出。
    """

    parser = argparse.ArgumentParser(description="LLM CI 批量 process 执行器")
    parser.add_argument(
        "--base",
        default=DEFAULT_BASE,
        help="workspace 根目录或 portfolio 目录；默认 workspace",
    )
    parser.add_argument(
        "--tickers",
        default=None,
        help="逗号分隔 ticker 列表；未传时自动扫描当前 workspace 全部可用 ticker",
    )
    parser.add_argument(
        "--documents-json",
        default=None,
        help="文档选择 JSON 数组；支持直接传 JSON 字符串，或传 JSON 文件路径",
    )
    parser.add_argument(
        "--tag",
        default="manual",
        help="本轮执行标签；用于日志与汇总文件命名",
    )
    parser.add_argument(
        "--max-documents-per-job",
        type=int,
        default=DEFAULT_MAX_DOCUMENTS_PER_JOB,
        help="当使用 --documents-json 时，单个子任务允许的最大文档数；默认 4",
    )
    return parser.parse_args(argv)


def _resolve_workspace_root(base: str) -> Path:
    """把 CLI `--base` 解析为 workspace 根目录。

    Args:
        base: CLI 传入的根路径。

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


def _parse_ticker_tokens(raw: str | None) -> list[str]:
    """解析逗号分隔的 ticker 字符串。

    Args:
        raw: 原始字符串。

    Returns:
        规范化后的 ticker 列表。

    Raises:
        无。
    """

    if raw is None:
        return []
    tickers = [token.strip().upper() for token in raw.split(",") if token.strip()]
    return list(dict.fromkeys(tickers))


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


def _load_document_selector_entries(raw: str) -> list[DocumentSelectorEntry]:
    """读取 `--documents-json` 负载。

    Args:
        raw: JSON 字符串或 JSON 文件路径。

    Returns:
        文档选择项列表。

    Raises:
        ValueError: JSON 结构非法时抛出。
        OSError: 读取文件失败时抛出。
    """

    candidate_path = Path(raw)
    if candidate_path.exists():
        payload_text = candidate_path.read_text(encoding="utf-8")
    else:
        payload_text = raw

    payload = json.loads(payload_text)
    if not isinstance(payload, list):
        raise ValueError("--documents-json 必须是数组")

    entries: list[DocumentSelectorEntry] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("--documents-json 数组元素必须是对象")
        ticker = str(item.get("ticker", "")).strip().upper()
        document_id = str(item.get("document_id", "")).strip()
        if not ticker:
            raise ValueError("--documents-json 项缺少 ticker")
        if not document_id:
            raise ValueError("--documents-json 项缺少 document_id")
        entries.append(DocumentSelectorEntry(ticker=ticker, document_id=document_id))
    return entries


def _aggregate_document_ids_by_ticker(
    entries: list[DocumentSelectorEntry],
) -> dict[str, tuple[str, ...]]:
    """按 ticker 聚合文档 ID。

    Args:
        entries: 文档选择项列表。

    Returns:
        `ticker -> document_ids` 映射。

    Raises:
        无。
    """

    grouped: dict[str, list[str]] = defaultdict(list)
    for entry in entries:
        ticker = entry["ticker"].strip().upper()
        document_id = entry["document_id"].strip()
        if document_id in grouped[ticker]:
            continue
        grouped[ticker].append(document_id)
    return {
        ticker: tuple(document_ids)
        for ticker, document_ids in sorted(grouped.items())
    }


def _build_jobs(
    *,
    tickers: list[str],
    document_ids_by_ticker: dict[str, tuple[str, ...]],
    max_documents_per_job: int = DEFAULT_MAX_DOCUMENTS_PER_JOB,
) -> list[ProcessJob]:
    """构建 process 作业列表。

    Args:
        tickers: ticker 列表。
        document_ids_by_ticker: `ticker -> document_ids` 映射。

    Returns:
        待执行作业列表。

    Raises:
        无。
    """

    if document_ids_by_ticker:
        jobs: list[ProcessJob] = []
        for ticker, document_ids in document_ids_by_ticker.items():
            batches = _split_document_ids_for_job(
                document_ids,
                max_documents_per_job=max_documents_per_job,
            )
            for batch_index, batch_document_ids in enumerate(batches, start=1):
                jobs.append(
                    ProcessJob(
                        ticker=ticker,
                        document_ids=batch_document_ids,
                        batch_index=batch_index,
                    )
                )
        return jobs
    return [ProcessJob(ticker=ticker, document_ids=tuple()) for ticker in tickers]


def _split_document_ids_for_job(
    document_ids: tuple[str, ...],
    *,
    max_documents_per_job: int | None = None,
) -> tuple[tuple[str, ...], ...]:
    """把同一 ticker 的文档集合按稳定顺序切成多个子批次。

    `process --document-id ...` 在文档数较大时，常因单个 ticker 作业过重而
    命中 300 秒超时。这里不改变单任务超时口径，只在调度层把大批次切小，
    以便最小增量 process 真正跑完。

    Args:
        document_ids: 已按稳定顺序去重的文档 ID 列表。
        max_documents_per_job: 单个子批次允许的最大文档数。

    Returns:
        切分后的批次元组；输入为空时返回空元组。

    Raises:
        ValueError: 批次大小非法时抛出。
    """

    normalized_limit = (
        DEFAULT_MAX_DOCUMENTS_PER_JOB
        if max_documents_per_job is None
        else int(max_documents_per_job)
    )
    if normalized_limit <= 0:
        raise ValueError("max_documents_per_job 必须大于 0")
    if not document_ids:
        return tuple()

    batches: list[tuple[str, ...]] = []
    for start in range(0, len(document_ids), normalized_limit):
        batches.append(document_ids[start : start + normalized_limit])
    return tuple(batches)


def _group_jobs_by_ticker(jobs: list[ProcessJob]) -> tuple[tuple[ProcessJob, ...], ...]:
    """按 ticker 把作业分组，确保同一 ticker 串行执行。

    `alpha.cli process` 会在 ticker 级使用 batch 事务更新 `portfolio/{ticker}`。
    若同一 ticker 的多个子批次并发执行，提交阶段会互相覆盖 staging/backup，
    典型表现就是 `commit_batch` 失败后回滚，并留下 `processed` 缺口。

    Args:
        jobs: 待执行作业列表。

    Returns:
        以 ticker 为单位分组后的作业序列；组内按 `batch_index` 升序排列。

    Raises:
        无。
    """

    grouped: dict[str, list[ProcessJob]] = defaultdict(list)
    for job in jobs:
        grouped[job.ticker].append(job)
    return tuple(
        tuple(sorted(grouped[ticker], key=lambda item: item.batch_index))
        for ticker in sorted(grouped)
    )


def _count_reported_failed_documents(log_text: str) -> int:
    """从 CLI 日志中统计已报告的失败文档数。

    目前 `alpha.cli process` 即使某些文档处理失败，也可能整体以退出码 `0`
    返回，因此不能只依赖子进程返回码判断成功。这里直接以 CLI 最终摘要里的
    `- xxx | status=failed | ...` 行作为真源信号。

    Args:
        log_text: 子进程标准输出与标准错误拼接文本。

    Returns:
        已报告失败文档数。

    Raises:
        无。
    """

    return len(_FAILED_DOCUMENT_LINE_RE.findall(str(log_text or "")))


def _is_successful_result(result: ProcessRunResult) -> bool:
    """判断单个作业是否真正成功。

    Args:
        result: 单个 process 作业结果。

    Returns:
        退出码为 0 且日志中未报告失败文档时返回 `True`。

    Raises:
        无。
    """

    return result.return_code == 0 and result.reported_failed_documents == 0


def _build_process_command(
    *,
    workspace_root: Path,
    ticker: str,
    document_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """构造单个 ticker 的 process 命令。

    Args:
        workspace_root: workspace 根目录。
        ticker: 股票代码。
        document_ids: 待处理文档 ID 列表。

    Returns:
        可执行命令元组。

    Raises:
        无。
    """

    command: list[str] = [
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
    return tuple(command)


def _run_process_job(
    job: ProcessJob,
    project_root: Path,
    workspace_root: Path,
    log_dir: Path,
    timeout_seconds: int,
) -> ProcessRunResult:
    """执行单个 ticker 的 process 命令。

    Args:
        job: ticker 级作业。
        project_root: 仓库根目录。
        workspace_root: workspace 根目录。
        log_dir: 日志目录。
        timeout_seconds: 单任务超时秒数。

    Returns:
        执行结果对象。

    Raises:
        OSError: 子进程启动或日志写入失败时抛出。
    """

    log_path = log_dir / f"{job.ticker}__batch_{job.batch_index:03d}.log"
    command = _build_process_command(
        workspace_root=workspace_root,
        ticker=job.ticker,
        document_ids=job.document_ids,
    )
    started = perf_counter()
    timed_out = False
    return_code = 0
    log_text = ""
    try:
        completed = subprocess.run(
            command,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return_code = int(completed.returncode)
        log_text = (completed.stdout or "") + (completed.stderr or "")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = 124
        stdout_text = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr_text = exc.stderr if isinstance(exc.stderr, str) else ""
        log_text = f"{stdout_text}{stderr_text}\nTIMEOUT: {timeout_seconds}s\n"
    duration_seconds = round(perf_counter() - started, 3)
    reported_failed_documents = _count_reported_failed_documents(log_text)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path.write_text(log_text, encoding="utf-8")
    return ProcessRunResult(
        ticker=job.ticker,
        document_ids=job.document_ids,
        command=command,
        return_code=return_code,
        duration_seconds=duration_seconds,
        timed_out=timed_out,
        log_path=str(log_path),
        batch_index=job.batch_index,
        reported_failed_documents=reported_failed_documents,
    )


def _run_ticker_job_sequence(
    ticker_jobs: tuple[ProcessJob, ...],
    project_root: Path,
    workspace_root: Path,
    log_dir: Path,
    timeout_seconds: int,
) -> list[ProcessRunResult]:
    """顺序执行同一 ticker 下的全部子批次。

    Args:
        ticker_jobs: 同一 ticker 的作业批次。
        project_root: 仓库根目录。
        workspace_root: workspace 根目录。
        log_dir: 日志目录。
        timeout_seconds: 单任务超时秒数。

    Returns:
        该 ticker 下全部子批次的执行结果。

    Raises:
        OSError: 子进程启动或日志写入失败时抛出。
    """

    return [
        _run_process_job(
            job=job,
            project_root=project_root,
            workspace_root=workspace_root,
            log_dir=log_dir,
            timeout_seconds=timeout_seconds,
        )
        for job in ticker_jobs
    ]


def _run_jobs(
    *,
    jobs: list[ProcessJob],
    project_root: Path,
    workspace_root: Path,
    log_dir: Path,
    timeout_seconds: int,
) -> list[ProcessRunResult]:
    """并发执行全部 process 作业。

    Args:
        jobs: 待执行作业列表。
        project_root: 仓库根目录。
        workspace_root: workspace 根目录。
        log_dir: 日志目录。
        timeout_seconds: 单任务超时秒数。

    Returns:
        按 ticker 排序的执行结果列表。

    Raises:
        OSError: 子进程启动或日志写入失败时抛出。
    """

    if not jobs:
        return []

    results: list[ProcessRunResult] = []
    future_map: dict[Future[list[ProcessRunResult]], tuple[ProcessJob, ...]] = {}
    grouped_jobs = _group_jobs_by_ticker(jobs)
    with ProcessPoolExecutor(max_workers=DEFAULT_CONCURRENCY) as executor:
        for ticker_jobs in grouped_jobs:
            future = executor.submit(
                _run_ticker_job_sequence,
                ticker_jobs,
                project_root,
                workspace_root,
                log_dir,
                timeout_seconds,
            )
            future_map[future] = ticker_jobs
        for future in as_completed(future_map):
            results.extend(future.result())
    return sorted(results, key=lambda item: (item.ticker, item.batch_index))


def _serialize_result(result: ProcessRunResult) -> dict[str, str | int | float | bool | list[str]]:
    """把执行结果序列化为 JSON 友好结构。

    Args:
        result: 单个 ticker 的执行结果。

    Returns:
        JSON 可序列化字典。

    Raises:
        无。
    """

    return {
        "ticker": result.ticker,
        "document_ids": list(result.document_ids),
        "batch_index": result.batch_index,
        "command": list(result.command),
        "return_code": result.return_code,
        "duration_seconds": result.duration_seconds,
        "timed_out": result.timed_out,
        "reported_failed_documents": result.reported_failed_documents,
        "logical_success": _is_successful_result(result),
        "log_path": result.log_path,
    }


def _write_summary(
    *,
    workspace_root: Path,
    tag: str,
    requested_tickers: list[str],
    jobs: list[ProcessJob],
    results: list[ProcessRunResult],
    started_at_epoch: float,
    max_documents_per_job: int,
) -> Path:
    """写出 process 汇总 JSON。

    Args:
        workspace_root: workspace 根目录。
        tag: 执行标签。
        requested_tickers: 入口 ticker 列表。
        jobs: 作业列表。
        results: 执行结果列表。
        started_at_epoch: 启动时间戳。

    Returns:
        汇总文件路径。

    Raises:
        OSError: 文件写入失败时抛出。
    """

    output_dir = workspace_root / "tmp" / DEFAULT_RUNS_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / f"{tag}.json"
    success_count = sum(1 for item in results if _is_successful_result(item))
    timeout_count = sum(1 for item in results if item.timed_out)
    payload = {
        "tag": tag,
        "workspace_root": str(workspace_root),
        "project_root": str(_resolve_project_root()),
        "requested_tickers": requested_tickers,
        "job_count": len(jobs),
        "ticker_count": len({job.ticker for job in jobs}),
        "document_count": sum(len(job.document_ids) for job in jobs),
        "max_workers": DEFAULT_CONCURRENCY,
        "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        "max_documents_per_job": max_documents_per_job,
        "started_at_epoch": started_at_epoch,
        "finished_at_epoch": time(),
        "success_count": success_count,
        "failure_count": len(results) - success_count,
        "timeout_count": timeout_count,
        "runs": [_serialize_result(item) for item in results],
    }
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary_path


def _resolve_requested_tickers(
    *,
    workspace_root: Path,
    tickers_arg: str | None,
    documents_json_arg: str | None,
) -> tuple[list[str], dict[str, tuple[str, ...]]]:
    """解析入口 ticker 与文档选择集合。

    Args:
        workspace_root: workspace 根目录。
        tickers_arg: 原始 `--tickers` 参数。
        documents_json_arg: 原始 `--documents-json` 参数。

    Returns:
        `requested_tickers, document_ids_by_ticker` 二元组。

    Raises:
        ValueError: 参数结构非法时抛出。
        OSError: 仓储扫描或文件读取失败时抛出。
    """

    if documents_json_arg is not None:
        entries = _load_document_selector_entries(documents_json_arg)
        grouped = _aggregate_document_ids_by_ticker(entries)
        return sorted(grouped.keys()), grouped

    requested_tickers = _parse_ticker_tokens(tickers_arg)
    if requested_tickers:
        return requested_tickers, {}
    return _discover_available_tickers(workspace_root), {}


def main(argv: list[str] | None = None) -> int:
    """脚本入口。

    Args:
        argv: 命令行参数列表；为 `None` 时读取 `sys.argv`。

    Returns:
        进程退出码；存在失败任务时返回 `1`，否则返回 `0`。

    Raises:
        OSError: 文件系统或子进程执行失败时抛出。
        ValueError: 参数内容非法时抛出。
    """

    args = parse_args(argv)
    workspace_root = _resolve_workspace_root(str(args.base))
    project_root = _resolve_project_root()
    requested_tickers, document_ids_by_ticker = _resolve_requested_tickers(
        workspace_root=workspace_root,
        tickers_arg=args.tickers,
        documents_json_arg=args.documents_json,
    )
    jobs = _build_jobs(
        tickers=requested_tickers,
        document_ids_by_ticker=document_ids_by_ticker,
        max_documents_per_job=int(args.max_documents_per_job),
    )
    log_dir = workspace_root / "tmp" / DEFAULT_LOGS_DIRNAME / str(args.tag)
    started_at_epoch = time()
    results = _run_jobs(
        jobs=jobs,
        project_root=project_root,
        workspace_root=workspace_root,
        log_dir=log_dir,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    )
    summary_path = _write_summary(
        workspace_root=workspace_root,
        tag=str(args.tag),
        requested_tickers=requested_tickers,
        jobs=jobs,
        results=results,
        started_at_epoch=started_at_epoch,
        max_documents_per_job=int(args.max_documents_per_job),
    )
    print(summary_path)
    return 0 if all(_is_successful_result(item) for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
