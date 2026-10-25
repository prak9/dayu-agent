"""证据锚点重写纯函数模块。

本模块负责根据证据复核（confirm）结果机械重写 evidence line，
包括 Financial Statement 行补强、同一 filing 锚点修正、以及
重写后的程序化后验校验。
"""

from __future__ import annotations

import re
from typing import Any

from alpha.services.internal.write_pipeline.audit_formatting import (
    _extract_evidence_section_block,
    _normalize_line_for_match,
    _replace_evidence_section_block,
)
from alpha.services.internal.write_pipeline.audit_rules import (
    _run_programmatic_audits,
)
from alpha.services.internal.write_pipeline.enums import EvidenceConfirmationStatus
from alpha.services.internal.write_pipeline.models import (
    EvidenceAnchorFix,
    EvidenceConfirmationEntry,
    EvidenceConfirmationResult,
)
from alpha.services.internal.write_pipeline.source_list_builder import (
    extract_evidence_items,
)

def _has_anchor_rewrite_candidates(confirmation_result: EvidenceConfirmationResult) -> bool:
    """判断本轮证据复核结果是否包含可机械回写的锚点问题。

    Args:
        confirmation_result: 当前 confirm 结果。

    Returns:
        若存在 `supported_but_anchor_too_coarse` 或
        `supported_elsewhere_in_same_filing` 条目，返回 ``True``；
        否则返回 ``False``。

    Raises:
        无。
    """

    if not confirmation_result.entries:
        return False
    rewrite_statuses = {
        EvidenceConfirmationStatus.SUPPORTED_BUT_ANCHOR_TOO_COARSE,
        EvidenceConfirmationStatus.SUPPORTED_ELSEWHERE_IN_SAME_FILING,
    }
    return any(entry.status in rewrite_statuses for entry in confirmation_result.entries)


def _extract_anchor_locator_from_hint(text: str) -> str:
    """从 confirm 提示中抽取可直接落盘的定位路径。

    Args:
        text: confirm 的 `rewrite_hint` 或 `reason`。

    Returns:
        可直接放入 evidence line 的 locator；无法抽取时返回空字符串。

    Raises:
        无。
    """

    full_line_match = re.search(r"将证据条目更改为：\s*(.+)$", text)
    if full_line_match is not None:
        return full_line_match.group(1).strip()
    path_match = re.search(
        r"(Part [A-Za-z0-9 .,:()'’/\\-]+(?: \| [A-Za-z0-9 .,:()'’/\\-]+)*)",
        text,
    )
    if path_match is not None:
        return path_match.group(1).strip()
    return ""


def _build_anchor_locator_from_fix(anchor_fix: EvidenceAnchorFix | None) -> str:
    """从结构化锚点修复信息中构造可落盘的 locator。

    Args:
        anchor_fix: 结构化锚点修复信息。

    Returns:
        可直接拼入 evidence line 的 locator；无法构造时返回空字符串。

    Raises:
        无。
    """

    if anchor_fix is None:
        return ""
    if anchor_fix.kind == "same_filing_evidence_line":
        return anchor_fix.evidence_line.strip()
    if anchor_fix.kind == "same_filing_section":
        return anchor_fix.section_path.strip()
    return ""


def _extract_statement_type_from_hint(*, rewrite_hint: str, reason: str) -> str:
    """从 confirm 提示中抽取目标财务报表类型。

    Args:
        rewrite_hint: confirm 的 `rewrite_hint`。
        reason: confirm 的 `reason`。

    Returns:
        `income` / `cash_flow` / `balance_sheet` 等报表类型；失败返回空字符串。

    Raises:
        无。
    """

    combined = f"{rewrite_hint}\n{reason}"
    match = re.search(r"Financial Statement:([A-Za-z_]+)", combined)
    if match is None:
        return ""
    return match.group(1).strip()


def _extract_period_value_from_hint(*, rewrite_hint: str, reason: str) -> str:
    """从 confirm 提示中抽取期次配置。

    Args:
        rewrite_hint: confirm 的 `rewrite_hint`。
        reason: confirm 的 `reason`。

    Returns:
        `FY2025,FY2024` 这类 period 串；失败返回空字符串。

    Raises:
        无。
    """

    combined = f"{rewrite_hint}\n{reason}"
    match = re.search(r"Periods?:([A-Za-z0-9_,]+)", combined)
    if match is None:
        return ""
    return match.group(1).strip()


def _extract_rows_from_hint(*, rewrite_hint: str, reason: str) -> list[str]:
    """从 confirm 提示中抽取需要补入的财务报表行标签。

    Args:
        rewrite_hint: confirm 的 `rewrite_hint`。
        reason: confirm 的 `reason`。

    Returns:
        需要补入的行标签列表；无法抽取时返回空列表。

    Raises:
        无。
    """

    rows: list[str] = []
    combined = f"{rewrite_hint}\n{reason}"

    rows_match = re.search(r"Rows:\s*([^\n。；\"]+)", combined)
    if rows_match is not None:
        for item in rows_match.group(1).split(","):
            normalized = item.strip().strip("。；，")
            if normalized and normalized not in rows:
                rows.append(normalized)

    quoted_rows = re.findall(r"[“\"]([^”\"]+)[”\"]", combined)
    for item in quoted_rows:
        normalized = item.strip()
        if not normalized:
            continue
        if normalized.startswith("Part "):
            continue
        if normalized.startswith("Financial Statement:"):
            continue
        if normalized not in rows:
            rows.append(normalized)
    return rows


def _merge_csv_values(*, existing_value: str, preferred_value: str) -> str:
    """合并逗号分隔字段并保持去重顺序。

    Args:
        existing_value: 当前字段值。
        preferred_value: 需要补入的新字段值。

    Returns:
        合并后的字段值。

    Raises:
        无。
    """

    merged: list[str] = []
    for raw_value in [existing_value, preferred_value]:
        for item in raw_value.split(","):
            normalized = item.strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
    return ",".join(merged)


def _rewrite_financial_statement_evidence_line(
    line: str,
    *,
    statement_type: str,
    period_value: str,
    rows: list[str],
) -> str:
    """按 confirm 提示重写财务报表 evidence line。

    Args:
        line: 当前 evidence line（不含 `- ` 前缀）。
        statement_type: 目标报表类型。
        period_value: 需要补入的 period 串。
        rows: 需要补入的行标签。

    Returns:
        重写后的 evidence line；若该行不匹配目标报表类型则原样返回。

    Raises:
        无。
    """

    parts = [part.strip() for part in line.split(" | ")]
    statement_index = next(
        (index for index, part in enumerate(parts) if part == f"Financial Statement:{statement_type}"),
        None,
    )
    if statement_index is None:
        return line

    updated_parts = list(parts)
    if period_value:
        period_index = next(
            (index for index, part in enumerate(updated_parts) if part.startswith("Period:") or part.startswith("Periods:")),
            None,
        )
        if period_index is not None:
            label = "Periods:" if updated_parts[period_index].startswith("Periods:") else "Period:"
            existing_periods = updated_parts[period_index].split(":", 1)[1].strip()
            merged_periods = _merge_csv_values(existing_value=existing_periods, preferred_value=period_value)
            updated_parts[period_index] = f"{label}{merged_periods}"
        else:
            updated_parts.insert(statement_index + 1, f"Period:{period_value}")

    if rows:
        rows_index = next((index for index, part in enumerate(updated_parts) if part.startswith("Rows:")), None)
        rows_value = ",".join(rows)
        if rows_index is not None:
            existing_rows = updated_parts[rows_index].split(":", 1)[1].strip()
            merged_rows = _merge_csv_values(existing_value=existing_rows, preferred_value=rows_value)
            updated_parts[rows_index] = f"Rows:{merged_rows}"
        else:
            updated_parts.append(f"Rows:{rows_value}")
    return " | ".join(updated_parts)


def _rewrite_evidence_lines_and_collect_resolved_anchor_issues(
    *,
    chapter_markdown: str,
    confirmation_result: EvidenceConfirmationResult,
) -> tuple[list[str], set[str]]:
    """根据 confirm 结果重写 evidence line 列表，并记录被当前 rewrite 吸收的问题。

    该函数只处理当前真正可机械闭环的两类情况：
    - confirm 明确给出完整 evidence line 或稳定 Part/Item 路径；
    - confirm 明确要求在已有 Financial Statement evidence line 上补 period / rows。

    Args:
        chapter_markdown: 当前章节正文。
        confirmation_result: confirm 结果。

    Returns:
        `(重写后的 evidence line 列表, 已被当前 rewrite 吸收的 violation_id 集合)`。

    Raises:
        无。
    """

    evidence_lines = extract_evidence_items(chapter_markdown)
    if not evidence_lines:
        return [], set()

    updated_lines = list(evidence_lines)
    existing_normalized = {_normalize_line_for_match(line) for line in updated_lines}
    resolved_violation_ids: set[str] = set()
    for entry in confirmation_result.entries:
        if entry.status not in {
            EvidenceConfirmationStatus.SUPPORTED_ELSEWHERE_IN_SAME_FILING,
            EvidenceConfirmationStatus.SUPPORTED_BUT_ANCHOR_TOO_COARSE,
        }:
            continue

        entry_resolved = False
        statement_type = ""
        period_value = ""
        rows: list[str] = []
        if entry.anchor_fix is not None and entry.anchor_fix.kind == "same_filing_statement":
            statement_type = entry.anchor_fix.statement_type
            period_value = entry.anchor_fix.period
            rows = list(entry.anchor_fix.rows)
        else:
            statement_type = _extract_statement_type_from_hint(
                rewrite_hint=entry.rewrite_hint,
                reason=entry.reason,
            )
            period_value = _extract_period_value_from_hint(
                rewrite_hint=entry.rewrite_hint,
                reason=entry.reason,
            )
            rows = _extract_rows_from_hint(
                rewrite_hint=entry.rewrite_hint,
                reason=entry.reason,
            )
        if statement_type and (period_value or rows):
            rewritten = False
            for index, line in enumerate(updated_lines):
                rewritten_line = _rewrite_financial_statement_evidence_line(
                    line,
                    statement_type=statement_type,
                    period_value=period_value,
                    rows=rows,
                )
                if rewritten_line != line:
                    old_normalized = _normalize_line_for_match(line)
                    existing_normalized.discard(old_normalized)
                    updated_lines[index] = rewritten_line
                    existing_normalized.add(_normalize_line_for_match(rewritten_line))
                    rewritten = True
                    entry_resolved = True
                    break
            if not rewritten and entry.anchor_fix is not None:
                evidence_prefix = _build_evidence_prefix_from_existing_lines(updated_lines)
                if evidence_prefix:
                    candidate_line = f"{evidence_prefix} | Financial Statement:{statement_type}"
                    if period_value:
                        candidate_line += f" | Period:{period_value}"
                    if rows:
                        candidate_line += f" | Rows:{','.join(rows)}"
                    normalized_line = _normalize_line_for_match(candidate_line)
                    if normalized_line not in existing_normalized:
                        existing_normalized.add(normalized_line)
                        updated_lines.append(candidate_line)
                        entry_resolved = True

        raw_locator = _build_anchor_locator_from_fix(entry.anchor_fix)
        if not raw_locator:
            raw_locator = _extract_anchor_locator_from_hint(entry.rewrite_hint) or _extract_anchor_locator_from_hint(entry.reason)
        if not raw_locator:
            if entry_resolved:
                resolved_violation_ids.add(entry.violation_id)
            continue
        if raw_locator.startswith("SEC EDGAR |") or raw_locator.startswith("Uploaded |"):
            candidate_line = raw_locator.lstrip("- ").strip()
        else:
            preferred_accession_match = re.search(r"Accession (\d{10}-\d{2}-\d{6})", entry.rewrite_hint)
            preferred_accession = preferred_accession_match.group(1) if preferred_accession_match else ""
            evidence_prefix = _build_evidence_prefix_from_existing_lines(
                updated_lines,
                preferred_accession=preferred_accession,
            )
            if not evidence_prefix:
                if entry_resolved:
                    resolved_violation_ids.add(entry.violation_id)
                continue
            candidate_line = f"{evidence_prefix} | {raw_locator}"
        normalized_line = _normalize_line_for_match(candidate_line)
        if normalized_line not in existing_normalized:
            existing_normalized.add(normalized_line)
            updated_lines.append(candidate_line)
            entry_resolved = True
        if entry_resolved:
            resolved_violation_ids.add(entry.violation_id)
    return updated_lines, resolved_violation_ids


def _rewrite_evidence_lines_for_confirmed_anchor_issues(
    *,
    chapter_markdown: str,
    confirmation_result: EvidenceConfirmationResult,
) -> list[str]:
    """根据 confirm 结果重写 evidence line 列表。

    Args:
        chapter_markdown: 当前章节正文。
        confirmation_result: confirm 结果。

    Returns:
        重写后的 evidence line 列表（不含 `- ` 前缀）。

    Raises:
        无。
    """

    rewritten_lines, _resolved_violation_ids = _rewrite_evidence_lines_and_collect_resolved_anchor_issues(
        chapter_markdown=chapter_markdown,
        confirmation_result=confirmation_result,
    )
    return rewritten_lines


def _build_evidence_prefix_from_existing_lines(
    evidence_lines: list[str],
    *,
    preferred_accession: str = "",
) -> str:
    """从现有证据条目中选取一个可复用的 filing 前缀。

    Args:
        evidence_lines: 当前 evidence line 列表。
        preferred_accession: 优先匹配的 accession。

    Returns:
        形如 `SEC EDGAR | Form 10-K | Filed ... | Accession ...` 的前缀；失败返回空字符串。

    Raises:
        无。
    """

    target_accession = preferred_accession.strip()
    candidate_lines = evidence_lines
    if target_accession:
        accession_tag = f"Accession {target_accession}"
        matched = [line for line in evidence_lines if accession_tag in line]
        if matched:
            candidate_lines = matched
    for line in candidate_lines:
        normalized_line = line.strip()
        if normalized_line.startswith("- "):
            normalized_line = normalized_line[2:].strip()
        parts = [part.strip() for part in normalized_line.split(" | ")]
        if len(parts) < 5:
            continue
        return " | ".join(parts[:4])
    return ""


def _build_anchor_rewrite_evidence_lines(
    *,
    chapter_markdown: str,
    confirmation_result: EvidenceConfirmationResult,
) -> list[str]:
    """根据 confirm 结果生成需要补入的更强 evidence line。

    当前只处理“已确认同一 filing 内可支持、但当前锚点缺失/过粗”的最小闭环：
    - `supported_elsewhere_in_same_filing`
    - `supported_but_anchor_too_coarse`

    若 `rewrite_hint` 能提供完整 evidence line，则直接使用；否则尝试从
    `rewrite_hint/reason` 中抽取 `Part ...` 路径，并复用当前 evidence section 的 filing 前缀。

    Args:
        chapter_markdown: 当前章节正文。
        confirmation_result: confirm 结果。

    Returns:
        需要补入 evidence section 的新 evidence line 列表。

    Raises:
        无。
    """

    evidence_lines = extract_evidence_items(chapter_markdown)
    rewritten_lines = _rewrite_evidence_lines_for_confirmed_anchor_issues(
        chapter_markdown=chapter_markdown,
        confirmation_result=confirmation_result,
    )
    if not evidence_lines or not rewritten_lines:
        return []

    original_normalized = {_normalize_line_for_match(line) for line in evidence_lines}
    rewrites: list[str] = []
    for line in rewritten_lines:
        normalized_line = _normalize_line_for_match(line)
        if normalized_line in original_normalized:
            continue
        rewrites.append(f"- {line}")
    return rewrites


def _validate_anchor_rewrite_postconditions(
    *,
    original_chapter_markdown: str,
    rewritten_chapter_markdown: str,
    expected_evidence_lines: list[str],
    skeleton: str,
    allowed_conditional_headings: set[str] | None = None,
) -> str:
    """对证据锚点轻量修复结果执行纯程序化后验校验。

    Args:
        original_chapter_markdown: 修复前章节正文。
        rewritten_chapter_markdown: 修复后章节正文。
        expected_evidence_lines: 期望落盘的 evidence line 列表。
        skeleton: 当前章节骨架。
        allowed_conditional_headings: 允许的条件型可见标题集合。

    Returns:
        通过校验时返回空字符串；失败时返回可读原因。

    Raises:
        无。
    """

    if rewritten_chapter_markdown == original_chapter_markdown:
        return "rewrite 未产生正文差异"

    actual_evidence_lines = extract_evidence_items(rewritten_chapter_markdown)
    if actual_evidence_lines != expected_evidence_lines:
        return "evidence section 与期望重写结果不一致"

    programmatic_fail = _run_programmatic_audits(
        rewritten_chapter_markdown,
        skeleton=skeleton,
        allowed_conditional_headings=allowed_conditional_headings,
    )
    if programmatic_fail is not None:
        return f"程序审计失败: {programmatic_fail.category}"
    return ""

