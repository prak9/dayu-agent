"""Telegram 边界解码与最小渠道 DTO。"""

from dataclasses import dataclass

from alpha.contracts.agent_types import JsonValue


def require_map(value: JsonValue) -> dict[str, JsonValue]:
    """要求 JSON 映射。参数：值。返回：映射。异常：类型非法时 ValueError。"""
    if not isinstance(value, dict):
        raise ValueError("Telegram 响应必须是 JSON 对象")
    return value


def require_int(value: JsonValue) -> int:
    """要求整数身份。参数：值。返回：整数。异常：布尔或非整数时 ValueError。"""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("Telegram 身份必须是整数")
    return value


def require_text(value: JsonValue) -> str:
    """要求字符串。参数：值。返回：字符串。异常：类型错误时 ValueError。"""
    if not isinstance(value, str):
        raise ValueError("Telegram 字段必须是字符串")
    return value


@dataclass(frozen=True)
class TelegramDocument:
    """尚未下载的文件元数据，不表示内容已提取。"""

    file_id: str
    unique_id: str
    name: str
    mime_type: str
    size: int | None


@dataclass(frozen=True)
class TelegramIncoming:
    """已解析消息或按钮；操作者身份不取自 Bot 发出的卡片。"""

    update_id: int
    user_id: int
    chat_id: int
    private: bool
    message_id: int
    thread_id: int | None
    text: str
    callback_id: str | None
    callback_data: str | None
    document: TelegramDocument | None
    topic_name: str | None


def decode_incoming(update: dict[str, JsonValue]) -> TelegramIncoming | None:
    """解码支持的消息。参数：原始更新。返回：消息或忽略。异常：所需字段损坏。"""
    update_id = require_int(update.get("update_id"))
    callback = require_map(update["callback_query"]) if "callback_query" in update else None
    raw_message = callback.get("message") if callback is not None else update.get("message")
    if raw_message is None:
        return None
    message = require_map(raw_message)
    sender = require_map(callback.get("from") if callback is not None else message.get("from"))
    chat = require_map(message.get("chat"))
    document = None
    if message.get("document") is not None:
        raw = require_map(message["document"])
        document = TelegramDocument(require_text(raw.get("file_id")), require_text(raw.get("file_unique_id")),
                                    require_text(raw.get("file_name", "document")), require_text(raw.get("mime_type", "application/octet-stream")),
                                    require_int(raw["file_size"]) if raw.get("file_size") is not None else None)
    topic = require_map(message["forum_topic_created"]) if message.get("forum_topic_created") is not None else None
    return TelegramIncoming(update_id, require_int(sender.get("id")), require_int(chat.get("id")), chat.get("type") == "private",
                            require_int(message.get("message_id")), require_int(message["message_thread_id"]) if message.get("message_thread_id") is not None else None,
                            require_text(message.get("text", message.get("caption", ""))),
                            require_text(callback.get("id")) if callback is not None else None,
                            require_text(callback.get("data")) if callback is not None else None, document,
                            require_text(topic.get("name")) if topic is not None else None)
