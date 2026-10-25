"""持久发送意图与 API 回执桥接；未知写结果需要用户核对。"""

from dataclasses import dataclass
import hashlib
import json
from typing import cast

from alpha.contracts.agent_types import JsonValue
from alpha.telegram.client import TelegramApiError, TelegramClient
from alpha.telegram.deliveries import DeliveryState, SQLiteTelegramDeliveries


class TelegramDeliveryUnknownError(RuntimeError):
    """发送可能已生效，不能自动重复发送。"""


@dataclass(frozen=True)
class TelegramSender:
    """固定发送内容，在 HTTP 返回后先保存回执再确认上层 outbox。"""

    client: TelegramClient
    receipts: SQLiteTelegramDeliveries

    async def text(self, key: str, chat_id: int, thread_id: int | None, text: str, *, keyboard: list[JsonValue] | None = None) -> int:
        """幂等发送文字。参数：稳定键、地址、正文、按钮。返回：已知消息 ID。异常：结果未知、失败或 API 错误。"""
        digest = hashlib.sha256(json.dumps({"text": text, "keyboard": keyboard}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        receipt = self.receipts.get(key)
        if receipt is None:
            receipt = self.receipts.prepare(key, chat_id, thread_id, digest, text_content=text,
                                           keyboard_json=json.dumps(keyboard, ensure_ascii=False, sort_keys=True))
        if (receipt.chat_id, receipt.thread_id) != (chat_id, thread_id) or receipt.text_content is None:
            raise ValueError("同一文字交付键的类型或地址改变")
        # 动态状态卡只在首次发送前冻结；限流和重启重试不能将内容替换成后来状态。
        text = receipt.text_content
        restored_keyboard = cast(JsonValue, json.loads(receipt.keyboard_json or "null"))
        if restored_keyboard is not None and not isinstance(restored_keyboard, list):
            raise ValueError("按钮快照损坏")
        keyboard = restored_keyboard
        actual_digest = hashlib.sha256(json.dumps({"text": text, "keyboard": keyboard}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if actual_digest != receipt.content_hash:
            raise ValueError("文字交付快照完整性损坏")
        if receipt.state == DeliveryState.DELIVERED and receipt.message_id is not None:
            return receipt.message_id
        if receipt.state in (DeliveryState.UNKNOWN, DeliveryState.SENDING):
            raise TelegramDeliveryUnknownError(f"消息发送结果未知，请检查 Telegram；交付键 {key}")
        if not self.receipts.claim(key):
            raise RuntimeError("消息交付失败，需要使用新的明确发送请求")
        try:
            message_id = await self.client.send_message(chat_id, thread_id, text, keyboard=keyboard)
        except TelegramApiError as exc:
            self.receipts.fail(key, unknown=exc.unknown, retryable=exc.retry_after is not None, error=str(exc))
            raise
        self.receipts.acknowledge(key, message_id)
        return message_id

    async def document(self, key: str, chat_id: int, thread_id: int | None, name: str, content: bytes) -> int:
        """幂等发送文件。参数：稳定键、地址、文件名与字节。返回：已知消息 ID。异常：未知结果、失败或 API 错误。"""
        digest = hashlib.sha256(name.encode() + b"\0" + content).hexdigest()
        receipt = self.receipts.prepare(key, chat_id, thread_id, digest)
        if receipt.state == DeliveryState.DELIVERED and receipt.message_id is not None:
            return receipt.message_id
        if receipt.state in (DeliveryState.UNKNOWN, DeliveryState.SENDING):
            raise TelegramDeliveryUnknownError(f"文件发送结果未知，请检查 Telegram；交付键 {key}")
        if not self.receipts.claim(key):
            raise RuntimeError("文件交付失败，需要使用新的明确发送请求")
        try:
            message_id = await self.client.send_document(chat_id, thread_id, name, content)
        except TelegramApiError as exc:
            self.receipts.fail(key, unknown=exc.unknown, retryable=exc.retry_after is not None, error=str(exc))
            raise
        self.receipts.acknowledge(key, message_id)
        return message_id
