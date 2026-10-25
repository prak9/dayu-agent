"""Notion 外部 JSON 边界解码，不向应用层传播无类型字段。"""

import math
from uuid import UUID

from alpha.contracts.agent_types import JsonValue
from alpha.integrations.notion.contracts import NotionMarkdown, NotionPage, NotionTask, NotionTaskState

_DEFAULT_POLL_SECONDS = 2.0


def require_map(value: JsonValue) -> dict[str, JsonValue]:
    """要求映射。参数：JSON 值。返回：映射。异常：非映射时 ValueError。"""
    if not isinstance(value, dict):
        raise ValueError("Notion JSON 对象格式非法")
    return value


def require_text(value: JsonValue) -> str:
    """要求文本。参数：JSON 值。返回：文本。异常：类型不符时 ValueError。"""
    if not isinstance(value, str):
        raise ValueError("Notion 文本字段格式非法")
    return value


def page_id(value: str) -> str:
    """规范页面 UUID。参数：页面 ID。返回：带连字符 UUID。异常：非法 ID。"""
    return str(UUID(value))


def decode_page(body: dict[str, JsonValue]) -> NotionPage:
    """解码远端页面。参数：响应。返回：页面。异常：字段不符。"""
    if body.get("object") != "page":
        raise ValueError("Notion 响应不是页面")
    parent = require_map(body.get("parent"))
    parent_id = page_id(require_text(parent.get("page_id"))) if parent.get("type") == "page_id" else None
    title_parts: list[str] = []
    properties = require_map(body.get("properties"))
    for raw in properties.values():
        prop = require_map(raw)
        if prop.get("type") != "title":
            continue
        title = prop.get("title")
        if not isinstance(title, list):
            raise ValueError("Notion 页面标题不是数组")
        for item in title:
            part = require_map(item)
            plain_text = part.get("plain_text")
            title_parts.append(require_text(plain_text) if plain_text is not None else require_text(require_map(part.get("text")).get("content")))
    return NotionPage(page_id(require_text(body.get("id"))), parent_id, require_text(body.get("url")), "".join(title_parts),
                       body.get("archived") is True or body.get("in_trash") is True)


def decode_markdown(body: dict[str, JsonValue]) -> NotionMarkdown:
    """解码完整性标记。参数：响应。返回：Markdown。异常：字段损坏。"""
    unknown = body.get("unknown_block_ids", [])
    if not isinstance(unknown, list) or not isinstance(body.get("truncated"), bool):
        raise ValueError("Notion Markdown 完整性字段缺失")
    return NotionMarkdown(require_text(body.get("markdown")), body.get("truncated") is True, tuple(require_text(item) for item in unknown))


def decode_task(body: dict[str, JsonValue]) -> NotionTask:
    """解码异步任务。参数：响应。返回：任务。异常：状态、轮询提示或错误字段非法。"""
    if body.get("object") != "async_task":
        raise ValueError("Notion 响应不是异步任务")
    hint = body.get("poll_after_seconds", _DEFAULT_POLL_SECONDS)
    if not isinstance(hint, (int, float)) or isinstance(hint, bool) or not math.isfinite(hint) or hint < 0:
        raise ValueError("Notion 轮询提示非法")
    result = require_map(body["result"]) if body.get("result") is not None else None
    error = require_map(body["error"]) if body.get("error") is not None else None
    error_status = error.get("status") if error is not None else None
    if error_status is not None and (not isinstance(error_status, int) or isinstance(error_status, bool)):
        raise ValueError("Notion 异步错误状态非法")
    return NotionTask(require_text(body.get("id")), NotionTaskState(require_text(body.get("status"))), float(hint),
                       decode_page(result) if result is not None and result.get("object") == "page" else None,
                       error_status, require_text(error.get("code")) if error is not None else None)
