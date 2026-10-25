"""Notion 官方 Markdown/页面 HTTP 适配；不在传输层重试有副作用请求。"""

from __future__ import annotations

import json
import math
from typing import cast
from urllib.parse import quote

import httpx

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.cancellation import CancellationToken
from alpha.integrations.notion.contracts import NotionMarkdown, NotionPage, NotionTask
from alpha.integrations.notion.decoding import decode_markdown, decode_page, decode_task, page_id, require_map, require_text

NOTION_API_VERSION = "2026-03-11"
_API_BASE = "https://api.notion.com/v1"
_HTTP_TIMEOUT_SECONDS = 20.0
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_CHILD_PAGE_SIZE = 100


class NotionApiError(RuntimeError):
    """传输或官方错误，写入未知结果必须由发布服务调和。"""

    def __init__(self, status: int, code: str, *, unknown: bool = False, retry_after: float | None = None,
                 committed_resource_id: str | None = None) -> None:
        """保存安全分类。参数：状态、错误码、未知结果、重试提示、已提交对象ID。返回：无。异常：无。"""
        self.status = status
        self.code = code
        self.unknown = unknown
        self.retry_after = retry_after
        self.committed_resource_id = committed_resource_id
        super().__init__(f"Notion 请求失败，status={status}，code={code}，结果{'未知' if unknown else '明确'}")


class NotionClient:
    """同步有界客户端，由 Host 托管操作线程和取消令牌。"""

    def __init__(self, token: str, *, transport: httpx.BaseTransport | None = None) -> None:
        """构造连接池。参数：独立 connection token、测试传输层。返回：无。异常：空密钥。"""
        if not token.strip():
            raise ValueError("Notion token 不能为空")
        self._http = httpx.Client(headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_API_VERSION},
                                  timeout=_HTTP_TIMEOUT_SECONDS, transport=transport, follow_redirects=False)

    def close(self) -> None:
        """释放连接池。参数：无。返回：无。异常：关闭失败。"""
        self._http.close()

    def _request(self, method: str, path: str, *, body: dict[str, JsonValue] | None = None, token: CancellationToken) -> dict[str, JsonValue]:
        """执行有界请求。参数：固定方法、相对 API 路径、JSON、Host 取消令牌。返回：响应。异常：取消或安全分类错误。"""
        token.raise_if_cancelled()
        data = bytearray()
        try:
            with self._http.stream(method, _API_BASE + path, json=body) as response:
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > _MAX_RESPONSE_BYTES:
                        raise NotionApiError(response.status_code, "response_too_large", unknown=method != "GET")
                try:
                    payload = require_map(cast(JsonValue, json.loads(bytes(data))))
                except (ValueError, UnicodeError):
                    raise NotionApiError(response.status_code, "invalid_response", unknown=method != "GET") from None
                if response.status_code >= 400:
                    retry_after = _retry_after(response.headers.get("Retry-After"))
                    code = payload.get("code")
                    additional = payload.get("additional_data")
                    committed = additional.get("committed_resource_id") if isinstance(additional, dict) else None
                    # 官方 503 可明确返回已经写入的对象 ID；保留给业务层先落盘再回读。
                    raise NotionApiError(response.status_code, code if isinstance(code, str) else "http_error",
                                         unknown=method != "GET" and response.status_code >= 500, retry_after=retry_after,
                                         committed_resource_id=page_id(committed) if isinstance(committed, str) else None)
        except httpx.HTTPError:
            raise NotionApiError(0, "transport_error", unknown=method != "GET") from None
        # 写请求的已知结果要先交还业务层持久化；取消不能抹去已经得到的 page/task 身份。
        if method == "GET":
            token.raise_if_cancelled()
        return payload

    def retrieve_page(self, identifier: str, token: CancellationToken) -> NotionPage:
        """读取直接父页和状态。参数：页面 ID、令牌。返回：页面。异常：API、取消或格式错误。"""
        return decode_page(self._request("GET", f"/pages/{page_id(identifier)}", token=token))

    def create_page(self, parent_id: str, title: str, markdown: str, token: CancellationToken) -> NotionPage | NotionTask:
        """创建完整正文子页。参数：固定父页、标题、正文、令牌。返回：页面或异步任务。异常：写入失败或未知结果。"""
        body: dict[str, JsonValue] = {"parent": {"type": "page_id", "page_id": page_id(parent_id)},
            "properties": {"title": {"type": "title", "title": [{"type": "text", "text": {"content": title}}]}},
            "markdown": markdown, "allow_async": True}
        result = self._request("POST", "/pages", body=body, token=token)
        return decode_task(result) if result.get("object") == "async_task" else decode_page(result)

    def retrieve_markdown(self, identifier: str, token: CancellationToken) -> NotionMarkdown:
        """回读正文。参数：页面或子树 ID、令牌。返回：含完整性标记的内容。异常：读取或取消失败。"""
        return decode_markdown(self._request("GET", f"/pages/{page_id(identifier)}/markdown", token=token))

    def replace_markdown(self, identifier: str, markdown: str, token: CancellationToken) -> NotionMarkdown | NotionTask:
        """替换本次尚未完成的专属发布页正文。参数：已知页面、确定正文、令牌。返回：结果或任务。异常：写入失败或未知结果。"""
        body: dict[str, JsonValue] = {"type": "replace_content", "replace_content": {"new_str": markdown}, "allow_async": True}
        result = self._request("PATCH", f"/pages/{page_id(identifier)}/markdown", body=body, token=token)
        return decode_task(result) if result.get("object") == "async_task" else decode_markdown(result)

    def retrieve_task(self, task_id: str, token: CancellationToken) -> NotionTask:
        """轮询已知任务，不使用远端提供的任意 URL。参数：task ID、令牌。返回：状态。异常：读取或取消失败。"""
        return decode_task(self._request("GET", f"/async_tasks/{quote(task_id, safe='')}", token=token))

    def replace_marker(self, identifier: str, old_marker: str, replacement: str, token: CancellationToken) -> NotionMarkdown | NotionTask:
        """仅替换尚未消耗的唯一分段哨兵。参数：页、旧标记、新内容、令牌。返回：正文或任务。异常：失败或未知结果。"""
        body: dict[str, JsonValue] = {"type": "update_content", "update_content": {"content_updates": [
            {"old_str": old_marker, "new_str": replacement}]}, "allow_async": True}
        result = self._request("PATCH", f"/pages/{page_id(identifier)}/markdown", body=body, token=token)
        return decode_task(result) if result.get("object") == "async_task" else decode_markdown(result)

    def child_pages(self, parent_id: str, token: CancellationToken) -> tuple[str, ...]:
        """完整枚举直接子页候选。参数：固定父页、令牌。返回：页面 ID。异常：分页损坏或读取失败。"""
        candidates: list[str] = []
        cursor: str | None = None
        seen: set[str] = set()
        while True:
            query = f"?page_size={_CHILD_PAGE_SIZE}" + (f"&start_cursor={quote(cursor, safe='')}" if cursor is not None else "")
            payload = self._request("GET", f"/blocks/{page_id(parent_id)}/children{query}", token=token)
            results = payload.get("results")
            if not isinstance(results, list):
                raise ValueError("Notion 子页列表格式非法")
            for raw in results:
                item = require_map(raw)
                if item.get("type") == "child_page":
                    candidates.append(page_id(require_text(item.get("id"))))
            if payload.get("has_more") is not True:
                return tuple(candidates)
            cursor = require_text(payload.get("next_cursor"))
            if cursor in seen:
                raise ValueError("Notion 子页分页游标重复")
            seen.add(cursor)


def _retry_after(value: str | None) -> float | None:
    """解析官方秒数提示。参数：响应头。返回：有限非负延迟或空。异常：无。"""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None
