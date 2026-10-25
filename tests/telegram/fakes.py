"""模拟 Telegram 远端状态，保留真实 HTTP 编码、渠道仓储与业务装配。"""

from dataclasses import dataclass, field
import json
from typing import cast

import httpx

from alpha.contracts.agent_types import JsonValue
from alpha.telegram.types import require_map


@dataclass
class TelegramServer:
    """可记录副作用后丢失响应的模拟服务器。"""

    updates: list[dict[str, JsonValue]] = field(default_factory=list)
    requests: list[tuple[str, dict[str, JsonValue]]] = field(default_factory=list)
    topics: list[dict[str, JsonValue]] = field(default_factory=list)
    messages: list[dict[str, JsonValue]] = field(default_factory=list)
    documents: int = 0
    files: dict[str, bytes] = field(default_factory=dict)
    unknown_topic: bool = False
    unknown_message: bool = False
    limited_message: bool = False
    _message_id: int = 100

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """处理 Bot API。参数：HTTP 请求。返回：响应。异常：注入的响应丢失。"""
        method = request.url.path.rsplit("/", maxsplit=1)[-1]
        if request.method == "GET":
            return httpx.Response(200, content=self.files[method])
        body = {} if method == "sendDocument" else require_map(cast(JsonValue, json.loads(request.content)))
        self.requests.append((method, body))
        result: JsonValue = True
        if method == "getMe":
            result = {"id": 123, "is_bot": True, "has_topics_enabled": True}
        elif method == "getFile":
            result = {"file_path": "documents/" + str(body["file_id"])}
        elif method == "getWebhookInfo":
            result = {"url": ""}
        elif method == "getUpdates":
            result = list(self.updates)
        elif method == "createForumTopic":
            self.topics.append({**body, "message_thread_id": len(self.topics) + 7})
            if self.unknown_topic:
                self.unknown_topic = False
                raise httpx.ReadTimeout("simulated lost topic response")
            result = {"message_thread_id": len(self.topics) + 6}
        elif method == "sendMessage":
            if self.limited_message:
                self.limited_message = False
                return httpx.Response(429, json={"ok": False, "error_code": 429, "parameters": {"retry_after": 0}})
            self._message_id += 1
            self.messages.append({**body, "message_id": self._message_id})
            if self.unknown_message:
                self.unknown_message = False
                raise httpx.ReadTimeout("simulated lost message response")
            result = {"message_id": self._message_id}
        elif method == "sendDocument":
            self.documents += 1
            self._message_id += 1
            result = {"message_id": self._message_id}
        return httpx.Response(200, json={"ok": True, "result": result})


def message(update_id: int, text: str, *, user_id: int = 42, thread_id: int | None = None) -> dict[str, JsonValue]:
    """构造私聊输入。参数：更新、正文、身份和话题。返回：原始更新。异常：无。"""
    return {"update_id": update_id, "message": {"message_id": update_id, "from": {"id": user_id},
                                               "chat": {"id": user_id, "type": "private"}, "message_thread_id": thread_id, "text": text}}


def callback(update_id: int, token: str, *, user_id: int = 42, chat_id: int = 42, thread_id: int | None = None) -> dict[str, JsonValue]:
    """构造卡片点击。参数：更新、token、身份及原卡片位置。返回：原始更新。异常：无。"""
    return {"update_id": update_id, "callback_query": {"id": f"cb-{update_id}", "from": {"id": user_id}, "data": token,
        "message": {"message_id": 5, "from": {"id": 123}, "chat": {"id": chat_id, "type": "private"}, "message_thread_id": thread_id}}}
