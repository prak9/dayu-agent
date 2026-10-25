"""可在创建生效后丢响应的 Notion 模拟远端。"""

from dataclasses import dataclass, field
import json
from typing import cast
from uuid import UUID
from threading import Event

import httpx

from alpha.contracts.agent_types import JsonValue
from alpha.integrations.notion.decoding import require_map, require_text
from tests.integrations.notion.test_client import PARENT_ID, page


@dataclass
class NotionServer:
    """保存页面正文和异步任务，不把客户端重试当作同一次创建。"""

    pages: dict[str, dict[str, JsonValue]] = field(default_factory=dict)
    markdown: dict[str, str] = field(default_factory=dict)
    tasks: dict[str, dict[str, JsonValue]] = field(default_factory=dict)
    create_attempts: int = 0
    created: int = 0
    unknown_create: bool = False
    committed_create_number: int | None = None
    limited_create: bool = False
    async_create: bool = False
    failed_task: bool = False
    corrupt_readback: bool = False
    truncated: bool = False
    append_attempts: int = 0
    unknown_append: bool = False
    async_append: bool = False
    expired_task: bool = False
    deny_parent: bool = False
    create_entered: Event | None = None
    create_release: Event | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """处理官方 API 路径。参数：请求。返回：响应。异常：注入的写响应丢失。"""
        path = request.url.path.removeprefix("/v1")
        if path == "/pages" and request.method == "POST":
            self.create_attempts += 1
            if self.limited_create:
                self.limited_create = False
                return httpx.Response(429, json={"object": "error", "code": "rate_limited"}, headers={"Retry-After": "0"})
            body = require_map(cast(JsonValue, json.loads(request.content)))
            self.created += 1
            identifier = str(UUID(int=self.created))
            metadata = page(identifier, require_text(require_map(body["parent"])["page_id"]))
            metadata["properties"] = body["properties"]
            self.pages[identifier] = metadata
            self.markdown[identifier] = require_text(body["markdown"])
            if self.committed_create_number == self.created:
                return httpx.Response(503, json={"code": "service_unavailable", "additional_data": {"committed_resource_id": identifier}})
            if self.create_entered is not None:
                self.create_entered.set()
            if self.create_release is not None and not self.create_release.wait(timeout=3):
                raise AssertionError("模拟 HTTP 未在测试时限内释放")
            if self.unknown_create:
                self.unknown_create = False
                raise httpx.ReadTimeout("created remotely, response lost")
            if self.async_create:
                task_id = f"task_{self.created}"
                self.tasks[task_id] = {"object": "async_task", "id": task_id, "status": "succeeded", "result": metadata}
                return httpx.Response(202, json={"object": "async_task", "id": task_id, "status": "queued", "poll_after_seconds": 0})
            return httpx.Response(200, json=metadata)
        if path.startswith("/async_tasks/"):
            if self.expired_task:
                return httpx.Response(404, json={"code": "object_not_found"})
            if self.failed_task:
                return httpx.Response(200, json={"object": "async_task", "id": path.rsplit("/", 1)[-1], "status": "failed", "error": {"status": 400, "code": "validation_error"}})
            return httpx.Response(200, json=self.tasks[path.rsplit("/", 1)[-1]])
        if path.startswith("/blocks/") and path.endswith("/children"):
            return httpx.Response(200, json={"results": [{"id": identifier, "type": "child_page"} for identifier in self.pages], "has_more": False})
        if path.startswith("/pages/"):
            identifier = path.split("/")[2]
            if identifier == PARENT_ID:
                if self.deny_parent:
                    return httpx.Response(403, json={"object": "error", "code": "restricted_resource"})
                return httpx.Response(200, json=page(PARENT_ID))
            if identifier not in self.pages:
                return httpx.Response(404, json={"object": "error", "code": "object_not_found"})
            if path.endswith("/markdown"):
                if request.method == "PATCH":
                    self.append_attempts += 1
                    body = require_map(cast(JsonValue, json.loads(request.content)))
                    updates = require_map(body["update_content"])["content_updates"]
                    assert isinstance(updates, list) and len(updates) == 1
                    update = require_map(updates[0])
                    old, new = require_text(update["old_str"]), require_text(update["new_str"])
                    if old not in self.markdown[identifier]:
                        return httpx.Response(400, json={"code": "validation_error"})
                    self.markdown[identifier] = self.markdown[identifier].replace(old, new)
                    if self.unknown_append:
                        self.unknown_append = False
                        raise httpx.ReadTimeout("appended remotely, response lost")
                    if self.async_append:
                        task_id = f"append_{self.append_attempts}"
                        self.tasks[task_id] = {"object": "async_task", "id": task_id, "status": "succeeded"}
                        return httpx.Response(202, json={"object": "async_task", "id": task_id, "status": "queued", "poll_after_seconds": 0})
                markdown = self.markdown[identifier].replace("报告", "被改写的数字1000") if self.corrupt_readback else self.markdown[identifier]
                return httpx.Response(200, json={"object": "page_markdown", "id": identifier, "markdown": markdown, "truncated": self.truncated, "unknown_block_ids": []})
            return httpx.Response(200, json=self.pages[identifier])
        raise AssertionError(f"未实现的模拟 Notion 方法：{request.method} {path}")
