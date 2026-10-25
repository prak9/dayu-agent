"""模板解析模块。

该模块负责将报告模板切分为一级章节，并提供：
- 全文目标提取能力。
- 全局读者画像提取能力。
- 章节目标提取能力。
- 章节骨架提取能力。
- 章节级写作合同提取能力。
- 条件型写作规则提取能力。
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from typing import Any

import yaml

from alpha.services.internal.write_pipeline.chapter_contracts import (
    ChapterContract,
    ItemRule,
    extract_chapter_contract,
    extract_item_rules,
)

_HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_COMMENT_BODY_PATTERN = re.compile(r"<!--(.*?)-->", re.DOTALL)
_REPORT_GOAL_START = "REPORT_GOAL"
_REPORT_GOAL_END = "END_REPORT_GOAL"
_AUDIENCE_PROFILE_START = "AUDIENCE_PROFILE"
_AUDIENCE_PROFILE_END = "END_AUDIENCE_PROFILE"
_COMPANY_FACET_CATALOG_START = "COMPANY_FACET_CATALOG"
_COMPANY_FACET_CATALOG_END = "END_COMPANY_FACET_CATALOG"
_CHAPTER_GOAL_START = "CHAPTER_GOAL"
_CHAPTER_GOAL_END = "END_CHAPTER_GOAL"


@dataclass
class TemplateChapter:
    """模板章节对象。

    Args:
        index: 章节序号（从 1 开始）。
        title: 章节标题。
        content: 章节完整文本（含二级标题与正文）。
        chapter_goal: 本章回答的总目标。
        skeleton: 去除 HTML 注释后的章节骨架。
        chapter_contract: 章节级写作合同。
        item_rules: 条件型条目规则。

    Returns:
        无。

    Raises:
        无。
    """

    index: int
    title: str
    content: str
    chapter_goal: str
    skeleton: str
    chapter_contract: ChapterContract
    item_rules: list[ItemRule]


@dataclass
class TemplateLayout:
    """模板结构对象。

    Args:
        report_goal: 全文总目标。
        audience_profile: 全局读者画像。
        company_facet_catalog: 公司级“主业务类型 / 关键约束”候选词表。
        preface: 第一章前导文本（原始，含 HTML 注释）。
        preface_skeleton: 前导文本剔除 HTML 注释后的骨架，用于拼装最终报告。
        chapters: 一级章节列表。

    Returns:
        无。

    Raises:
        无。
    """

    report_goal: str
    audience_profile: str
    company_facet_catalog: dict[str, list[str]]
    preface: str
    preface_skeleton: str
    chapters: list[TemplateChapter]


def parse_template_layout(template_markdown: str) -> TemplateLayout:
    """解析模板一级章节布局。

    Args:
        template_markdown: 模板全文。

    Returns:
        `TemplateLayout` 对象。

    Raises:
        ValueError: 当模板缺少一级章节时抛出。
    """

    lines = template_markdown.splitlines()
    heading_positions: list[int] = []
    for line_index, line in enumerate(lines):
        if line.startswith("## "):
            heading_positions.append(line_index)

    if not heading_positions:
        raise ValueError("模板中未找到一级章节（## ）")

    preface = "\n".join(lines[: heading_positions[0]]).strip()
    report_goal = _extract_unique_text_block(
        raw_text=preface,
        start_marker=_REPORT_GOAL_START,
        end_marker=_REPORT_GOAL_END,
        scope_name="模板前导区",
        allow_empty=True,
    )
    audience_profile = _extract_unique_text_block(
        raw_text=preface,
        start_marker=_AUDIENCE_PROFILE_START,
        end_marker=_AUDIENCE_PROFILE_END,
        scope_name="模板前导区",
        allow_empty=True,
    )
    company_facet_catalog = _extract_unique_yaml_mapping_block(
        raw_text=preface,
        start_marker=_COMPANY_FACET_CATALOG_START,
        end_marker=_COMPANY_FACET_CATALOG_END,
        scope_name="模板前导区",
        allow_empty=True,
    )
    chapters: list[TemplateChapter] = []
    preface_skeleton = _strip_html_comments(preface).strip()
    for pos_index, start_line in enumerate(heading_positions):
        end_line = heading_positions[pos_index + 1] if pos_index + 1 < len(heading_positions) else len(lines)
        section_lines = lines[start_line:end_line]
        content = "\n".join(section_lines).strip()
        title = section_lines[0][3:].strip()
        chapter_goal = _extract_unique_text_block(
            raw_text=content,
            start_marker=_CHAPTER_GOAL_START,
            end_marker=_CHAPTER_GOAL_END,
            scope_name=f"章节 {title!r}",
            allow_empty=True,
        )
        skeleton = _strip_html_comments(content).strip()
        chapter_contract = extract_chapter_contract(content, chapter_title=title)
        item_rules = extract_item_rules(content, chapter_title=title)
        chapters.append(
            TemplateChapter(
                index=pos_index + 1,
                title=title,
                content=content,
                chapter_goal=chapter_goal,
                skeleton=skeleton,
                chapter_contract=chapter_contract,
                item_rules=item_rules,
            )
        )

    return TemplateLayout(
        report_goal=report_goal,
        audience_profile=audience_profile,
        company_facet_catalog=company_facet_catalog,
        preface=preface,
        preface_skeleton=preface_skeleton,
        chapters=chapters,
    )


def build_report_markdown(preface: str, chapters: list[str]) -> str:
    """按模板顺序拼装报告正文。

    Args:
        preface: 前导文本。
        chapters: 已完成章节正文列表（每项需含 `## 标题`）。

    Returns:
        报告 Markdown 全文。

    Raises:
        ValueError: 当章节为空时抛出。
    """

    if not chapters:
        raise ValueError("至少需要一个章节内容")

    body = "\n\n---\n\n".join(chapter.strip() for chapter in chapters if chapter.strip())
    if preface:
        return f"{preface.strip()}\n\n---\n\n{body}".strip()
    return body.strip()


def _strip_html_comments(text: str) -> str:
    """删除 HTML 注释块。

    Args:
        text: 原始文本。

    Returns:
        删除注释后的文本。

    Raises:
        无。
    """

    normalized = text.replace("\r\n", "\n")
    lines = normalized.split("\n")
    kept_lines: list[str] = []
    line_index = 0

    while line_index < len(lines):
        current_line = lines[line_index]
        if "<!--" not in current_line:
            kept_lines.append(current_line)
            line_index += 1
            continue

        if current_line.strip().startswith("<!--"):
            next_index = line_index
            while next_index < len(lines):
                candidate = lines[next_index]
                if candidate.strip().startswith("<!--"):
                    while next_index < len(lines):
                        if "-->" in lines[next_index]:
                            next_index += 1
                            break
                        next_index += 1
                    continue
                if not candidate.strip():
                    next_index += 1
                    continue
                break

            trailing_blank_count = 0
            for kept_line in reversed(kept_lines):
                if kept_line.strip():
                    break
                trailing_blank_count += 1
            has_nonblank_before = bool(kept_lines) and bool(kept_lines[-1].strip())
            has_nonblank_after = next_index < len(lines) and bool(lines[next_index].strip())
            if trailing_blank_count > 1:
                del kept_lines[-(trailing_blank_count - 1) :]
            if has_nonblank_before and has_nonblank_after:
                if trailing_blank_count == 0:
                    kept_lines.append("")
            line_index = next_index
            continue

        cleaned_line = _HTML_COMMENT_PATTERN.sub("", current_line)
        kept_lines.append(cleaned_line)
        line_index += 1

    return "\n".join(kept_lines)


def _extract_unique_text_block(
    *,
    raw_text: str,
    start_marker: str,
    end_marker: str,
    scope_name: str,
    allow_empty: bool,
) -> str:
    """提取唯一的文本块内容。

    Args:
        raw_text: 原始文本。
        start_marker: 起始标记。
        end_marker: 结束标记。
        scope_name: 作用域名称，仅用于错误提示。
        allow_empty: 是否允许不存在该文本块。

    Returns:
        文本块正文；若允许缺失且未找到，则返回空字符串。

    Raises:
        ValueError: 当文本块重复、缺失结束标记或正文为空时抛出。
    """

    payloads: list[str] = []
    for match in _HTML_COMMENT_BODY_PATTERN.finditer(raw_text):
        comment_body = match.group(1)
        payload = _extract_named_comment_text_from_body(
            comment_body=comment_body,
            start_marker=start_marker,
            end_marker=end_marker,
            scope_name=scope_name,
        )
        if payload is not None:
            payloads.append(payload)
    if not payloads:
        if allow_empty:
            return ""
        raise ValueError(f"{scope_name} 缺少 {start_marker} 块")
    if len(payloads) > 1:
        raise ValueError(f"{scope_name} 存在多个 {start_marker} 块，无法判定唯一目标")
    return payloads[0]


def _extract_unique_yaml_mapping_block(
    *,
    raw_text: str,
    start_marker: str,
    end_marker: str,
    scope_name: str,
    allow_empty: bool,
) -> dict[str, list[str]]:
    """提取唯一 YAML 映射块。

    Args:
        raw_text: 原始文本。
        start_marker: 起始标记。
        end_marker: 结束标记。
        scope_name: 作用域名称，仅用于错误提示。
        allow_empty: 是否允许不存在该 YAML 块。

    Returns:
        解析后的映射结果；若允许缺失且未声明，则返回空映射。

    Raises:
        ValueError: 当 YAML 非法、不是映射，或值不是字符串列表时抛出。
    """

    payload = _extract_unique_text_block(
        raw_text=raw_text,
        start_marker=start_marker,
        end_marker=end_marker,
        scope_name=scope_name,
        allow_empty=allow_empty,
    )
    if not payload:
        return {}
    try:
        parsed = yaml.safe_load(payload)
    except yaml.YAMLError as exc:
        raise ValueError(f"{scope_name} 的 {start_marker} 不是合法 YAML: {exc}") from exc
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ValueError(f"{scope_name} 的 {start_marker} 必须解析为映射")
    normalized: dict[str, list[str]] = {}
    for raw_key, raw_value in parsed.items():
        key = str(raw_key).strip()
        if not key:
            raise ValueError(f"{scope_name} 的 {start_marker} 包含空键名")
        if not isinstance(raw_value, list) or any(not isinstance(item, str) for item in raw_value):
            raise ValueError(f"{scope_name} 的 {start_marker}.{key} 必须为字符串列表")
        normalized[key] = [item.strip() for item in raw_value if item.strip()]
    return normalized


def _extract_named_comment_text_from_body(
    *,
    comment_body: str,
    start_marker: str,
    end_marker: str,
    scope_name: str,
) -> str | None:
    """从单个 HTML 注释体中提取带标记的纯文本块。

    Args:
        comment_body: HTML 注释正文。
        start_marker: 起始标记。
        end_marker: 结束标记。
        scope_name: 作用域名称，仅用于错误提示。

    Returns:
        若命中对应标记，则返回去缩进后的纯文本；否则返回 ``None``。

    Raises:
        ValueError: 当块结构非法、正文为空或结束标记缺失时抛出。
    """

    lines = [line.rstrip() for line in comment_body.splitlines()]
    start_index: int | None = None
    for line_index, line in enumerate(lines):
        if line.strip() == start_marker:
            start_index = line_index
            break
    if start_index is None:
        return None
    for line_index in range(start_index + 1, len(lines)):
        if lines[line_index].strip() == end_marker:
            payload_lines = lines[start_index + 1 : line_index]
            payload_text = textwrap.dedent("\n".join(payload_lines)).strip()
            if not payload_text:
                raise ValueError(f"{scope_name} 的 {start_marker} 块不能为空")
            return payload_text
    raise ValueError(f"{scope_name} 的 {start_marker} 缺少 {end_marker}")
