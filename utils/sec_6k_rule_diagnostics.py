#!/usr/bin/env python3
"""运行 SEC 6-K 规则诊断闭环的薄脚本。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def _ensure_repo_root_on_sys_path() -> None:
    """确保仓库根目录位于 `sys.path`。

    直接以 `python utils/sec_6k_rule_diagnostics.py` 运行脚本时，
    Python 只会自动把 `utils/` 目录加入 `sys.path`，此时无法导入同级仓库
    下的 `alpha` 包。这里把仓库根目录补入模块搜索路径，保证脚本与
    `python -m` 运行方式行为一致。

    Args:
        无。

    Returns:
        无。

    Raises:
        无。
    """

    repo_root = Path(__file__).resolve().parents[1]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        # 保持仓库根目录优先，确保导入当前工作区代码而不是外部同名包。
        sys.path.insert(0, repo_root_str)


_ensure_repo_root_on_sys_path()

from alpha.fins.sec_6k_rule_diagnostics import (
    DEFAULT_OUTPUT_DIRNAME,
    ProcessProgressUpdate,
    Sec6KRuleDiagnosticsReport,
    run_sec_6k_rule_diagnostics,
)


def _parse_args() -> argparse.Namespace:
    """解析命令行参数。

    Args:
        无。

    Returns:
        解析后的参数对象。

    Raises:
        SystemExit: 参数非法时由 argparse 抛出。
    """

    parser = argparse.ArgumentParser(description="运行 SEC 6-K 规则诊断闭环")
    parser.add_argument(
        "--workspace-root",
        default="workspace",
        help="workspace 根目录，默认 `workspace`",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="可选输出目录，默认写入 `workspace/tmp/sec_6k_rule_diagnostics/`",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=26,
        help="`process --ci --overwrite` 最大并发数，默认 26",
    )
    parser.add_argument(
        "--tickers",
        default=None,
        help="可选 ticker 子集，CSV 格式；只对这些 ticker 运行诊断",
    )
    return parser.parse_args()


def _parse_target_tickers(raw_tickers: str | None) -> list[str] | None:
    """解析命令行传入的 ticker 子集。

    Args:
        raw_tickers: 原始 CSV 字符串，可为空。

    Returns:
        规范化后的 ticker 列表；未传入时返回 `None`。

    Raises:
        ValueError: 传入非空字符串但解析后为空时抛出。
    """

    if raw_tickers is None:
        return None
    tickers = [item.strip().upper() for item in raw_tickers.split(",") if item.strip()]
    if not tickers:
        raise ValueError("tickers 不能为空")
    normalized_tickers: list[str] = []
    for ticker in tickers:
        if ticker in normalized_tickers:
            continue
        normalized_tickers.append(ticker)
    return normalized_tickers


def _resolve_output_dir(workspace_root: Path, output_dir: Path | None) -> Path:
    """解析诊断输出目录。

    Args:
        workspace_root: workspace 根目录。
        output_dir: 命令行显式传入的输出目录，可为空。

    Returns:
        实际输出目录绝对路径。

    Raises:
        无。
    """

    if output_dir is not None:
        return output_dir.resolve()
    return workspace_root.resolve() / "tmp" / DEFAULT_OUTPUT_DIRNAME


def _print_report_summary(report: Sec6KRuleDiagnosticsReport, output_dir: Path) -> None:
    """打印诊断摘要。

    Args:
        report: 诊断报告。
        output_dir: 实际输出目录。

    Returns:
        无。

    Raises:
        无。
    """

    failed_runs = [item for item in report.process_runs if item.return_code != 0]
    print("SEC 6-K 规则诊断完成", flush=True)
    print(f"- 输出目录: {output_dir}", flush=True)
    print(f"- 20-F ticker 数量: {len(report.twenty_f_tickers)}", flush=True)
    print(f"- 非季报误落盘样本数: {len(report.false_positive_6k)}", flush=True)
    print(f"- 季报误 reject ticker 数量: {len(report.false_negative_6k)}", flush=True)
    print(f"- process 失败 ticker 数量: {len(failed_runs)}", flush=True)
    print(f"- 摘要文件: {output_dir / 'summary.md'}", flush=True)


def _print_process_progress(update: ProcessProgressUpdate) -> None:
    """打印单个 ticker 的 process 进度。

    Args:
        update: 进度更新事件。

    Returns:
        无。

    Raises:
        无。
    """

    if update.phase == "started":
        print(
            f"[process:start] ticker={update.ticker} document_count={len(update.document_ids)}",
            flush=True,
        )
        return
    print(
        (
            f"[process:end] ticker={update.ticker} "
            f"document_count={len(update.document_ids)} "
            f"return_code={update.return_code} "
            f"log_path={update.log_path or '-'}"
        ),
        flush=True,
    )


def main() -> None:
    """脚本入口。

    Args:
        无。

    Returns:
        无。

    Raises:
        OSError: 诊断输出写入失败时抛出。
    """

    args = _parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    output_dir = Path(args.output_dir) if args.output_dir else None
    target_tickers = _parse_target_tickers(args.tickers)
    resolved_output_dir = _resolve_output_dir(workspace_root, output_dir)
    print("开始运行 SEC 6-K 规则诊断", flush=True)
    print(f"- workspace_root: {workspace_root}", flush=True)
    print(f"- output_dir: {resolved_output_dir}", flush=True)
    print(f"- max_concurrency: {args.max_concurrency}", flush=True)
    if target_tickers is not None:
        print(f"- target_ticker_count: {len(target_tickers)}", flush=True)
    report = asyncio.run(
        run_sec_6k_rule_diagnostics(
            workspace_root=workspace_root,
            output_dir=output_dir,
            max_concurrency=args.max_concurrency,
            target_tickers=target_tickers,
            progress_reporter=_print_process_progress,
        )
    )
    _print_report_summary(report, resolved_output_dir)


if __name__ == "__main__":
    main()
