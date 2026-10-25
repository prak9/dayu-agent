"""以现有 httpx 实现 Telegram Bot API；异常文本不泄漏 URL 中的 Bot token。"""

from __future__ import annotations

import json
from typing import cast

import httpx

from alpha.contracts.agent_types import JsonValue
from alpha.telegram.types import require_int, require_map, require_text

_API_ROOT = "https://api.telegram.org"
_REQUEST_TIMEOUT = 45.0
_POLL_TIMEOUT = 30
_MAX_UPDATE_BATCH = 100
_MAX_FILE_BYTES = 20 * 1024 * 1024
_MAX_TEXT_UNITS = 4096


class TelegramApiError(RuntimeError):
    """安全错误；unknown 表示副作用结果未知，不能盲目重发。"""

    def __init__(self, code: int, *, retry_after: int | None = None, unknown: bool = False) -> None:
        """保存分类。参数：API 状态码、退避秒数、结果未知。返回：无。异常：无。"""
        self.code = code
        self.retry_after = retry_after
        self.unknown = unknown
        super().__init__(f"Telegram 请求失败，code={code}，结果{'未知' if unknown else '明确拒绝'}")


class TelegramClient:
    """一个 Bot 的有界 HTTP 客户端；不持久化凭据、不自动重试写操作。"""

    def __init__(self, token: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """创建客户端。参数：token 密钥、测试传输层。返回：无。异常：空密钥时 ValueError。"""
        if not token.strip() or "/" in token or any(character.isspace() for character in token):
            raise ValueError("Telegram Bot token 格式非法")
        self._base = f"{_API_ROOT}/bot{token}"
        self._file_base = f"{_API_ROOT}/file/bot{token}"
        self._http = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, transport=transport, follow_redirects=False)

    async def aclose(self) -> None:
        """关闭连接池。参数：无。返回：无。异常：连接关闭失败。"""
        await self._http.aclose()

    async def _call(self, method: str, parameters: dict[str, JsonValue]) -> JsonValue:
        """调用固定 API。参数：方法与 API 字段。返回：result。异常：安全分类的 API 错误。"""
        try:
            response = await self._http.post(f"{self._base}/{method}", json=parameters)
        except httpx.HTTPError:
            raise TelegramApiError(0, unknown=True) from None
        try:
            body = require_map(cast(JsonValue, response.json()))
        except (ValueError, json.JSONDecodeError):
            raise TelegramApiError(response.status_code, unknown=True) from None
        if body.get("ok") is not True:
            retry = require_map(body["parameters"]).get("retry_after") if isinstance(body.get("parameters"), dict) else None
            code = require_int(body.get("error_code", response.status_code))
            raise TelegramApiError(code, retry_after=require_int(retry) if retry is not None else None, unknown=code >= 500)
        return body.get("result")

    async def preflight(self) -> int:
        """验证 Bot、话题模式和长轮询条件。参数：无。返回：Bot ID。异常：未启话题、已有 webhook 或 API 错误。"""
        bot = require_map(await self._call("getMe", {}))
        if bot.get("is_bot") is not True or bot.get("has_topics_enabled") is not True:
            raise ValueError("请先在 BotFather 为该 Bot 启用私聊话题模式")
        webhook = require_map(await self._call("getWebhookInfo", {}))
        if webhook.get("url"):
            raise ValueError("该 Bot 已配置 webhook；请显式移除后再启用 alpha 长轮询")
        return require_int(bot.get("id"))

    async def get_updates(self, offset: int) -> list[dict[str, JsonValue]]:
        """长轮询消息。参数：已持久化 offset。返回：更新。异常：API 或格式错误。"""
        result = await self._call("getUpdates", {"offset": offset, "limit": _MAX_UPDATE_BATCH, "timeout": _POLL_TIMEOUT,
                                                  "allowed_updates": ["message", "callback_query"]})
        if not isinstance(result, list):
            raise ValueError("Telegram 更新响应不是数组")
        return [require_map(item) for item in result]

    async def create_topic(self, chat_id: int, name: str) -> int:
        """创建原生话题。参数：私聊、含操作标记的标题。返回：thread ID。异常：API 或标题错误。"""
        if not name or len(name) > 128:
            raise ValueError("Telegram 话题标题须为 1–128 字符")
        return require_int(require_map(await self._call("createForumTopic", {"chat_id": chat_id, "name": name})).get("message_thread_id"))

    async def send_message(self, chat_id: int, thread_id: int | None, text: str, *, keyboard: list[JsonValue] | None = None) -> int:
        """发送纯文本卡片。参数：会话、话题、正文、按钮行。返回：message ID。异常：超限或 API 错误。"""
        if not text or len(text.encode("utf-16-le")) // 2 > _MAX_TEXT_UNITS:
            raise ValueError("Telegram 正文为空或超过 4096 UTF-16 单位")
        parameters: dict[str, JsonValue] = {"chat_id": chat_id, "text": text}
        if thread_id is not None:
            parameters["message_thread_id"] = thread_id
        if keyboard is not None:
            parameters["reply_markup"] = {"inline_keyboard": keyboard}
        return require_int(require_map(await self._call("sendMessage", parameters)).get("message_id"))

    async def edit_message(self, chat_id: int, message_id: int, text: str) -> None:
        """编辑已知进度卡。参数：会话、消息、正文。返回：无。异常：API 错误。"""
        await self._call("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text})

    async def answer_callback(self, callback_id: str, text: str = "已接受") -> None:
        """及时应答按钮。参数：callback ID、提示。返回：无。异常：API 错误。"""
        await self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    async def send_document(self, chat_id: int, thread_id: int | None, name: str, content: bytes) -> int:
        """上传报告文件。参数：会话、话题、文件名、完整内容。返回：message ID。异常：超限或未知发送结果。"""
        if len(content) > _MAX_FILE_BYTES:
            raise ValueError("报告文件超过渠道上传上限")
        data = {"chat_id": str(chat_id)}
        if thread_id is not None:
            data["message_thread_id"] = str(thread_id)
        try:
            response = await self._http.post(f"{self._base}/sendDocument", data=data, files={"document": (name, content, "text/markdown")})
            body = require_map(cast(JsonValue, response.json()))
        except (httpx.HTTPError, ValueError):
            raise TelegramApiError(0, unknown=True) from None
        if body.get("ok") is not True:
            raise TelegramApiError(response.status_code, unknown=response.status_code >= 500)
        return require_int(require_map(body.get("result")).get("message_id"))

    async def download_document(self, file_id: str, *, max_bytes: int = _MAX_FILE_BYTES) -> bytes:
        """有界下载附件。参数：文件 ID、本地上限。返回：字节。异常：路径非法、超限或下载错误。"""
        if not 0 < max_bytes <= _MAX_FILE_BYTES:
            raise ValueError("附件上限须在渠道支持范围内")
        info = require_map(await self._call("getFile", {"file_id": file_id}))
        path = require_text(info.get("file_path"))
        if path.startswith("/") or ".." in path.split("/") or ":" in path or "\\" in path:
            raise ValueError("Telegram 文件路径非法")
        content = bytearray()
        try:
            async with self._http.stream("GET", f"{self._file_base}/{path}") as response:
                if response.status_code != 200:
                    raise TelegramApiError(response.status_code)
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise ValueError("附件实际大小超过上限")
        except httpx.HTTPError:
            raise TelegramApiError(0) from None
        return bytes(content)
