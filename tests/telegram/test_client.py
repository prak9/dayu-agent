"""Telegram 原生私聊话题协议、有界附件和密钥不泄漏测试。"""

import json
from dataclasses import dataclass, field
from typing import cast

import httpx
import pytest

from alpha.contracts.agent_types import JsonValue
from alpha.telegram.client import TelegramApiError, TelegramClient
from alpha.telegram.types import decode_incoming


@dataclass
class _Transport:
    """按顺序返回独立响应并记录实际请求。"""

    responses: list[httpx.Response | Exception]
    requests: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """处理模拟请求。参数：请求。返回：响应。异常：显式注入的传输故障。"""
        self.requests.append(request)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _ok(value: JsonValue) -> httpx.Response:
    """构造 API 成功响应。参数：结果。返回：响应。异常：无。"""
    return httpx.Response(200, json={"ok": True, "result": value})


@pytest.mark.asyncio
async def test_topics_preflight_poll_and_buttons_use_native_private_threads() -> None:
    """私聊话题发送保留 thread ID，且明确请求支持的更新类型。参数：无。返回：无。异常：断言失败。"""
    transport = _Transport([_ok({"id": 123, "is_bot": True, "has_topics_enabled": True}), _ok({"url": ""}),
                            _ok([]), _ok({"message_thread_id": 7}), _ok({"message_id": 9}), _ok(True), _ok(True)])
    client = TelegramClient("123:secret", transport=httpx.MockTransport(transport))
    assert await client.preflight() == 123
    assert await client.get_updates(10) == []
    assert await client.create_topic(1, "研究") == 7
    assert await client.send_message(1, 7, "纯文本 < &", keyboard=[[{"text": "状态", "callback_data": "short"}]]) == 9
    await client.edit_message(1, 9, "已完成")
    await client.answer_callback("callback")
    sent = json.loads(transport.requests[4].content)
    assert sent["message_thread_id"] == 7 and "parse_mode" not in sent
    assert json.loads(transport.requests[2].content)["offset"] == 10
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("bot,webhook", [({"is_bot": True}, {}), ({"is_bot": True, "has_topics_enabled": True}, {"url": "https://example.com"})])
async def test_preflight_does_not_change_bot_settings(bot: dict[str, JsonValue], webhook: dict[str, JsonValue]) -> None:
    """预检失败只报告，不自动删除 webhook。参数：Bot 与 webhook。返回：无。异常：断言失败。"""
    transport = _Transport([_ok(bot), _ok(webhook)])
    client = TelegramClient("123:secret", transport=httpx.MockTransport(transport))
    with pytest.raises(ValueError):
        await client.preflight()
    assert all("deleteWebhook" not in str(request.url) for request in transport.requests)
    await client.aclose()


@pytest.mark.asyncio
async def test_api_failures_classify_unknown_results_without_exposing_token() -> None:
    """网络未知和明确限流区别处理。参数：无。返回：无。异常：断言失败。"""
    transport = _Transport([httpx.ReadTimeout("secret URL https://api.telegram.org/bot123:secret/sendMessage"),
                            httpx.Response(429, json={"ok": False, "error_code": 429, "parameters": {"retry_after": 4}}),
                            httpx.Response(503, text="invalid JSON"), _ok({})])
    client = TelegramClient("123:secret", transport=httpx.MockTransport(transport))
    with pytest.raises(TelegramApiError) as unknown:
        await client.send_message(1, None, "hello")
    assert unknown.value.unknown and "secret" not in str(unknown.value)
    assert unknown.value.__cause__ is None
    with pytest.raises(TelegramApiError) as limited:
        await client.send_message(1, None, "hello")
    assert limited.value.retry_after == 4 and not limited.value.unknown
    with pytest.raises(TelegramApiError) as malformed:
        await client.send_message(1, None, "hello")
    assert malformed.value.unknown
    with pytest.raises(ValueError, match="数组"):
        await client.get_updates(0)
    for text in ("", "🚀" * 2049):
        with pytest.raises(ValueError):
            await client.send_message(1, None, text)
    with pytest.raises(ValueError):
        await client.create_topic(1, "x" * 129)
    await client.aclose()


@pytest.mark.asyncio
async def test_document_upload_and_download_enforce_actual_size() -> None:
    """文件限额检查实际字节而非信任元数据。参数：无。返回：无。异常：断言失败。"""
    transport = _Transport([_ok({"message_id": 4}), _ok({"file_path": "documents/a.pdf"}), httpx.Response(200, content=b"abcd"),
                            _ok({"file_path": "../escape"}), _ok({"file_path": "documents/b.pdf"}), httpx.Response(200, content=b"abcd")])
    client = TelegramClient("123:secret", transport=httpx.MockTransport(transport))
    assert await client.send_document(1, 7, "report.md", b"hello") == 4
    assert await client.download_document("file", max_bytes=4) == b"abcd"
    with pytest.raises(ValueError, match="路径"):
        await client.download_document("file")
    with pytest.raises(ValueError, match="实际大小"):
        await client.download_document("file", max_bytes=3)
    with pytest.raises(ValueError):
        await client.download_document("file", max_bytes=0)
    await client.aclose()


def test_callback_actor_is_sender_and_not_card_bot() -> None:
    """按钮操作者与原卡片发送人不同。参数：无。返回：无。异常：断言失败。"""
    update: dict[str, JsonValue] = {"update_id": 1, "callback_query": {"id": "cb", "from": {"id": 42}, "data": "token",
        "message": {"message_id": 2, "from": {"id": 123}, "chat": {"id": 42, "type": "private"}, "message_thread_id": 7}}}
    incoming = decode_incoming(update)
    assert incoming is not None and incoming.user_id == 42 and incoming.thread_id == 7
    assert decode_incoming({"update_id": 2, "edited_message": {}}) is None
    message = cast(dict[str, JsonValue], cast(dict[str, JsonValue], update["callback_query"])["message"])
    message["document"] = {"file_id": "file", "file_unique_id": "unique", "file_name": "a.pdf", "file_size": 4}
    with_document = decode_incoming(update)
    assert with_document is not None and with_document.document is not None and with_document.document.size == 4
