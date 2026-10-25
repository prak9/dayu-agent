"""整批先落库再推进 offset 的 Telegram 持久 inbox。"""

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import time
from typing import cast

from alpha.contracts.agent_types import JsonValue
from alpha.telegram.database import TelegramDatabase
from alpha.telegram.types import require_int, require_map


class InboxState(str, Enum):
    """渠道派发状态，不复制 Host Run 生命周期。"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class InboxItem:
    """持久更新及当前派发尝试。"""

    update_id: int
    update: dict[str, JsonValue]
    attempt: int


class SQLiteTelegramInbox:
    """Bot/update 去重，offset 与原始更新在同一事务内提交。"""

    def __init__(self, database: TelegramDatabase, bot_id: int) -> None:
        """注入存储。参数：渠道数据库、Bot ID。返回：无。异常：无。"""
        self._database = database
        self._bot_id = bot_id

    def offset(self) -> int:
        """读取确认位置。参数：无。返回：next offset。异常：数据库错误。"""
        with self._database.connection() as conn:
            row = conn.execute("SELECT next_offset FROM polling_offsets WHERE bot_id=?", (self._bot_id,)).fetchone()
            return int(row[0]) if row is not None else 0

    def accept_batch(self, updates: list[dict[str, JsonValue]]) -> int:
        """原子保存一批原始更新。参数：更新。返回：新 offset。异常：同 ID 内容冲突或数据非法。"""
        with self._database.connection(write=True) as conn:
            row = conn.execute("SELECT next_offset FROM polling_offsets WHERE bot_id=?", (self._bot_id,)).fetchone()
            offset = int(row[0]) if row is not None else 0
            for update in updates:
                update_id = require_int(update.get("update_id"))
                body = json.dumps(update, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                digest = hashlib.sha256(body.encode()).hexdigest()
                existing = conn.execute("SELECT body_hash FROM inbox WHERE bot_id=? AND update_id=?", (self._bot_id, update_id)).fetchone()
                if existing is not None and str(existing[0]) != digest:
                    raise ValueError("相同 Telegram update ID 内容冲突")
                conn.execute("INSERT OR IGNORE INTO inbox(bot_id,update_id,body_json,body_hash,state) VALUES (?,?,?,?,?)",
                             (self._bot_id, update_id, body, digest, InboxState.PENDING.value))
                offset = max(offset, update_id + 1)
            conn.execute("INSERT INTO polling_offsets VALUES (?,?) ON CONFLICT(bot_id) DO UPDATE SET next_offset=excluded.next_offset",
                         (self._bot_id, offset))
            return offset

    def claim_next(self) -> InboxItem | None:
        """领取最早可重试更新。参数：无。返回：更新或空。异常：数据库或完整性错误。"""
        with self._database.connection(write=True) as conn:
            row = conn.execute("SELECT * FROM inbox WHERE bot_id=? AND state=? AND retry_at<=? ORDER BY update_id LIMIT 1",
                               (self._bot_id, InboxState.PENDING.value, time.time())).fetchone()
            if row is None:
                return None
            body = str(row["body_json"])
            if hashlib.sha256(body.encode()).hexdigest() != str(row["body_hash"]):
                raise ValueError("Telegram 原始更新完整性损坏")
            conn.execute("UPDATE inbox SET state=?,attempts=attempts+1 WHERE bot_id=? AND update_id=?",
                         (InboxState.PROCESSING.value, self._bot_id, row["update_id"]))
            return InboxItem(int(row["update_id"]), require_map(cast(JsonValue, json.loads(body))), int(row["attempts"]) + 1)

    def finish(self, item: InboxItem, *, error: str | None = None, retry_after: float | None = None) -> None:
        """回写当前尝试。参数：更新、错误、可选重试延迟。返回：无。异常：过期尝试或数据库错误。"""
        state = InboxState.PENDING if retry_after is not None else InboxState.FAILED if error is not None else InboxState.COMPLETED
        with self._database.connection(write=True) as conn:
            changed = conn.execute("UPDATE inbox SET state=?,error=?,retry_at=? WHERE bot_id=? AND update_id=? AND state=? AND attempts=?",
                                   (state.value, error, time.time() + (retry_after or 0), self._bot_id, item.update_id,
                                    InboxState.PROCESSING.value, item.attempt)).rowcount
            if changed != 1:
                raise ValueError("Telegram inbox 派发尝试已过期")

    def recover_interrupted(self) -> int:
        """单实例锁获取后恢复中断派发。参数：无。返回：恢复数量。异常：数据库错误。"""
        with self._database.connection(write=True) as conn:
            return conn.execute("UPDATE inbox SET state=? WHERE bot_id=? AND state=?",
                                (InboxState.PENDING.value, self._bot_id, InboxState.PROCESSING.value)).rowcount
