"""Notion Markdown、异步响应、有界读取与未知结果分类测试。"""

from dataclasses import dataclass, field
import json
from typing import cast

import httpx
import pytest

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.cancellation import CancellationToken, CancelledError
from alpha.integrations.notion.client import NOTION_API_VERSION, NotionApiError, NotionClient
from alpha.integrations.notion.contracts import NotionMarkdown, NotionPage, NotionTask, NotionTaskState
from alpha.integrations.notion.decoding import decode_markdown, decode_task

PARENT_ID = "8b6f0c8f-c126-4555-b531-281fbb0b96bc"
PAGE_ID = "11111111-1111-4111-8111-111111111111"


def page(identifier: str = PAGE_ID, parent: str = PARENT_ID) -> dict[str, JsonValue]:
    """构造公开 API 页面。参数：页面、父页。返回：JSON。异常：无。"""
    return {"object": "page", "id": identifier, "url": f"https://www.notion.so/{identifier}", "parent": {"type": "page_id", "page_id": parent},
            "archived": False, "properties": {"title": {"type": "title", "title": [{"type": "text", "plain_text": "Invest report"}]}}}


@dataclass
class _Transport:
    """顺序响应，记录请求便于验证协议字段。"""

    responses: list[httpx.Response | Exception]
    requests: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """处理模拟请求。参数：请求。返回：响应。异常：注入的 HTTP 错误。"""
        self.requests.append(request)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_create_read_replace_and_async_result_are_distinct() -> None:
    """202 只返回任务身份，不误判为页面完成。参数：无。返回：无。异常：断言失败。"""
    markdown: dict[str, JsonValue] = {"object": "page_markdown", "id": PAGE_ID, "markdown": "# Report", "truncated": False, "unknown_block_ids": []}
    task: dict[str, JsonValue] = {"object": "async_task", "id": "task_1", "status": "queued", "poll_after_seconds": 2}
    transport = _Transport([httpx.Response(200, json=page()), httpx.Response(202, json=task), httpx.Response(200, json={**task, "status": "succeeded", "result": page()}),
                            httpx.Response(200, json=markdown), httpx.Response(200, json=markdown)])
    client = NotionClient("secret-token", transport=httpx.MockTransport(transport))
    token = CancellationToken()
    assert client.retrieve_page(PAGE_ID, token).parent_id == PARENT_ID
    queued = client.create_page(PARENT_ID, "title", "# Report\n内容", token)
    assert isinstance(queued, NotionTask) and queued.state == NotionTaskState.QUEUED
    completed = client.retrieve_task(queued.task_id, token)
    assert completed.page is not None and completed.page.page_id == PAGE_ID
    assert client.retrieve_markdown(PAGE_ID, token).markdown == "# Report"
    replaced = client.replace_markdown(PAGE_ID, "# Report", token)
    assert isinstance(replaced, NotionMarkdown) and replaced.markdown == "# Report"
    request_body = json.loads(transport.requests[1].content)
    assert request_body["markdown"] == "# Report\n内容" and request_body["allow_async"] is True
    assert "children" not in request_body and transport.requests[1].headers["Notion-Version"] == NOTION_API_VERSION
    client.close()


def test_candidates_are_direct_children_and_all_pages_are_read() -> None:
    """候选枚举分页完整且不跟任意远端 URL。参数：无。返回：无。异常：断言失败。"""
    transport = _Transport([httpx.Response(200, json={"results": [{"type": "paragraph", "id": PAGE_ID}], "has_more": True, "next_cursor": "cursor"}),
                            httpx.Response(200, json={"results": [{"type": "child_page", "id": PAGE_ID}], "has_more": False})])
    client = NotionClient("secret", transport=httpx.MockTransport(transport))
    assert client.child_pages(PARENT_ID, CancellationToken()) == (PAGE_ID,)
    assert "start_cursor=cursor" in str(transport.requests[-1].url)
    client.close()


def test_committed_resource_identity_survives_503_without_retry() -> None:
    """503已提交身份必须交还持久层，禁止重发创建。参数：无。返回：无。异常：断言失败。"""
    transport = _Transport([httpx.Response(503, json={"code": "service_unavailable", "additional_data": {
        "committed_resource_id": PAGE_ID, "retry_guidance": ["Do not repeat the write."]}})])
    client = NotionClient("secret", transport=httpx.MockTransport(transport))
    with pytest.raises(NotionApiError) as failure:
        client.create_page(PARENT_ID, "title", "body", CancellationToken())
    assert failure.value.committed_resource_id == PAGE_ID
    assert failure.value.unknown and len(transport.requests) == 1
    client.close()


def test_transport_errors_and_limits_do_not_leak_secrets_or_retry_writes() -> None:
    """未知写入与明确限流不同，取消前不发请求。参数：无。返回：无。异常：断言失败。"""
    transport = _Transport([httpx.ReadTimeout("secret-token"), httpx.Response(429, json={"object": "error", "code": "rate_limited"}, headers={"Retry-After": "3"}),
                            httpx.Response(500, text="invalid"), httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))])
    client = NotionClient("secret-token", transport=httpx.MockTransport(transport))
    token = CancellationToken()
    with pytest.raises(NotionApiError) as unknown:
        client.create_page(PARENT_ID, "title", "body", token)
    assert unknown.value.unknown and "secret-token" not in str(unknown.value)
    with pytest.raises(NotionApiError) as limited:
        client.create_page(PARENT_ID, "title", "body", token)
    assert not limited.value.unknown and limited.value.retry_after == 3
    with pytest.raises(NotionApiError) as invalid:
        client.retrieve_page(PAGE_ID, token)
    assert not invalid.value.unknown
    with pytest.raises(NotionApiError, match="response_too_large"):
        client.retrieve_markdown(PAGE_ID, token)
    token.cancel()
    with pytest.raises(CancelledError):
        client.create_page(PARENT_ID, "title", "body", token)
    assert len(transport.requests) == 4
    client.close()


def test_decoders_reject_missing_completeness_and_invalid_poll_hint() -> None:
    """损坏响应不成为可发布结果。参数：无。返回：无。异常：断言失败。"""
    with pytest.raises(ValueError):
        decode_markdown({"markdown": "body"})
    with pytest.raises(ValueError):
        decode_task({"object": "async_task", "id": "task", "status": "running", "poll_after_seconds": True})
    failure = decode_task({"object": "async_task", "id": "task", "status": "failed", "error": {"status": 400, "code": "validation_error"}})
    assert failure.error_status == 400
