"""repair 执行纯函数模块。

本模块是 repair plan 解析与 patch 应用的唯一真源，避免同名逻辑在
其它纯函数模块中再次分叉。
"""

from __future__ import annotations

import json
import re
from typing import Any

from alpha.log import Log
from alpha.services.internal.write_pipeline.enums import (
    RepairResolutionMode,
    RepairTargetKind,
    normalize_repair_target_kind,
)
from alpha.services.internal.write_pipeline.audit_formatting import (
    _extract_markdown_content,
    _find_all_occurrences,
    _find_markdown_section_span,
    _find_normalized_match_spans,
    _heading_exists_in_markdown,
)
from alpha.services.internal.write_pipeline.audit_rules import (
    MODULE,
    RepairPatchApplyRecord,
    RepairPlanApplyResult,
)
from alpha.services.internal.write_pipeline.models import RepairContract


def _extract_fenced_code_block(raw_text: str, language: str) -> str:
    """提取指定语言的 fenced code block 正文。

    Args:
        raw_text: 原始文本。
        language: 目标 fenced block 的语言标签。

    Returns:
        首个匹配代码块的正文；未命中时返回空字符串。

    Raises:
        无。
    """

    pattern = re.compile(rf"```(?:{re.escape(language)})\s*([\s\S]*?)```", re.IGNORECASE)
    match = pattern.search(raw_text)
    if match is None:
        return ""
    return match.group(1).strip()


def _extract_first_json_object_text(raw_text: str) -> str:
    """从混合文本中提取首个顶层 JSON 对象文本。

    Args:
        raw_text: 原始文本。

    Returns:
        首个完整 JSON 对象文本；未命中时返回空字符串。

    Raises:
        无。
    """

    in_string = False
    escape = False
    depth = 0
    start_index: int | None = None
    for index, char in enumerate(raw_text):
        if escape:
            escape = False
            continue
        if char == "\\" and in_string:
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            if depth == 0:
                start_index = index
            depth += 1
            continue
        if char == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start_index is not None:
                return raw_text[start_index:index + 1].strip()
    return ""


def _parse_repair_plan(raw_text: str) -> dict[str, Any]:
    """解析 repair prompt 返回的局部补丁计划。

    Args:
        raw_text: 模型返回的原始文本。

    Returns:
        标准化后的 repair plan 字典。

    Raises:
        ValueError: 当输出格式非法或 patch 字段不完整时抛出。
    """

    candidates = [raw_text.strip()]
    extracted = _extract_markdown_content(raw_text).strip()
    if extracted and extracted not in candidates:
        candidates.append(extracted)
    fenced_json = _extract_fenced_code_block(raw_text, "json")
    if fenced_json and fenced_json not in candidates:
        candidates.append(fenced_json)
    inline_json_object = _extract_first_json_object_text(raw_text)
    if inline_json_object and inline_json_object not in candidates:
        candidates.append(inline_json_object)

    payload: Any | None = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue

    if not isinstance(payload, dict):
        raise ValueError("repair 输出必须是 JSON 对象")
    raw_patches = payload.get("patches")
    if not isinstance(raw_patches, list) or not raw_patches:
        raise ValueError("repair 输出必须包含至少一个 patch")

    patches: list[dict[str, Any]] = []
    for index, raw_patch in enumerate(raw_patches, start=1):
        if not isinstance(raw_patch, dict):
            raise ValueError(f"patch[{index}] 必须是对象")
        target_excerpt = str(raw_patch.get("target_excerpt", "")).strip()
        target_kind_raw = str(raw_patch.get("target_kind", RepairTargetKind.SUBSTRING)).strip() or RepairTargetKind.SUBSTRING
        target_section_heading = str(raw_patch.get("target_section_heading", "")).strip()
        raw_occurrence_index = raw_patch.get("occurrence_index")
        replacement = str(raw_patch.get("replacement", ""))
        reason = str(raw_patch.get("reason", "")).strip()
        if not target_excerpt:
            raise ValueError(f"patch[{index}] 缺少 target_excerpt")
        try:
            target_kind = RepairTargetKind(target_kind_raw)
        except ValueError as exc:
            raise ValueError(f"patch[{index}] target_kind 非法: {target_kind_raw}") from exc
        occurrence_index: int | None = None
        if raw_occurrence_index not in (None, ""):
            try:
                occurrence_index = int(raw_occurrence_index)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"patch[{index}] occurrence_index 必须是正整数") from exc
            if occurrence_index < 1:
                raise ValueError(f"patch[{index}] occurrence_index 必须是正整数")
        patches.append(
            {
                "target_excerpt": target_excerpt,
                "target_kind": target_kind.value,
                "target_section_heading": target_section_heading,
                "occurrence_index": occurrence_index,
                "replacement": replacement,
                "reason": reason,
            }
        )

    raw_notes = payload.get("notes") or []
    notes = [str(item).strip() for item in raw_notes if str(item).strip()]
    return {"patches": patches, "notes": notes}


def _collect_delete_claim_excerpts(*, repair_contract: RepairContract | None) -> list[str]:
    """从修复合同中提取必须删除的 unsupported claim 片段。

    Args:
        repair_contract: 结构化修复合同；为空时视为无约束。

    Returns:
        需要强制删除的 excerpt 列表，保持原顺序且去重。

    Raises:
        无。
    """

    if repair_contract is None:
        return []
    excerpts: list[str] = []
    for action in repair_contract.remediation_actions:
        if action.resolution_mode.strip() != RepairResolutionMode.DELETE_CLAIM.value:
            continue
        excerpt = action.excerpt.strip()
        if excerpt and excerpt not in excerpts:
            excerpts.append(excerpt)
    return excerpts


def _validate_delete_claim_patch(
    *,
    patch_index: int,
    target_excerpt: str,
    target_kind: RepairTargetKind,
    replacement: str,
    delete_claim_excerpts: list[str],
) -> str:
    """校验 delete_claim patch 是否满足稳定删除约束。

    Args:
        patch_index: patch 序号。
        target_excerpt: patch 目标原文。
        target_kind: patch 命中粒度。
        replacement: patch 替换文本。
        delete_claim_excerpts: 当前合同要求删除的 unsupported claim 列表。

    Returns:
        违反约束时返回错误消息；否则返回空字符串。

    Raises:
        无。
    """

    for delete_excerpt in delete_claim_excerpts:
        if delete_excerpt not in target_excerpt:
            continue
        if target_kind == RepairTargetKind.SUBSTRING:
            return f"patch[{patch_index}] delete_claim 不允许使用 substring，请改为 line/bullet/paragraph"
        if delete_excerpt in replacement:
            return f"patch[{patch_index}] delete_claim replacement 仍保留 unsupported claim: {delete_excerpt}"
    return ""


def _apply_repair_plan_with_details(
    *,
    chapter_markdown: str,
    repair_plan: dict[str, Any],
    repair_contract: RepairContract | None = None,
) -> RepairPlanApplyResult:
    """将局部 patch plan 应用到现有章节正文，并返回逐条应用明细。

    Args:
        chapter_markdown: 当前章节正文。
        repair_plan: 结构化 repair patch 计划。
        repair_contract: 当前轮次的结构化修复合同；用于执行硬约束校验。

    Returns:
        包含应用结果、失败统计与逐条 patch 明细的结果对象。

    Raises:
        无。
    """

    patches = repair_plan.get("patches", [])
    delete_claim_excerpts = _collect_delete_claim_excerpts(repair_contract=repair_contract)
    total_patches = len(patches)
    skipped_errors: list[str] = []
    patch_results: list[RepairPatchApplyRecord] = []
    current = chapter_markdown
    applied_count = 0
    for index, patch in enumerate(patches, start=1):
        target_excerpt = str(patch.get("target_excerpt", ""))
        target_kind = normalize_repair_target_kind(
            patch.get("target_kind", RepairTargetKind.SUBSTRING)
        )
        target_section_heading = str(patch.get("target_section_heading", "")).strip()
        occurrence_index = patch.get("occurrence_index")
        replacement = str(patch.get("replacement", ""))
        matched_count = 0
        delete_claim_error = _validate_delete_claim_patch(
            patch_index=index,
            target_excerpt=target_excerpt,
            target_kind=target_kind,
            replacement=replacement,
            delete_claim_excerpts=delete_claim_excerpts,
        )
        if delete_claim_error:
            Log.warning(delete_claim_error, module=MODULE)
            skipped_errors.append(delete_claim_error)
            patch_results.append(
                RepairPatchApplyRecord(
                    index,
                    target_excerpt,
                    target_kind,
                    target_section_heading,
                    occurrence_index,
                    matched_count,
                    "skipped",
                    delete_claim_error,
                )
            )
            continue
        scope_start = 0
        scope_end = len(current)
        if target_section_heading:
            if not _heading_exists_in_markdown(markdown_text=current, heading_text=target_section_heading):
                msg = f"patch[{index}] 未找到真实 section 标题: {target_section_heading}"
                Log.warning(msg, module=MODULE)
                skipped_errors.append(msg)
                patch_results.append(RepairPatchApplyRecord(index, target_excerpt, target_kind, target_section_heading, occurrence_index, matched_count, "skipped", msg))
                continue
            section_span = _find_markdown_section_span(markdown_text=current, heading_text=target_section_heading)
            if section_span is None:
                msg = f"patch[{index}] 未找到 section 标题: {target_section_heading}"
                Log.warning(msg, module=MODULE)
                skipped_errors.append(msg)
                patch_results.append(RepairPatchApplyRecord(index, target_excerpt, target_kind, target_section_heading, occurrence_index, matched_count, "skipped", msg))
                continue
            scope_start, scope_end = section_span
        scope_text = current[scope_start:scope_end]
        exact_match_positions = _find_all_occurrences(scope_text, target_excerpt)
        match_spans = (
            [(pos, pos + len(target_excerpt)) for pos in exact_match_positions]
            if exact_match_positions
            else _find_normalized_match_spans(text=scope_text, target=target_excerpt, target_kind=target_kind)
        )
        match_count = len(match_spans)
        matched_count = match_count
        try:
            if occurrence_index is None:
                if match_count != 1:
                    raise ValueError(f"patch[{index}] 目标片段命中次数异常: expected=1 actual={match_count}")
                match_start, match_end = match_spans[0]
            else:
                if not isinstance(occurrence_index, int) or occurrence_index < 1:
                    raise ValueError(f"patch[{index}] occurrence_index 非法: {occurrence_index}")
                if occurrence_index > match_count:
                    raise ValueError(f"patch[{index}] occurrence_index 超出命中次数: index={occurrence_index} actual={match_count}")
                match_start, match_end = match_spans[occurrence_index - 1]
        except ValueError as exc:
            msg = str(exc)
            Log.warning(msg, module=MODULE)
            skipped_errors.append(msg)
            patch_results.append(RepairPatchApplyRecord(index, target_excerpt, target_kind, target_section_heading, occurrence_index, matched_count, "skipped", msg))
            continue
        absolute_start = scope_start + match_start
        absolute_end = scope_start + match_end
        if _is_forbidden_evidence_modification(
            markdown_text=current,
            target_excerpt=current[absolute_start:absolute_end],
            replacement=replacement,
            absolute_start=absolute_start,
            absolute_end=absolute_end,
        ):
            msg = f"patch[{index}] 禁止修改证据小节: {target_excerpt}"
            Log.warning(msg, module=MODULE)
            skipped_errors.append(msg)
            patch_results.append(RepairPatchApplyRecord(index, target_excerpt, target_kind, target_section_heading, occurrence_index, matched_count, "skipped", msg))
            continue
        current = current[:absolute_start] + replacement + current[absolute_end:]
        applied_count += 1
        patch_results.append(RepairPatchApplyRecord(index, target_excerpt, target_kind, target_section_heading, occurrence_index, matched_count, "applied", ""))
    current = _cleanup_repair_markdown(current)
    all_failed = total_patches > 0 and applied_count == 0
    error_message = ""
    if all_failed:
        error_message = f"所有 {total_patches} 个 patch 均失败: " + "; ".join(skipped_errors)
    if skipped_errors:
        Log.warning(f"repair plan 共 {total_patches} 个 patch, 跳过 {len(skipped_errors)} 个失败 patch", module=MODULE)
    return RepairPlanApplyResult(current, total_patches, applied_count, len(skipped_errors), all_failed, error_message, patch_results)


def _apply_repair_plan(
    *,
    chapter_markdown: str,
    repair_plan: dict[str, Any],
    repair_contract: RepairContract | None = None,
) -> str:
    """将局部 patch plan 应用到现有章节正文。

    Args:
        chapter_markdown: 当前章节正文。
        repair_plan: 结构化 repair patch 计划。
        repair_contract: 当前轮次的结构化修复合同；用于执行硬约束校验。

    Returns:
        应用 patch 后的正文。

    Raises:
        ValueError: 当所有 patch 都失败时抛出。
    """

    apply_result = _apply_repair_plan_with_details(
        chapter_markdown=chapter_markdown,
        repair_plan=repair_plan,
        repair_contract=repair_contract,
    )
    if apply_result.all_failed:
        raise ValueError(apply_result.error_message)
    return apply_result.patched_markdown


def _is_forbidden_evidence_modification(
    *,
    markdown_text: str,
    target_excerpt: str,
    replacement: str,
    absolute_start: int,
    absolute_end: int,
) -> bool:
    """判断 patch 是否试图修改证据小节。

    Args:
        markdown_text: 当前章节全文。
        target_excerpt: 原始命中文本。
        replacement: 替换后的文本。
        absolute_start: 命中片段在全文中的起始位置。
        absolute_end: 命中片段在全文中的结束位置。

    Returns:
        若 patch 试图改写证据小节则返回 ``True``。

    Raises:
        无。
    """

    if replacement == target_excerpt:
        return False
    evidence_span = _find_markdown_section_span(markdown_text=markdown_text, heading_text="证据与出处")
    if evidence_span is None:
        return False
    section_start, section_end = evidence_span
    return section_start <= absolute_start < section_end and absolute_end <= section_end


def _cleanup_repair_markdown(markdown_text: str) -> str:
    """清理 repair patch 应用后留下的结构性残片。

    Args:
        markdown_text: patch 应用后的章节文本。

    Returns:
        清理空 bullet 与多余空行后的正文。

    Raises:
        无。
    """

    normalized_lines = _normalize_whitespace_only_lines(markdown_text.splitlines())
    cleaned_lines = _drop_empty_bullet_lines(normalized_lines)
    cleaned_text = "\n".join(cleaned_lines)
    cleaned_text = _collapse_markdown_blank_lines(cleaned_text)
    trailing_newline = "\n" if markdown_text.endswith("\n") and cleaned_text.strip() else ""
    return cleaned_text.strip() + trailing_newline


def _normalize_whitespace_only_lines(lines: list[str]) -> list[str]:
    """把只包含空白符的行归一化为空行。

    Args:
        lines: 逐行 Markdown 文本。

    Returns:
        仅保留非空白内容，纯空白行被统一为 ``""`` 的行列表。

    Raises:
        无。
    """

    normalized: list[str] = []
    for line in lines:
        if line.strip():
            normalized.append(line)
            continue
        normalized.append("")
    return normalized


def _drop_empty_bullet_lines(lines: list[str]) -> list[str]:
    """删除内容为空或仅剩标点的 bullet 行。

    Args:
        lines: 逐行 Markdown 文本。

    Returns:
        删除空 bullet 后的行列表。

    Raises:
        无。
    """

    cleaned: list[str] = []
    for line in lines:
        bullet_match = re.match(r"^(\s*[-*]\s+)(.*)$", line)
        if bullet_match is None:
            cleaned.append(line)
            continue
        content = bullet_match.group(2).strip()
        if _is_effectively_empty_bullet_content(content):
            continue
        cleaned.append(line)
    return cleaned


def _is_effectively_empty_bullet_content(content: str) -> bool:
    """判断 bullet 内容是否已经空到应整体删除。

    Args:
        content: bullet 去掉前缀后的正文。

    Returns:
        若内容已无有效信息则返回 ``True``。

    Raises:
        无。
    """

    if not content:
        return True
    normalized = re.sub(r"[。．，,；;：:、!！?？…·\-\(\)（）\[\]【】\"'“”‘’`_~]+", "", content)
    normalized = re.sub(r"\s+", "", normalized)
    return not normalized


def _collapse_markdown_blank_lines(markdown_text: str) -> str:
    """压缩 Markdown 中连续空白行。

    Args:
        markdown_text: 原始 Markdown 文本。

    Returns:
        连续三个及以上空行被压缩后的文本。

    Raises:
        无。
    """

    normalized = markdown_text.replace("\r\n", "\n")
    return re.sub(r"\n{3,}", "\n\n", normalized)