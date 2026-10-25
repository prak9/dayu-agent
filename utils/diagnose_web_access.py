#!/usr/bin/env python3
"""网页访问诊断脚本。

该脚本用于定位「浏览器能打开，但 web tools / requests / Playwright 访问失败」的差异。
它会对同一个 URL 导出以下同源证据：

- 浏览器主文档 request headers 与导航结果；
- `requests` 将发送的 headers 与实际 GET 结果；
- 当前仓库 `fetch_web_page` 的调用结果；
- Playwright 观察到的网络请求摘要。

若站点只能在人工浏览器中访问，可用 headed 模式配合 storage state 导出，
把人工验证后的浏览器状态保存下来，供后续 `fetch_web_page` 复用。

设计目标不是直接修复问题，而是把后续分析所需的原始证据一次性收集完整。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence
from urllib.parse import urlparse

import requests

from alpha.log import Log, LogLevel
from alpha.engine.tool_errors import ToolBusinessError
from alpha.engine.tool_registry import ToolRegistry
from alpha.engine.tools.web_challenge_detection import detect_bot_challenge
from alpha.engine.tools.web_tools import (
    _DEFAULT_BROWSER_USER_AGENT,
    _build_fetch_headers,
    _build_referer,
    _create_fetch_web_page_tool,
    _create_no_retry_session,
    _normalize_url_for_http,
    _resolve_playwright_storage_state_path,
)
from alpha.workspace_paths import CONVERSATION_STORE_RELATIVE_DIR


_DEFAULT_BATCH_OUTPUT_ROOT = Path("workspace/output/web_diagnostics")
_DEFAULT_SESSION_DIR = Path("workspace") / CONVERSATION_STORE_RELATIVE_DIR
_JSONL_SUFFIXES = {".jsonl", ".jsonlines"}


@dataclass(frozen=True)
class DiagnosticUrlEntry:
    """单条批量诊断 URL 样本。"""

    url: str
    label: str = ""
    region: str = ""
    category: str = ""
    notes: str = ""


def _build_argument_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。

    Args:
        无。

    Returns:
        已配置好的参数解析器。

    Raises:
        无。
    """

    parser = argparse.ArgumentParser(description="导出网页抓取差异诊断信息。")
    parser.add_argument("--url", help="待诊断的网页 URL。")
    parser.add_argument("--url-file", help="批量诊断 URL 文件。支持 JSONL 和 TXT。")
    parser.add_argument(
        "--output",
        help="输出 JSON 文件路径。默认写入 workspace/output/web_diagnostics/<slug>.json",
    )
    parser.add_argument(
        "--batch-output-dir",
        help="批量模式输出目录。默认写入 workspace/output/web_diagnostics/<run_label>",
    )
    parser.add_argument(
        "--run-label",
        help="批量模式运行标签。默认使用 UTC 时间戳。",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=12.0,
        help="requests 与 fetch_web_page 使用的基础超时秒数。",
    )
    parser.add_argument(
        "--tool-timeout-budget",
        type=float,
        default=60.0,
        help="调用 fetch_web_page 时的 tool timeout budget。",
    )
    parser.add_argument(
        "--playwright-timeout",
        type=float,
        default=20.0,
        help="Playwright 页面导航超时秒数。",
    )
    parser.add_argument(
        "--browser",
        choices=("chromium", "firefox", "webkit"),
        default="chromium",
        help="Playwright 浏览器类型。",
    )
    parser.add_argument(
        "--channel",
        default="chrome",
        help="Playwright 浏览器 channel；仅 chromium 生效，传空字符串表示不指定。",
    )
    parser.add_argument(
        "--storage-state-in",
        help="可选 Playwright storage state 输入文件；浏览器与 fetch_web_page 都会复用。",
    )
    parser.add_argument(
        "--storage-state-out",
        help="可选 Playwright storage state 输出文件；适合在 headed 模式人工通过验证后保存。",
    )
    parser.add_argument(
        "--storage-state-dir",
        help="按 host 自动读写 storage state 的目录；适合批量诊断时复用人工浏览器状态。",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="以有界面模式启动浏览器，便于人工观察。",
    )
    parser.add_argument(
        "--manual-wait-seconds",
        type=float,
        default=0.0,
        help="headed 模式下在导航后额外等待多少秒，便于人工完成验证后再保存 storage state。",
    )
    parser.add_argument(
        "--pause-before-snapshot",
        action="store_true",
        help="在采样正文和保存 storage state 前等待人工确认，适合人工浏览器完成验证后再继续。",
    )
    parser.add_argument(
        "--max-network",
        type=int,
        default=80,
        help="最多记录多少条网络请求摘要。",
    )
    parser.add_argument(
        "--skip-playwright",
        action="store_true",
        help="跳过 Playwright 浏览器诊断。",
    )
    parser.add_argument(
        "--skip-tool-fetch",
        action="store_true",
        help="跳过仓库内 fetch_web_page 调用。",
    )
    parser.add_argument(
        "--cold-session-dir",
        default=str(_DEFAULT_SESSION_DIR),
        help="每次诊断前要删除的 session 目录；传空字符串表示不清理。",
    )
    return parser


def _default_run_label() -> str:
    """生成默认批量运行标签。

    Args:
        无。

    Returns:
        基于 UTC 时间戳的运行标签。

    Raises:
        无。
    """

    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _slugify_for_filename(url: str) -> str:
    """把 URL 规整成适合文件名的 slug。

    Args:
        url: 原始 URL。

    Returns:
        仅包含安全字符的文件名片段。

    Raises:
        无。
    """

    parsed = urlparse(url)
    raw = f"{parsed.netloc}{parsed.path}".strip("/") or "web_diagnostic"
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", raw)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized or "web_diagnostic"


def _default_output_path(url: str) -> Path:
    """构造默认输出文件路径。

    Args:
        url: 待诊断 URL。

    Returns:
        默认输出文件路径。

    Raises:
        无。
    """

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("workspace/output/web_diagnostics") / f"{_slugify_for_filename(url)}-{timestamp}.json"


def _default_batch_output_dir(run_label: str) -> Path:
    """构造批量诊断默认输出目录。

    Args:
        run_label: 本轮运行标签。

    Returns:
        默认批量输出目录。

    Raises:
        无。
    """

    return _DEFAULT_BATCH_OUTPUT_ROOT / run_label


def _clear_cold_session_dir(path_value: str) -> None:
    """删除冷启动 session 目录。

    Args:
        path_value: session 目录路径。

    Returns:
        无。

    Raises:
        无。
    """

    raw = str(path_value).strip()
    if not raw:
        return
    path = Path(raw).expanduser().resolve()
    if path.exists():
        shutil.rmtree(path)


def _read_url_entries(path: Path) -> list[DiagnosticUrlEntry]:
    """读取批量诊断 URL 样本文件。

    Args:
        path: URL 文件路径。

    Returns:
        去重后的 URL 样本列表。

    Raises:
        ValueError: 文件内容不合法时抛出。
    """

    if path.suffix.lower() in _JSONL_SUFFIXES:
        entries = _read_jsonl_url_entries(path)
    else:
        entries = _read_txt_url_entries(path)
    return _deduplicate_url_entries(entries)


def _read_jsonl_url_entries(path: Path) -> list[DiagnosticUrlEntry]:
    """读取 JSONL URL 样本文件。

    Args:
        path: JSONL 文件路径。

    Returns:
        URL 样本列表。

    Raises:
        ValueError: JSONL 内容不合法时抛出。
    """

    entries: list[DiagnosticUrlEntry] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONL 第 {line_number} 行不是合法 JSON: {exc}") from exc

        if isinstance(payload, str):
            url = payload.strip()
            entries.append(DiagnosticUrlEntry(url=url))
            continue
        if not isinstance(payload, dict):
            raise ValueError(f"JSONL 第 {line_number} 行必须是对象或字符串。")

        url = str(payload.get("url", "")).strip()
        if not url:
            raise ValueError(f"JSONL 第 {line_number} 行缺少 url。")
        entries.append(
            DiagnosticUrlEntry(
                url=url,
                label=str(payload.get("label", "")).strip(),
                region=str(payload.get("region", "")).strip(),
                category=str(payload.get("category", "")).strip(),
                notes=str(payload.get("notes", "")).strip(),
            )
        )
    return entries


def _read_txt_url_entries(path: Path) -> list[DiagnosticUrlEntry]:
    """读取纯文本 URL 样本文件。

    Args:
        path: 纯文本文件路径。

    Returns:
        URL 样本列表。

    Raises:
        无。
    """

    entries: list[DiagnosticUrlEntry] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(DiagnosticUrlEntry(url=line))
    return entries


def _deduplicate_url_entries(entries: Sequence[DiagnosticUrlEntry]) -> list[DiagnosticUrlEntry]:
    """按 URL 去重，保留首次出现的元数据。

    Args:
        entries: 原始 URL 样本列表。

    Returns:
        去重后的 URL 样本列表。

    Raises:
        无。
    """

    deduped: list[DiagnosticUrlEntry] = []
    seen_urls: set[str] = set()
    for entry in entries:
        normalized_url = entry.url.strip()
        if not normalized_url or normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        deduped.append(
            DiagnosticUrlEntry(
                url=normalized_url,
                label=entry.label,
                region=entry.region,
                category=entry.category,
                notes=entry.notes,
            )
        )
    return deduped


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """把结果写入 JSONL 文件。

    Args:
        path: 输出文件路径。
        rows: 行数据序列。

    Returns:
        无。

    Raises:
        OSError: 文件写入失败时抛出。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    if content:
        content = f"{content}\n"
    path.write_text(content, encoding="utf-8")


def _resolve_storage_state_paths(
    *,
    url: str,
    storage_state_in: str,
    storage_state_out: str,
    storage_state_dir: str,
) -> tuple[str, str]:
    """解析单 URL 诊断要使用的 storage state 输入与输出路径。

    Args:
        url: 当前诊断 URL。
        storage_state_in: 显式输入文件路径。
        storage_state_out: 显式输出文件路径。
        storage_state_dir: host 级 storage state 目录。

    Returns:
        `(effective_storage_state_in, effective_storage_state_out)`。

    Raises:
        无。
    """

    normalized_dir = str(storage_state_dir).strip()
    effective_storage_state_in = str(storage_state_in).strip()
    effective_storage_state_out = str(storage_state_out).strip()
    if not normalized_dir:
        return effective_storage_state_in, effective_storage_state_out

    if not effective_storage_state_in:
        effective_storage_state_in = _resolve_playwright_storage_state_path(
            url=url,
            playwright_storage_state_dir=normalized_dir,
        )
    if not effective_storage_state_out:
        host = (urlparse(url).hostname or "").strip().lower()
        if host:
            effective_storage_state_out = str(Path(normalized_dir).expanduser().resolve() / f"{host}.json")
    return effective_storage_state_in, effective_storage_state_out


def _classify_diagnostic_bucket(payload: dict[str, Any]) -> str:
    """按三条访问路径结果给诊断样本分桶。

    Args:
        payload: 单条诊断 JSON。

    Returns:
        粗粒度对比桶名。

    Raises:
        无。
    """

    raw_playwright_profile = payload.get("playwright_profile")
    playwright_profile: dict[str, Any] = raw_playwright_profile if isinstance(raw_playwright_profile, dict) else {}
    raw_requests_profile = payload.get("requests_profile")
    requests_profile: dict[str, Any] = raw_requests_profile if isinstance(raw_requests_profile, dict) else {}
    raw_requests_result = requests_profile.get("result")
    requests_result: dict[str, Any] = raw_requests_result if isinstance(raw_requests_result, dict) else {}
    raw_fetch_profile = payload.get("fetch_web_page_profile")
    fetch_profile: dict[str, Any] = raw_fetch_profile if isinstance(raw_fetch_profile, dict) else {}

    playwright_sampled = not bool(playwright_profile.get("skipped"))
    fetch_sampled = not bool(fetch_profile.get("skipped"))
    playwright_ok = bool(playwright_profile.get("ok"))
    requests_ok = bool(requests_result.get("ok"))
    fetch_ok = bool(fetch_profile.get("ok"))
    challenge_detected = bool(playwright_profile.get("challenge_detected"))

    if not playwright_sampled and not fetch_sampled:
        return "requests_only_sampled"
    if not playwright_sampled or not fetch_sampled:
        return "partial_sample"
    if challenge_detected:
        return "playwright_challenge_detected"
    if playwright_ok and requests_ok and fetch_ok:
        return "all_success"
    if playwright_ok and not requests_ok and not fetch_ok:
        return "browser_only_success"
    if playwright_ok and requests_ok and not fetch_ok:
        return "fetch_only_failure"
    if not playwright_ok and requests_ok and not fetch_ok:
        return "requests_only_success"
    if not playwright_ok and not requests_ok and not fetch_ok:
        return "all_failed"
    if playwright_ok and not requests_ok and fetch_ok:
        return "fetch_outperforms_requests"
    if not playwright_ok and requests_ok and fetch_ok:
        return "requests_and_fetch_success_playwright_failed"
    if not playwright_ok and not requests_ok and fetch_ok:
        return "fetch_only_success"
    return "mixed"


def _count_by_key(rows: Sequence[dict[str, Any]], key: str) -> dict[str, int]:
    """统计字符串字段分布。

    Args:
        rows: 结果行列表。
        key: 待统计字段名。

    Returns:
        计数字典。

    Raises:
        无。
    """

    counts: dict[str, int] = {}
    for row in rows:
        raw_key = str(row.get(key, "") or "").strip() or "<empty>"
        counts[raw_key] = counts.get(raw_key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _build_batch_result_row(
    *,
    entry: DiagnosticUrlEntry,
    diagnostic_path: Path,
    payload: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    """从单条诊断 JSON 提炼批量汇总行。

    Args:
        entry: 输入 URL 样本。
        diagnostic_path: 对应诊断文件路径。
        payload: 单条诊断 JSON。
        index: 输入序号。

    Returns:
        批量结果行。

    Raises:
        无。
    """

    raw_playwright_profile = payload.get("playwright_profile")
    playwright_profile: dict[str, Any] = raw_playwright_profile if isinstance(raw_playwright_profile, dict) else {}
    raw_requests_profile = payload.get("requests_profile")
    requests_profile: dict[str, Any] = raw_requests_profile if isinstance(raw_requests_profile, dict) else {}
    raw_requests_result = requests_profile.get("result")
    requests_result: dict[str, Any] = raw_requests_result if isinstance(raw_requests_result, dict) else {}
    raw_fetch_profile = payload.get("fetch_web_page_profile")
    fetch_profile: dict[str, Any] = raw_fetch_profile if isinstance(raw_fetch_profile, dict) else {}
    raw_playwright_navigation = playwright_profile.get("navigation")
    playwright_navigation: dict[str, Any] = raw_playwright_navigation if isinstance(raw_playwright_navigation, dict) else {}
    raw_challenge_signals = playwright_profile.get("challenge_signals")
    challenge_signals: list[Any] = raw_challenge_signals if isinstance(raw_challenge_signals, list) else []
    comparison_bucket = _classify_diagnostic_bucket(payload)
    playwright_sampled = not bool(playwright_profile.get("skipped"))
    fetch_sampled = not bool(fetch_profile.get("skipped"))
    return {
        "input_index": index,
        "url": entry.url,
        "label": entry.label,
        "region": entry.region,
        "category": entry.category,
        "notes": entry.notes,
        "diagnostic_path": str(diagnostic_path),
        "comparison_bucket": comparison_bucket,
        "playwright_sampled": playwright_sampled,
        "playwright_ok": bool(playwright_profile.get("ok")),
        "playwright_error_type": str(playwright_profile.get("error_type", "") or ""),
        "playwright_response_status": playwright_navigation.get("response_status"),
        "playwright_final_url": str(playwright_navigation.get("final_url", entry.url) or entry.url),
        "challenge_detected": bool(playwright_profile.get("challenge_detected")),
        "challenge_signals": list(challenge_signals),
        "page_text_length": int(playwright_profile.get("page_text_length", 0) or 0),
        "requests_ok": bool(requests_result.get("ok")),
        "requests_status_code": requests_result.get("status_code"),
        "requests_error_type": str(requests_result.get("error_type", "") or ""),
        "fetch_sampled": fetch_sampled,
        "fetch_ok": bool(fetch_profile.get("ok")),
        "fetch_error_code": str(fetch_profile.get("error_code", "") or ""),
        "fetch_error_type": str(fetch_profile.get("error_type", "") or ""),
        "fetch_final_url": str(fetch_profile.get("final_url", entry.url) or entry.url),
    }


def _build_batch_summary(
    *,
    run_label: str,
    input_path: Path,
    rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """构造批量诊断汇总。

    Args:
        run_label: 本轮运行标签。
        input_path: 输入 URL 文件路径。
        rows: 结果行列表。

    Returns:
        汇总字典。

    Raises:
        无。
    """

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_label": run_label,
        "input_file": str(input_path),
        "input_url_count": len(rows),
        "playwright_sampled_count": sum(1 for row in rows if row.get("playwright_sampled")),
        "playwright_ok_count": sum(1 for row in rows if row.get("playwright_sampled") and row.get("playwright_ok")),
        "requests_ok_count": sum(1 for row in rows if row.get("requests_ok")),
        "fetch_sampled_count": sum(1 for row in rows if row.get("fetch_sampled")),
        "fetch_ok_count": sum(1 for row in rows if row.get("fetch_sampled") and row.get("fetch_ok")),
        "challenge_detected_count": sum(1 for row in rows if row.get("playwright_sampled") and row.get("challenge_detected")),
        "comparison_buckets": _count_by_key(rows, "comparison_bucket"),
        "playwright_error_types": _count_by_key(
            [row for row in rows if row.get("playwright_sampled") and not row.get("playwright_ok")],
            "playwright_error_type",
        ),
        "requests_error_types": _count_by_key(
            [row for row in rows if not row.get("requests_ok")],
            "requests_error_type",
        ),
        "fetch_error_codes": _count_by_key(
            [row for row in rows if row.get("fetch_sampled") and not row.get("fetch_ok")],
            "fetch_error_code",
        ),
    }


def _build_batch_summary_markdown(summary: dict[str, Any]) -> str:
    """构造批量诊断 Markdown 汇总。

    Args:
        summary: 汇总字典。

    Returns:
        Markdown 文本。

    Raises:
        无。
    """

    lines = [
        f"# Diagnose Web Access Batch Summary - {summary['run_label']}",
        "",
        f"- 生成时间：{summary['generated_at']}",
        f"- 输入文件：{summary['input_file']}",
        f"- URL 数量：{summary['input_url_count']}",
        f"- Playwright 已采样：{summary['playwright_sampled_count']}",
        f"- Playwright 成功：{summary['playwright_ok_count']}",
        f"- requests 成功：{summary['requests_ok_count']}",
        f"- fetch_web_page 已采样：{summary['fetch_sampled_count']}",
        f"- fetch_web_page 成功：{summary['fetch_ok_count']}",
        f"- 检测到 challenge：{summary['challenge_detected_count']}",
        "",
        "## Comparison Buckets",
        "",
    ]
    for key, value in summary["comparison_buckets"].items():
        lines.append(f"- {key}: {value}")
    if not summary["comparison_buckets"]:
        lines.append("- 无")

    lines.extend(["", "## Playwright Error Types", ""])
    for key, value in summary["playwright_error_types"].items():
        lines.append(f"- {key}: {value}")
    if not summary["playwright_error_types"]:
        lines.append("- 无")

    lines.extend(["", "## Requests Error Types", ""])
    for key, value in summary["requests_error_types"].items():
        lines.append(f"- {key}: {value}")
    if not summary["requests_error_types"]:
        lines.append("- 无")

    lines.extend(["", "## Fetch Error Codes", ""])
    for key, value in summary["fetch_error_codes"].items():
        lines.append(f"- {key}: {value}")
    if not summary["fetch_error_codes"]:
        lines.append("- 无")
    return "\n".join(lines) + "\n"


def _build_single_diagnostic_payload(args: argparse.Namespace) -> dict[str, Any]:
    """构造单 URL 诊断载荷。

    Args:
        args: 命令行参数。

    Returns:
        单条诊断 JSON 载荷。

    Raises:
        ValueError: URL 缺失时抛出。
    """

    if not str(args.url or "").strip():
        raise ValueError("单 URL 模式必须提供 --url。")

    _clear_cold_session_dir(args.cold_session_dir)
    effective_storage_state_in, effective_storage_state_out = _resolve_storage_state_paths(
        url=args.url,
        storage_state_in=args.storage_state_in or "",
        storage_state_out=args.storage_state_out or "",
        storage_state_dir=args.storage_state_dir or "",
    )
    effective_storage_state_path = effective_storage_state_in or effective_storage_state_out
    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "url": args.url,
    }
    if args.skip_playwright:
        payload["playwright_profile"] = {"skipped": True}
    else:
        payload["playwright_profile"] = _build_playwright_profile(
            args.url,
            browser_name=args.browser,
            channel=args.channel.strip(),
            headed=args.headed,
            timeout_seconds=args.playwright_timeout,
            max_network=max(1, args.max_network),
            storage_state_in=effective_storage_state_in,
            storage_state_out=effective_storage_state_out,
            manual_wait_seconds=max(0.0, args.manual_wait_seconds),
            pause_before_snapshot=bool(args.pause_before_snapshot),
        )
    if args.skip_tool_fetch:
        payload["fetch_web_page_profile"] = {"skipped": True}
    else:
        payload["fetch_web_page_profile"] = _build_tool_fetch_profile(
            args.url,
            request_timeout_seconds=args.request_timeout,
            tool_timeout_budget=args.tool_timeout_budget,
            playwright_storage_state_dir=_storage_state_dir_from_path(effective_storage_state_path),
        )
    payload["requests_profile"] = _build_requests_profile(args.url, args.request_timeout)
    return payload


def _run_single_diagnose(args: argparse.Namespace) -> int:
    """执行单 URL 诊断并写文件。

    Args:
        args: 命令行参数。

    Returns:
        退出码。0 表示成功。

    Raises:
        无。
    """

    output_path = Path(args.output) if args.output else _default_output_path(args.url)
    payload = _build_single_diagnostic_payload(args)
    _write_json(output_path, payload)
    Log.info(f"诊断结果已写入: {output_path}")
    return 0


def _build_batch_child_command(
    *,
    entry: DiagnosticUrlEntry,
    diagnostic_path: Path,
    args: argparse.Namespace,
) -> list[str]:
    """构造批量模式下单 URL 子进程命令。

    Args:
        entry: 当前 URL 样本。
        diagnostic_path: 目标诊断文件路径。
        args: 顶层命令行参数。

    Returns:
        子进程命令数组。

    Raises:
        无。
    """

    command = [
        sys.executable,
        "-m",
        "utils.diagnose_web_access",
        "--url",
        entry.url,
        "--output",
        str(diagnostic_path),
        "--request-timeout",
        str(args.request_timeout),
        "--tool-timeout-budget",
        str(args.tool_timeout_budget),
        "--playwright-timeout",
        str(args.playwright_timeout),
        "--browser",
        args.browser,
        "--channel",
        args.channel,
        "--max-network",
        str(args.max_network),
        "--cold-session-dir",
        str(args.cold_session_dir or ""),
    ]
    if str(args.storage_state_dir or "").strip():
        command.extend(["--storage-state-dir", str(args.storage_state_dir)])
    if args.headed:
        command.append("--headed")
    if args.pause_before_snapshot:
        command.append("--pause-before-snapshot")
    if args.manual_wait_seconds > 0:
        command.extend(["--manual-wait-seconds", str(args.manual_wait_seconds)])
    if args.skip_playwright:
        command.append("--skip-playwright")
    if args.skip_tool_fetch:
        command.append("--skip-tool-fetch")
    return command


def _run_batch_diagnose(args: argparse.Namespace) -> int:
    """执行批量 URL 诊断流程。

    Args:
        args: 命令行参数。

    Returns:
        退出码。0 表示成功。

    Raises:
        ValueError: 输入 URL 文件缺失或无有效样本时抛出。
    """

    if not str(args.url_file or "").strip():
        raise ValueError("批量模式必须提供 --url-file。")

    input_path = Path(str(args.url_file)).expanduser().resolve()
    if not input_path.is_file():
        raise ValueError(f"URL 文件不存在: {input_path}")

    entries = _read_url_entries(input_path)
    if not entries:
        raise ValueError("URL 文件中没有可用样本。")

    run_label = str(args.run_label or _default_run_label()).strip()
    run_dir = (
        Path(str(args.batch_output_dir)).expanduser().resolve()
        if str(args.batch_output_dir or "").strip()
        else _default_batch_output_dir(run_label).expanduser().resolve()
    )
    diagnostics_dir = run_dir / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(run_dir / "corpus.normalized.jsonl", [asdict(entry) for entry in entries])

    batch_rows: list[dict[str, Any]] = []
    interactive_mode = bool(args.headed or args.pause_before_snapshot or args.manual_wait_seconds > 0)
    for index, entry in enumerate(entries, start=1):
        diagnostic_path = diagnostics_dir / f"{index:04d}-{_slugify_for_filename(entry.url)}.json"
        Log.info(f"[diagnose {index}/{len(entries)}] {entry.url}")
        command = _build_batch_child_command(entry=entry, diagnostic_path=diagnostic_path, args=args)
        if interactive_mode:
            completed = subprocess.run(command, check=False)
        else:
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"批量诊断子进程失败: {entry.url} (exit={completed.returncode})")
        payload = json.loads(diagnostic_path.read_text(encoding="utf-8"))
        row = _build_batch_result_row(
            entry=entry,
            diagnostic_path=diagnostic_path,
            payload=payload,
            index=index,
        )
        batch_rows.append(row)

    _write_jsonl(run_dir / "results.jsonl", batch_rows)
    summary = _build_batch_summary(run_label=run_label, input_path=input_path, rows=batch_rows)
    _write_json(run_dir / "summary.json", summary)
    (run_dir / "summary.md").write_text(_build_batch_summary_markdown(summary), encoding="utf-8")
    Log.info(f"批量诊断结果已写入: {run_dir}")
    return 0


def _storage_state_dir_from_path(path_value: str) -> str:
    """从 storage state 文件路径推导目录路径。

    Args:
        path_value: storage state 文件路径。

    Returns:
        父目录绝对路径；空值时返回空字符串。

    Raises:
        无。
    """

    raw = str(path_value).strip()
    if not raw:
        return ""
    return str(Path(raw).expanduser().resolve().parent)


def _json_safe_headers(headers: Any) -> dict[str, str]:
    """把 headers 映射规整为 JSON 可序列化字典。

    Args:
        headers: 任意 header 映射。

    Returns:
        仅包含字符串键值的字典。

    Raises:
        无。
    """

    if not headers:
        return {}
    return {str(key): str(value) for key, value in dict(headers).items()}


def _wait_for_manual_confirmation(prompt_text: str) -> None:
    """等待人工确认后继续采样页面状态。

    Args:
        prompt_text: 终端提示文本。

    Returns:
        无。

    Raises:
        无。
    """

    try:
        input(prompt_text)
    except EOFError:
        print("[诊断] 当前 stdin 不可交互，跳过人工确认等待。")


def _build_requests_profile(url: str, timeout_seconds: float) -> dict[str, Any]:
    """构建 requests 侧诊断信息。

    Args:
        url: 待访问 URL。
        timeout_seconds: GET 请求超时秒数。

    Returns:
        requests 预备 headers 与实际请求结果。

    Raises:
        无。
    """

    normalized_url = _normalize_url_for_http(url)
    session = _create_no_retry_session()
    headers = _build_fetch_headers(normalized_url)
    headers["Referer"] = _build_referer(normalized_url)
    prepared_request = requests.Request("GET", normalized_url, headers=headers)
    prepared = session.prepare_request(prepared_request)
    profile: dict[str, Any] = {
        "normalized_url": normalized_url,
        "prepared_headers": _json_safe_headers(prepared.headers),
        "timeout_seconds": timeout_seconds,
    }
    started_at = time.perf_counter()
    try:
        response = session.send(
            prepared,
            timeout=timeout_seconds,
            allow_redirects=True,
        )
    except Exception as exc:
        profile["result"] = {
            "ok": False,
            "error_type": type(exc).__name__,
            "error_module": type(exc).__module__,
            "message": str(exc),
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        }
    else:
        profile["result"] = {
            "ok": True,
            "status_code": response.status_code,
            "final_url": response.url,
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
            "response_headers": _json_safe_headers(response.headers),
            "text_prefix": (response.text or "")[:500],
        }
    finally:
        session.close()
    return profile


def _build_tool_fetch_profile(
    url: str,
    request_timeout_seconds: float,
    tool_timeout_budget: float,
    playwright_storage_state_dir: str = "",
) -> dict[str, Any]:
    """构建仓库内 fetch_web_page 的调用诊断。

    Args:
        url: 待访问 URL。
        request_timeout_seconds: 基础请求超时秒数。
        tool_timeout_budget: fetch_web_page 的工具预算。
        playwright_storage_state_dir: 可选 storage state 目录。

    Returns:
        fetch_web_page 的成功或失败结果。

    Raises:
        无。
    """

    registry = ToolRegistry()
    _, fetch_web_page, _ = _create_fetch_web_page_tool(
        registry,
        request_timeout_seconds=request_timeout_seconds,
        fetch_truncate_chars=80_000,
        timeout_budget=tool_timeout_budget,
        playwright_storage_state_dir=playwright_storage_state_dir,
    )
    started_at = time.perf_counter()
    try:
        result = fetch_web_page(url=url)
    except ToolBusinessError as exc:
        return {
            "ok": False,
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
            "error_code": exc.code,
            "message": exc.message,
            "hint": exc.hint,
            "extra": exc.extra,
        }
    except Exception as exc:  # pragma: no cover - 仅作脚本兜底
        return {
            "ok": False,
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    return {
        "ok": True,
        "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        "title": result.get("title", ""),
        "final_url": result.get("final_url", url),
        "content_prefix": (result.get("content") or "")[:500],
    }


def _build_playwright_profile(
    url: str,
    *,
    browser_name: str,
    channel: str,
    headed: bool,
    timeout_seconds: float,
    max_network: int,
    storage_state_in: str = "",
    storage_state_out: str = "",
    manual_wait_seconds: float = 0.0,
    pause_before_snapshot: bool = False,
) -> dict[str, Any]:
    """构建 Playwright 浏览器侧诊断信息。

    Args:
        url: 待访问 URL。
        browser_name: 浏览器类型。
        channel: 浏览器 channel。
        headed: 是否启用有界面模式。
        timeout_seconds: 页面导航超时秒数。
        max_network: 最多记录的网络请求数。
        storage_state_in: 可选 storage state 输入文件路径。
        storage_state_out: 可选 storage state 输出文件路径。
        manual_wait_seconds: 导航后额外等待秒数，便于人工完成验证。
        pause_before_snapshot: 是否在采样正文和保存 storage state 前等待人工确认。

    Returns:
        浏览器环境、主文档 request headers 与网络请求摘要。

    Raises:
        无。
    """

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - 本地缺依赖时的兜底
        return {
            "ok": False,
            "error_type": "ImportError",
            "message": str(exc),
        }

    try:
        from playwright_stealth import Stealth
    except ImportError:
        Stealth = None  # type: ignore[assignment]

    network_entries: list[dict[str, Any]] = []
    entry_map: dict[int, dict[str, Any]] = {}
    main_document_request: dict[str, Any] | None = None
    main_document_response: dict[str, Any] | None = None
    result: dict[str, Any] = {
        "ok": False,
        "browser": browser_name,
        "channel": channel or None,
        "headed": headed,
        "timeout_seconds": timeout_seconds,
    }

    def _handle_request(request: Any) -> None:
        """记录请求摘要与主文档请求头。"""

        nonlocal main_document_request
        entry = {
            "method": request.method,
            "url": request.url,
            "resource_type": request.resource_type,
            "is_navigation_request": request.is_navigation_request(),
        }
        if len(network_entries) < max_network:
            network_entries.append(entry)
            entry_map[id(request)] = entry
        if (
            main_document_request is None
            and request.resource_type == "document"
            and request.is_navigation_request()
        ):
            main_document_request = {
                "method": request.method,
                "url": request.url,
                "headers": _json_safe_headers(request.headers),
            }

    def _handle_response(response: Any) -> None:
        """补充响应状态与主文档响应头。"""

        nonlocal main_document_response
        entry = entry_map.get(id(response.request))
        if entry is not None:
            entry["status"] = response.status
        if (
            main_document_response is None
            and response.request.resource_type == "document"
            and response.request.is_navigation_request()
        ):
            main_document_response = {
                "status": response.status,
                "url": response.url,
                "headers": _json_safe_headers(response.headers),
            }

    def _handle_request_failed(request: Any) -> None:
        """补充请求失败信息。"""

        entry = entry_map.get(id(request))
        if entry is not None:
            failure = request.failure
            entry["failure"] = failure if isinstance(failure, str) else str(failure)

    with sync_playwright() as pw:
        browser_type = getattr(pw, browser_name)
        launch_kwargs: dict[str, Any] = {"headless": not headed}
        if browser_name == "chromium" and channel:
            launch_kwargs["channel"] = channel
        started_at = time.perf_counter()
        try:
            browser = browser_type.launch(**launch_kwargs)
        except Exception as exc:
            result.update(
                {
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "elapsed_seconds": round(time.perf_counter() - started_at, 3),
                }
            )
            return result

        try:
            context_kwargs: dict[str, Any] = {
                "viewport": {"width": 1280, "height": 800},
                "user_agent": _DEFAULT_BROWSER_USER_AGENT,
                "locale": "zh-CN",
                "accept_downloads": False,
            }
            if storage_state_in:
                context_kwargs["storage_state"] = storage_state_in
            context = browser.new_context(
                **context_kwargs,
            )
            page = context.new_page()
            page.on("request", _handle_request)
            page.on("response", _handle_response)
            page.on("requestfailed", _handle_request_failed)
            if Stealth is not None:
                Stealth().apply_stealth_sync(page)

            navigation_response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=int(timeout_seconds * 1000),
            )
            page.wait_for_timeout(1000)
            if manual_wait_seconds > 0:
                print(f"[诊断] 等待人工交互 {manual_wait_seconds:.1f}s，可在浏览器中完成验证...")
                page.wait_for_timeout(int(manual_wait_seconds * 1000))
            if pause_before_snapshot:
                _wait_for_manual_confirmation("[诊断] 完成人工验证后按回车继续采样页面状态... ")
            page_text = page.evaluate("() => document.body ? document.body.innerText : ''")
            page_html = page.content()
            challenge = detect_bot_challenge(
                response=None,
                response_headers=(main_document_response or {}).get("headers", {}),
                http_status=navigation_response.status if navigation_response is not None else None,
                content_text=page_text or page_html,
            )
            if storage_state_out:
                output_path = Path(storage_state_out).expanduser()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(output_path))
            result.update(
                {
                    "ok": True,
                    "elapsed_seconds": round(time.perf_counter() - started_at, 3),
                    "browser_version": browser.version,
                    "main_document_request": main_document_request,
                    "main_document_response": main_document_response,
                    "navigation": {
                        "response_status": navigation_response.status if navigation_response is not None else None,
                        "final_url": page.url,
                        "title": page.title(),
                        "user_agent": page.evaluate("() => navigator.userAgent"),
                    },
                    "page_text_prefix": page_text[:500],
                    "page_text_length": len(page_text),
                    "page_html_prefix": page_html[:500],
                    "page_html_length": len(page_html),
                    "challenge_detected": challenge.challenge_detected,
                    "challenge_signals": list(challenge.challenge_signals),
                    "storage_state_in": storage_state_in or None,
                    "storage_state_out": storage_state_out or None,
                    "network_requests": network_entries,
                    "network_request_count": len(network_entries),
                }
            )
        except Exception as exc:
            result.update(
                {
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "elapsed_seconds": round(time.perf_counter() - started_at, 3),
                    "main_document_request": main_document_request,
                    "main_document_response": main_document_response,
                    "network_requests": network_entries,
                    "network_request_count": len(network_entries),
                }
            )
        finally:
            browser.close()
    return result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """把诊断结果写入 JSON 文件。

    Args:
        path: 输出文件路径。
        payload: 诊断结果。

    Returns:
        无。

    Raises:
        OSError: 文件写入失败时抛出。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> int:
    """脚本入口。

    Args:
        argv: 可选命令行参数列表。

    Returns:
        退出码。0 表示成功，其余为失败。

    Raises:
        无。
    """
    Log.set_level(LogLevel.INFO)

    parser = _build_argument_parser()
    args = parser.parse_args(argv)
    has_single_url = bool(str(args.url or "").strip())
    has_url_file = bool(str(args.url_file or "").strip())
    if has_single_url and has_url_file:
        raise ValueError("--url 和 --url-file 不能同时提供。")
    if not has_single_url and not has_url_file:
        raise ValueError("必须提供 --url 或 --url-file 之一。")
    if has_url_file:
        return _run_batch_diagnose(args)
    return _run_single_diagnose(args)


if __name__ == "__main__":
    sys.exit(main())
