"""固定研究快照到 Notion Markdown 的确定投影与回读内容核验。"""

from html import escape, unescape
import re
from urllib.parse import urlparse

from alpha.contracts.research import ResearchRecord, ResearchRevision
from alpha.contracts.research_working import ResearchReportContent
from alpha.research.publication_identity import publication_identifier, publication_marker

_TABLE_DIVIDER = re.compile(r"^:?-+:?$")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_TOKENS = re.compile(r"https?://[^\s<>\"')]+|[+-]?[$€£¥₹₽]?\d+(?:[.,]\d+)*(?:%|x)?|[+-](?=\s*[$€£¥₹₽]?\d)|\((?=[$€£¥₹₽]?\d)|(?<=[\d%])\)|[A-Za-z_][A-Za-z0-9_:-]*|[^\W\d_]|[$€£¥₹₽%±×÷≤≥∞−]")
_EXTERNAL_SCHEMES = frozenset(("http", "https", "mailto"))
_TITLE_CHARS = 80


def _cells(line: str) -> list[str]:
    """拆分 GFM 表格单行。参数：行文本。返回：保留转义内容的单元格。异常：无。"""
    return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def _external_links(text: str) -> str:
    """将本地来源保留为文字而非伪造远端链接。参数：Markdown。返回：投影文本。异常：无。"""
    return _MARKDOWN_LINK.sub(_link_replacement, text)


def _link_replacement(match: re.Match[str]) -> str:
    """投影单个引用。参数：匹配。返回：链接或本地引用说明。异常：无。"""
    label, destination = match.group(1), match.group(2)
    if urlparse(destination).scheme in _EXTERNAL_SCHEMES:
        return match.group(0)
    return f"{label}（本地引用：{destination}）"


def notion_markdown(text: str) -> str:
    """转换常见 GFM 表格并保留代码块。参数：研究 Markdown。返回：官方增强 Markdown。异常：无。"""
    lines = _external_links(text).splitlines()
    output: list[str] = []
    fence: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        prefix = line.lstrip()[:3]
        if prefix in ("```", "~~~"):
            fence = None if fence == prefix else prefix if fence is None else fence
        if (fence is None and index + 1 < len(lines) and "|" in line and "|" in lines[index + 1]
                and len(_cells(line)) == len(_cells(lines[index + 1])) and all(_TABLE_DIVIDER.fullmatch(cell) for cell in _cells(lines[index + 1]))):
            rows = [_cells(line)]
            index += 2
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                row = _cells(lines[index])
                if len(row) != len(rows[0]):
                    break
                rows.append(row)
                index += 1
            output.append("<table>\n" + "\n".join("<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>" for row in rows) + "\n</table>")
            continue
        output.append(line)
        index += 1
    return "\n".join(output)


def render_publication(research: ResearchRecord, revision: ResearchRevision, content: ResearchReportContent, target_id: str) -> tuple[str, str]:
    """渲染已提交版本。参数：原研究、版本、完整快照、固定目标。返回：标题与冻结正文。异常：无。"""
    identifier = publication_identifier(revision.revision_id, target_id)
    title = f"{research.title[:_TITLE_CHARS]} {revision.as_of.date().isoformat()} v{revision.number} [{identifier}]"
    sections = [f"# {research.title}\n\n{publication_marker(identifier)}\n\n研究问题：{research.question}\n\n信息截止：{revision.as_of.isoformat()}", content.report_markdown]
    if content.evidence:
        sections.append("## 来源与证据定位\n\n" + "\n\n".join(
            f"- {item.evidence_id} · {item.classification.value} · {item.document_type}\n"
            f"  来源：{item.source_ref}\n  定位：{item.locator or '原文定位未提供'}\n  摘录：{item.excerpt}\n"
            f"  公开时间：{item.published_at.isoformat() if item.published_at is not None else item.time_missing_reason or '未知'}"
            for item in content.evidence
        ))
    if revision.parent_revision_id is not None:
        sections.append(f"前一报告版本：{revision.parent_revision_id}")
    sections.append(f"---\n\nalpha-revision: {revision.revision_id}\n\n"
                    f"alpha-content-sha256: {revision.content_hash}\n\nalpha-method-sha256: {revision.skill_hash}")
    return title, notion_markdown("\n\n".join(sections))


def _comparison_tokens(markdown: str) -> tuple[str, ...]:
    """提取稳定内容序列。参数：增强 Markdown。返回：文字、数值、币种和 URL 序列。异常：无。"""
    plain = _MARKDOWN_LINK.sub(_comparison_link, markdown)
    plain = unescape(_HTML_TAG.sub(" ", plain))
    return tuple(_TOKENS.findall(plain))


def _comparison_link(match: re.Match[str]) -> str:
    """归一自动链接，不重复计算 URL 本身作为标签的显示。参数：链接。返回：稳定文字和目标。异常：无。"""
    label, destination = match.group(1), match.group(2)
    return destination if label == destination else f"{label} {destination}"


def verify_publication_markdown(expected: str, actual: str, publication_id: str) -> None:
    """核对回读标记及完整内容。参数：冻结正文、远端正文、发布 ID。返回：无。异常：缺标记、遗漏、数字/来源或正文变化。"""
    if publication_marker(publication_id) not in actual or _comparison_tokens(expected) != _comparison_tokens(actual):
        raise ValueError("Notion 回读正文、数值、来源或发布标记不匹配，保留待核对")
