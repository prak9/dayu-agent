"""冻结 Markdown 的确定分段与远端单次替换标记。"""

import json
import re
from hashlib import sha256

MAX_SEGMENT_BYTES = 128 * 1024
_MARKER_PREFIX = "alpha-segment:"


def _size(text: str) -> int:
    """计算 JSON 编码大小。参数：正文。返回：UTF-8 字节数。异常：无。"""
    return len(json.dumps(text, ensure_ascii=False).encode("utf-8"))


def split_publication(markdown: str) -> tuple[str, ...]:
    """在空行处分段并保持代码和 HTML 表格完整。参数：正文。返回：可原样连接的分段。异常：单块超限。"""
    blocks: list[str] = []
    block = ""
    fence: str | None = None
    table = False
    for line in markdown.splitlines(keepends=True):
        prefix = line.lstrip()[:3]
        if prefix in ("```", "~~~"):
            fence = None if fence == prefix else prefix if fence is None else fence
        if line.lstrip().startswith("<table>"):
            table = True
        block += line
        if "</table>" in line:
            table = False
        if not line.strip() and fence is None and not table:
            blocks.append(block)
            block = ""
    if block:
        blocks.append(block)
    segments: list[str] = []
    current = ""
    current_size = _size(current)
    for block in blocks:
        block_size = _size(block)
        if block_size > MAX_SEGMENT_BYTES:
            raise ValueError("报告单个段落、代码块或表格超过 Notion 分段上限，请拆分后提交新版本")
        if current and current_size + block_size - 2 > MAX_SEGMENT_BYTES:
            segments.append(current)
            current = ""
            current_size = _size(current)
        current += block
        current_size += block_size - 2
    if current:
        segments.append(current)
    if not segments:
        raise ValueError("发布正文不能为空")
    return tuple(segments)


def segment_marker(publication_id: str, index: int, segment: str) -> str:
    """生成版本和分段绑定的替换哨兵。参数：发布、索引、分段。返回：唯一标记。异常：无。"""
    return f"{_MARKER_PREFIX} {publication_id}:{index}:{sha256(segment.encode('utf-8')).hexdigest()}"


def segment_progress(markdown: str, publication_id: str, segments: tuple[str, ...]) -> tuple[int, str]:
    """解析唯一远端进度并剥离尾标记。参数：回读、发布、冻结分段。返回：已写段数、正文。异常：标记缺失或冲突。"""
    matches = list(re.finditer(r"alpha-segment: publication_[a-f0-9]+:\d+:[a-f0-9]{64}", markdown))
    if len(matches) != 1:
        raise ValueError("Notion 分段进度标记缺失或不唯一")
    match = matches[0]
    for index, segment in enumerate(segments):
        if match.group() == segment_marker(publication_id, index, segment):
            return index + 1, markdown[:match.start()] + markdown[match.end():]
    raise ValueError("Notion 分段进度不属于该固定版本")
