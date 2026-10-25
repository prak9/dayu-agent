"""来源清单构建模块。

该模块负责：
- 从章节正文中抽取“证据与出处”条目。
- 按“来源 | 类型/标识 | 日期”三段式去重、归类并按日期倒序排序。
- 生成“来源清单”章节 Markdown。
"""

from __future__ import annotations

import re
from collections import OrderedDict
from datetime import datetime
from typing import Iterable

from .models import SourceEntry

_DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")

_GROUP_ORDER = [
    "SEC filings",
    "上传财报/公告",
    "监管机构与官方发布",
    "标准与框架",
    "行业协会与市场统计",
    "公司官网与公告/新闻稿",
    "媒体报道",
]

_UPLOADED_DOCUMENT_TYPE_KEYWORDS = (
    "年度报告",
    "年报",
    "中期报告",
    "半年度报告",
    "季度报告",
    "第一季度报告",
    "第三季度报告",
    "公告",
    "通函",
    "招股说明书",
    "上市文件",
    "发售文件",
    "聆讯后资料集",
    "股东信",
    "电话会议纪要",
    "路演纪要",
    "演示材料",
    "业绩说明会",
    "ESG报告",
    "环境、社会及管治报告",
    "社会责任报告",
    "可持续发展报告",
)


def extract_evidence_items(chapter_markdown: str) -> list[str]:
    """提取章节中的证据条目。

    遇到任意级别 Markdown 标题（##、###、#### 等）即终止收集，
    避免将"#### 关键术语说明"内的条目误判为证据。

    Args:
        chapter_markdown: 章节正文。

    Returns:
        证据条目列表。

    Raises:
        无。
    """

    lines = chapter_markdown.splitlines()
    start_index = _find_evidence_start_line(lines)
    if start_index < 0:
        return []

    items: list[str] = []
    for line in lines[start_index + 1 :]:
        stripped = line.strip()
        # 遇到任意级别标题（##、###、#### 等）终止收集
        if stripped.startswith("#"):
            break
        if not stripped or stripped.startswith("```"):
            continue
        if stripped.startswith("- "):
            item_text = _normalize_text(stripped[2:])
            if item_text:
                items.append(item_text)
            continue
        if looks_like_evidence_item(stripped):
            items.append(_normalize_text(stripped))
    return items


def looks_like_evidence_item(text: str) -> bool:
    """判断一行文本是否像 evidence line。

    设计意图：
    - 模型偶尔会漏掉 `- ` bullet，但仍输出完整四段式来源。
    - 这里仅做最小判定：要求至少 4 段 `|` 分隔字段，避免把普通正文误当证据。

    Args:
        text: 待判断文本。

    Returns:
        若看起来像 evidence line，则返回 `True`。

    Raises:
        无。
    """

    normalized = _normalize_text(text)
    if not normalized:
        return False
    parts = [part.strip() for part in normalized.split("|")]
    return len(parts) >= 4 and all(parts[:4])


def build_source_entries(evidence_items: Iterable[str]) -> list[SourceEntry]:
    """构建并去重来源条目。

    当前来源清单直接保留章节里已有的完整四段式/多段式 evidence line，
    但去重时仅比较前三段“来源 | 类型/标识 | 日期”。这样可以把同一
    文档在不同章节、不同定位的重复引用折叠为一个来源条目。

    Args:
        evidence_items: 原始证据条目。

    Returns:
        去重后的来源条目列表。

    Raises:
        无。
    """

    unique_map: "OrderedDict[str, SourceEntry]" = OrderedDict()
    for raw_text in evidence_items:
        normalized = _normalize_text(raw_text)
        if not normalized:
            continue
        dedup_key = _extract_dedup_key(normalized)
        if dedup_key in unique_map:
            continue
        display_text = _extract_document_ref(normalized)
        group = _classify_group(display_text)
        date_text = _extract_date_text(display_text)
        unique_map[dedup_key] = SourceEntry(text=display_text, group=group, date_text=date_text)

    deduped = list(unique_map.values())
    return _sort_entries(deduped)


def render_source_list_chapter(entries: list[SourceEntry]) -> str:
    """渲染“来源清单”章节。

    Args:
        entries: 来源条目列表。

    Returns:
        来源清单章节 Markdown（从 `## 来源清单` 开始）。

    Raises:
        无。
    """

    grouped: dict[str, list[SourceEntry]] = {name: [] for name in _GROUP_ORDER}
    for entry in entries:
        grouped.setdefault(entry.group, []).append(entry)

    blocks: list[str] = ["## 来源清单", ""]
    for group_name in _GROUP_ORDER:
        blocks.append(f"### {group_name}")
        group_items = grouped.get(group_name, [])
        if group_items:
            for item in group_items:
                blocks.append(f"- {item.text}")
        else:
            blocks.append("- 无")
        blocks.append("")

    return "\n".join(blocks).strip()


def _find_evidence_start_line(lines: list[str]) -> int:
    """定位“证据与出处”标题行。

    Args:
        lines: 文本行列表。

    Returns:
        标题行索引，未找到返回 `-1`。

    Raises:
        无。
    """

    for index, line in enumerate(lines):
        if line.strip() == "### 证据与出处":
            return index
    return -1


def _normalize_text(text: str) -> str:
    """规整来源文本。

    Args:
        text: 原始文本。

    Returns:
        规整后的文本。

    Raises:
        无。
    """

    return re.sub(r"\s+", " ", text).strip()


def _extract_document_ref(text: str) -> str:
    """返回来源清单展示文本。

    当前来源清单保留章节中已生成的完整 evidence line，不再截断为
    文档级引用，以免丢失“定位”字段。

    Args:
        text: 已规整的来源文本。

    Returns:
        规范化后的完整 evidence line。

    Raises:
        无。
    """

    return _normalize_text(text)


def _extract_dedup_key(text: str) -> str:
    """提取来源去重键。

    当前按前三段“来源 | 类型/标识 | 日期”去重；第四段及之后的定位信息
    仅用于展示，不参与来源级别去重。

    Args:
        text: 已规整的来源文本。

    Returns:
        去重键字符串。

    Raises:
        无。
    """

    normalized = _normalize_text(text)
    parts = [part.strip() for part in normalized.split("|")]
    if len(parts) < 3 or not all(parts[:3]):
        return normalized
    return " | ".join(parts[:3])


def _classify_group(text: str) -> str:
    """按规则归类来源分组。

    Args:
        text: 来源文本。

    Returns:
        分组名称。

    Raises:
        无。
    """

    normalized = _normalize_text(text)
    lower_text = normalized.lower()
    parts = [part.strip() for part in normalized.split("|")]
    if "sec edgar" in lower_text or "accession" in lower_text or "form " in lower_text:
        return "SEC filings"
    if "http://" in lower_text or "https://" in lower_text or "url:" in lower_text:
        if any(keyword in lower_text for keyword in ["reuters", "bloomberg", "wsj", "ft", "媒体"]):
            return "媒体报道"
        if any(keyword in lower_text for keyword in ["investor", "ir", "官网", "newsroom", "company"]):
            return "公司官网与公告/新闻稿"
    if _looks_like_uploaded_document(parts):
        return "上传财报/公告"
    if any(keyword in lower_text for keyword in ["ifrs", "gaap", "framework", "标准"]):
        return "标准与框架"
    if any(keyword in lower_text for keyword in ["协会", "exchange", "stat", "统计", "industry"]):
        return "行业协会与市场统计"
    return "监管机构与官方发布"


def _looks_like_uploaded_document(parts: list[str]) -> bool:
    """判断来源是否更像仓库上传的财报/公告类文档。

    Args:
        parts: 规整后按 `|` 切分的字段列表。

    Returns:
        若应归入“上传财报/公告”，返回 `True`。

    Raises:
        无。
    """

    if len(parts) < 2:
        return False

    document_type = parts[1]
    if any(keyword in document_type for keyword in _UPLOADED_DOCUMENT_TYPE_KEYWORDS):
        return True

    if len(parts) < 3:
        return False

    date_segment = parts[2]
    if "公告日期" in date_segment and any(token in document_type for token in ("报告", "说明书", "通函")):
        return True
    if any(token in date_segment for token in ("财年", "报告期")) and any(
        token in document_type for token in ("报告", "公告", "说明书", "通函")
    ):
        return True
    return False


def _extract_date_text(text: str) -> str:
    """提取来源中的日期字符串。

    Args:
        text: 来源文本。

    Returns:
        日期文本，未命中返回空字符串。

    Raises:
        无。
    """

    match = _DATE_PATTERN.search(text)
    if match is None:
        return ""
    return match.group(1)


def _sort_entries(entries: list[SourceEntry]) -> list[SourceEntry]:
    """按分组顺序与日期倒序排序。

    Args:
        entries: 原始来源条目。

    Returns:
        排序后的条目列表。

    Raises:
        无。
    """

    group_priority = {name: index for index, name in enumerate(_GROUP_ORDER)}

    def _date_key(entry: SourceEntry) -> tuple[int, int]:
        if not entry.date_text:
            return (1, 0)
        try:
            timestamp = int(datetime.strptime(entry.date_text, "%Y-%m-%d").timestamp())
            return (0, -timestamp)
        except ValueError:
            return (1, 0)

    return sorted(
        entries,
        key=lambda entry: (group_priority.get(entry.group, 999), *_date_key(entry), entry.text),
    )
