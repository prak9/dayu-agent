"""渠道消息和附件回执：记录未知发送，避免崩溃恢复时盲目重发。"""

from dataclasses import dataclass
from enum import Enum
import sqlite3

from alpha.telegram.database import TelegramDatabase


class DeliveryState(str, Enum):
    """渠道副作用状态，独立于研究和 Host 执行。"""

    PENDING = "pending"
    SENDING = "sending"
    DELIVERED = "delivered"
    UNKNOWN = "unknown"
    FAILED = "failed"


@dataclass(frozen=True)
class TelegramReceipt:
    """消息或附件的固定意图及远端回执。"""

    key: str
    chat_id: int
    thread_id: int | None
    content_hash: str
    state: DeliveryState
    message_id: int | None
    text_content: str | None
    keyboard_json: str | None


def _receipt(row: sqlite3.Row) -> TelegramReceipt:
    """映射回执。参数：数据行。返回：回执。异常：损坏字段。"""
    return TelegramReceipt(str(row["delivery_key"]), int(row["chat_id"]), int(row["thread_id"]) if row["thread_id"] is not None else None,
                           str(row["content_hash"]), DeliveryState(str(row["state"])), int(row["message_id"]) if row["message_id"] is not None else None,
                           str(row["text_content"]) if row["text_content"] is not None else None,
                           str(row["keyboard_json"]) if row["keyboard_json"] is not None else None)


class SQLiteTelegramDeliveries:
    """固定渠道交付键的内容与位置，单实例持有发送权。"""

    def __init__(self, database: TelegramDatabase, bot_id: int) -> None:
        """注入存储。参数：数据库、Bot。返回：无。异常：无。"""
        self._database = database
        self._bot_id = bot_id

    def prepare(self, key: str, chat_id: int, thread_id: int | None, content_hash: str, *, text_content: str | None = None, keyboard_json: str | None = None) -> TelegramReceipt:
        """持久保存发送意图。参数：稳定键、位置、完整内容摘要。返回：回执。异常：同键内容或位置变化。"""
        if not key or not content_hash:
            raise ValueError("渠道交付键与内容摘要不能为空")
        with self._database.connection(write=True) as conn:
            existing = conn.execute("SELECT * FROM outbound_receipts WHERE bot_id=? AND delivery_key=?", (self._bot_id, key)).fetchone()
            if existing is not None:
                receipt = _receipt(existing)
                if (receipt.chat_id, receipt.thread_id, receipt.content_hash) != (chat_id, thread_id, content_hash):
                    raise ValueError("同一渠道交付键的内容或位置发生变化")
                return receipt
            conn.execute("INSERT INTO outbound_receipts VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (self._bot_id, key, chat_id, thread_id, content_hash, DeliveryState.PENDING.value, None, None, text_content, keyboard_json))
            return _receipt(conn.execute("SELECT * FROM outbound_receipts WHERE bot_id=? AND delivery_key=?", (self._bot_id, key)).fetchone())

    def get(self, key: str) -> TelegramReceipt | None:
        """读取首次冻结的交付。参数：键。返回：回执或空。异常：数据库错误。"""
        with self._database.connection() as conn:
            row = conn.execute("SELECT * FROM outbound_receipts WHERE bot_id=? AND delivery_key=?", (self._bot_id, key)).fetchone()
            return _receipt(row) if row is not None else None

    def claim(self, key: str) -> bool:
        """领取未发送意图。参数：键。返回：是否成功。异常：数据库错误。"""
        with self._database.connection(write=True) as conn:
            return conn.execute("UPDATE outbound_receipts SET state=? WHERE bot_id=? AND delivery_key=? AND state=?",
                                (DeliveryState.SENDING.value, self._bot_id, key, DeliveryState.PENDING.value)).rowcount == 1

    def acknowledge(self, key: str, message_id: int) -> TelegramReceipt:
        """记录已知发送结果。参数：键、message ID。返回：回执。异常：状态冲突。"""
        with self._database.connection(write=True) as conn:
            row = conn.execute("SELECT * FROM outbound_receipts WHERE bot_id=? AND delivery_key=?", (self._bot_id, key)).fetchone()
            if row is None or (str(row["state"]) != DeliveryState.SENDING.value and row["message_id"] != message_id):
                raise ValueError("交付未领取或远端消息 ID 冲突")
            conn.execute("UPDATE outbound_receipts SET state=?,message_id=?,error=NULL WHERE bot_id=? AND delivery_key=?",
                         (DeliveryState.DELIVERED.value, message_id, self._bot_id, key))
            return _receipt(conn.execute("SELECT * FROM outbound_receipts WHERE bot_id=? AND delivery_key=?", (self._bot_id, key)).fetchone())

    def fail(self, key: str, *, unknown: bool, retryable: bool, error: str) -> None:
        """记录失败或未知结果。参数：键、未知、可重试、错误。返回：无。异常：状态冲突。"""
        state = DeliveryState.UNKNOWN if unknown else DeliveryState.PENDING if retryable else DeliveryState.FAILED
        with self._database.connection(write=True) as conn:
            if conn.execute("UPDATE outbound_receipts SET state=?,error=? WHERE bot_id=? AND delivery_key=? AND state=?",
                            (state.value, error, self._bot_id, key, DeliveryState.SENDING.value)).rowcount != 1:
                raise ValueError("渠道交付状态已改变")

    def recover_interrupted(self) -> int:
        """将崩溃时发送中标为未知。参数：无。返回：数量。异常：数据库错误。"""
        with self._database.connection(write=True) as conn:
            return conn.execute("UPDATE outbound_receipts SET state=? WHERE bot_id=? AND state=?",
                                (DeliveryState.UNKNOWN.value, self._bot_id, DeliveryState.SENDING.value)).rowcount
