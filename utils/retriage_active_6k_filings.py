#!/usr/bin/env python3
"""复判 active filings 中被误收的 6-K，并可对称写回 `.rejections/`。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


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

from alpha.fins.active_6k_retriage import retriage_active_6k_filings


def _build_argument_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。

    Args:
        无。

    Returns:
        已配置好的参数解析器。

    Raises:
        无。
    """

    parser = argparse.ArgumentParser(description="复判 active filings 中被误收的 6-K。")
    parser.add_argument("--base", default="workspace", help="workspace 根目录。")
    parser.add_argument("--tickers", help="只扫描指定 ticker，逗号分隔。")
    parser.add_argument("--document-ids", help="只扫描指定 document_id，逗号分隔。")
    parser.add_argument("--apply", action="store_true", help="实际把误收样本写回 .rejections/ 并退出 active。")
    return parser


def _parse_csv_argument(raw_value: Optional[str], *, uppercase: bool) -> Optional[list[str]]:
    """把逗号分隔参数解析成字符串列表。

    Args:
        raw_value: 原始参数值。
        uppercase: 是否转成大写。

    Returns:
        规范化后的列表；若参数为空则返回 `None`。

    Raises:
        无。
    """

    if raw_value is None:
        return None
    items: list[str] = []
    for part in raw_value.split(","):
        normalized = part.strip()
        if not normalized:
            continue
        if uppercase:
            normalized = normalized.upper()
        if normalized not in items:
            items.append(normalized)
    return items or None


def main() -> int:
    """执行 active 6-K 复判命令。

    Args:
        无。

    Returns:
        进程退出码。`0` 表示成功。

    Raises:
        OSError: 仓储读写失败时抛出。
        ValueError: 参数或元数据非法时抛出。
    """

    parser = _build_argument_parser()
    args = parser.parse_args()
    report = retriage_active_6k_filings(
        workspace_root=Path(args.base).resolve(),
        apply=bool(args.apply),
        target_tickers=_parse_csv_argument(args.tickers, uppercase=True),
        target_document_ids=_parse_csv_argument(args.document_ids, uppercase=False),
    )
    rejected_count = sum(1 for item in report.outcomes if item.action == "rejected")
    print(
        json.dumps(
            {
                "workspace_root": report.workspace_root,
                "apply": report.apply,
                "candidate_count": len(report.candidates),
                "rejected_count": rejected_count,
                "outcomes": [
                    {
                        "ticker": item.ticker,
                        "document_id": item.document_id,
                        "action": item.action,
                        "reason": item.reason,
                        "current_classification": item.current_classification,
                    }
                    for item in report.outcomes
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())