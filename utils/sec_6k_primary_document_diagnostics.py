#!/usr/bin/env python3
"""运行 SEC 6-K 主文件选文诊断的薄脚本。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_repo_root_on_sys_path() -> None:
    """确保仓库根目录位于 `sys.path`。

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
        sys.path.insert(0, repo_root_str)


_ensure_repo_root_on_sys_path()

from alpha.fins.sec_6k_primary_document_diagnostics import (  # noqa: E402
    DEFAULT_OUTPUT_DIRNAME,
    Sec6KPrimaryDocumentDiagnosticsReport,
    run_sec_6k_primary_document_diagnostics,
)


def _parse_args() -> argparse.Namespace:
    """解析命令行参数。

    Args:
        无。

    Returns:
        参数对象。

    Raises:
        SystemExit: 参数非法时由 argparse 抛出。
    """

    parser = argparse.ArgumentParser(description="运行 SEC 6-K 主文件选文诊断")
    parser.add_argument(
        "--workspace-root",
        default="workspace",
        help="workspace 根目录，默认 `workspace`",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="可选输出目录，默认写入 `workspace/tmp/sec_6k_primary_document_diagnostics/`",
    )
    parser.add_argument(
        "--tickers",
        default=None,
        help="可选 ticker 子集，CSV 格式；只扫描这些 ticker",
    )
    parser.add_argument(
        "--document-ids",
        default=None,
        help="可选 document_id 子集，CSV 格式；只扫描这些 filing",
    )
    return parser.parse_args()


def _parse_csv_argument(raw_value: str | None, *, field_name: str) -> list[str] | None:
    """解析 CSV 形式的可选列表参数。

    Args:
        raw_value: 原始字符串。
        field_name: 字段名，用于错误信息。

    Returns:
        去空后的列表；未传入时返回 `None`。

    Raises:
        ValueError: 传入非空字符串但解析后为空时抛出。
    """

    if raw_value is None:
        return None
    items = [item.strip() for item in raw_value.split(",") if item.strip()]
    if not items:
        raise ValueError(f"{field_name} 不能为空")
    return items


def _resolve_output_dir(workspace_root: Path, output_dir: Path | None) -> Path:
    """解析实际输出目录。

    Args:
        workspace_root: workspace 根目录。
        output_dir: 显式输出目录。

    Returns:
        输出目录绝对路径。

    Raises:
        无。
    """

    if output_dir is not None:
        return output_dir.resolve()
    return workspace_root.resolve() / "tmp" / DEFAULT_OUTPUT_DIRNAME


def _print_report_summary(report: Sec6KPrimaryDocumentDiagnosticsReport, output_dir: Path) -> None:
    """打印诊断摘要。

    Args:
        report: 诊断报告。
        output_dir: 输出目录。

    Returns:
        无。

    Raises:
        无。
    """

    print("SEC 6-K primary_document 诊断完成", flush=True)
    print(f"- 输出目录: {output_dir}", flush=True)
    print(f"- 扫描 active 6-K 数量: {report.analyzed_filing_count}", flush=True)
    print(f"- 主文件错位样本数: {len(report.mismatches)}", flush=True)
    print(f"- 摘要文件: {output_dir / 'summary.md'}", flush=True)


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
    target_tickers = _parse_csv_argument(args.tickers, field_name="tickers")
    target_document_ids = _parse_csv_argument(args.document_ids, field_name="document_ids")
    resolved_output_dir = _resolve_output_dir(workspace_root, output_dir)
    print("开始运行 SEC 6-K primary_document 诊断", flush=True)
    print(f"- workspace_root: {workspace_root}", flush=True)
    print(f"- output_dir: {resolved_output_dir}", flush=True)
    if target_tickers is not None:
        print(f"- target_ticker_count: {len(target_tickers)}", flush=True)
    if target_document_ids is not None:
        print(f"- target_document_count: {len(target_document_ids)}", flush=True)
    report = run_sec_6k_primary_document_diagnostics(
        workspace_root=workspace_root,
        output_dir=output_dir,
        target_tickers=target_tickers,
        target_document_ids=target_document_ids,
    )
    _print_report_summary(report, resolved_output_dir)


if __name__ == "__main__":
    main()