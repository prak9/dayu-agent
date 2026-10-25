"""原生话题创建操作日志；未知响应只调和，不盲目重建。"""

from dataclasses import dataclass
from enum import Enum
import secrets
import sqlite3

from alpha.telegram.database import TelegramDatabase

_MARKER_BYTES = 8
_MAX_TOPIC_NAME = 128


class TopicState(str, Enum):
    """话题 provisioning 状态。"""

    PENDING = "pending"
    CREATING = "creating"
    READY = "ready"
    UNKNOWN = "unknown"
    FAILED = "failed"


@dataclass(frozen=True)
class TopicProvision:
    """已持久生成的创建身份，不按公司名或相同标题绑定。"""

    research_id: str
    user_id: int
    chat_id: int
    marker: str
    name: str
    state: TopicState
    thread_id: int | None


def _provision(row: sqlite3.Row) -> TopicProvision:
    """映射操作。参数：行。返回：创建状态。异常：损坏字段。"""
    return TopicProvision(str(row["research_id"]), int(row["user_id"]), int(row["chat_id"]), str(row["marker"]), str(row["name"]),
                          TopicState(str(row["state"])), int(row["thread_id"]) if row["thread_id"] is not None else None)


class SQLiteTelegramTopics:
    """先持久创建标记，得到 thread 后才能研究派发。"""

    def __init__(self, database: TelegramDatabase, bot_id: int) -> None:
        """注入存储。参数：数据库、Bot。返回：无。异常：无。"""
        self._database = database
        self._bot_id = bot_id

    def prepare(self, research_id: str, user_id: int, chat_id: int, title: str) -> TopicProvision:
        """固定创建操作。参数：研究、操作者、私聊、标题。返回：操作。异常：目标改变或存储错误。"""
        with self._database.connection(write=True) as conn:
            existing = conn.execute("SELECT * FROM topic_provisions WHERE bot_id=? AND research_id=?", (self._bot_id, research_id)).fetchone()
            if existing is not None:
                if (existing["user_id"], existing["chat_id"]) != (user_id, chat_id):
                    raise PermissionError("话题创建操作属于其他用户或会话")
                return _provision(existing)
            marker = secrets.token_hex(_MARKER_BYTES)
            name = f"[alpha:{marker}] {title}"[:_MAX_TOPIC_NAME]
            conn.execute("INSERT INTO topic_provisions VALUES (?,?,?,?,?,?,?,?,?)",
                         (self._bot_id, research_id, user_id, chat_id, marker, name, TopicState.PENDING.value, None, None))
            return _provision(conn.execute("SELECT * FROM topic_provisions WHERE bot_id=? AND research_id=?", (self._bot_id, research_id)).fetchone())

    def claim(self, research_id: str) -> bool:
        """领取尚未发送创建的操作。参数：研究。返回：是否成功。异常：数据库错误。"""
        with self._database.connection(write=True) as conn:
            return conn.execute("UPDATE topic_provisions SET state=? WHERE bot_id=? AND research_id=? AND state=?",
                                (TopicState.CREATING.value, self._bot_id, research_id, TopicState.PENDING.value)).rowcount == 1

    def record_failure(self, research_id: str, *, unknown: bool, retryable: bool, error: str) -> None:
        """记录已发送创建的失败。参数：研究、结果未知、明确可重试、错误。返回：无。异常：状态冲突。"""
        state = TopicState.UNKNOWN if unknown else TopicState.PENDING if retryable else TopicState.FAILED
        with self._database.connection(write=True) as conn:
            changed = conn.execute("UPDATE topic_provisions SET state=?,error=? WHERE bot_id=? AND research_id=? AND state=?",
                                   (state.value, error, self._bot_id, research_id, TopicState.CREATING.value)).rowcount
            if changed != 1:
                raise ValueError("话题创建操作已被其他更新调和")

    def confirm(self, research_id: str, user_id: int, chat_id: int, thread_id: int) -> TopicProvision:
        """记录响应或显式绑定确认。参数：研究、身份、完整话题地址。返回：就绪操作。异常：越权或不同 thread 冲突。"""
        with self._database.connection(write=True) as conn:
            row = conn.execute("SELECT * FROM topic_provisions WHERE bot_id=? AND research_id=?", (self._bot_id, research_id)).fetchone()
            if row is None:
                raise KeyError("话题创建操作不存在")
            if (row["user_id"], row["chat_id"]) != (user_id, chat_id):
                raise PermissionError("话题创建操作者不匹配")
            if row["thread_id"] is not None and int(row["thread_id"]) != thread_id:
                raise ValueError("同一研究出现多个候选话题，需要人工核对")
            conn.execute("UPDATE topic_provisions SET state=?,thread_id=?,error=NULL WHERE bot_id=? AND research_id=?",
                         (TopicState.READY.value, thread_id, self._bot_id, research_id))
            return _provision(conn.execute("SELECT * FROM topic_provisions WHERE bot_id=? AND research_id=?", (self._bot_id, research_id)).fetchone())

    def find_marker(self, user_id: int, chat_id: int, name: str) -> TopicProvision | None:
        """用持久操作标记调和服务消息。参数：身份、完整含标记标题。返回：操作或空。异常：数据库错误。"""
        with self._database.connection() as conn:
            row = conn.execute("SELECT * FROM topic_provisions WHERE bot_id=? AND user_id=? AND chat_id=? AND name=?",
                               (self._bot_id, user_id, chat_id, name)).fetchone()
            return _provision(row) if row is not None else None

    def recover_interrupted(self) -> int:
        """启动时将中断创建标记为未知。参数：无。返回：数量。异常：数据库错误。"""
        with self._database.connection(write=True) as conn:
            return conn.execute("UPDATE topic_provisions SET state=? WHERE bot_id=? AND state=?",
                                (TopicState.UNKNOWN.value, self._bot_id, TopicState.CREATING.value)).rowcount

    def ready(self) -> list[TopicProvision]:
        """列出可修复跨库绑定的就绪话题。参数：无。返回：操作列表。异常：数据库错误。"""
        with self._database.connection() as conn:
            return [_provision(row) for row in conn.execute("SELECT * FROM topic_provisions WHERE bot_id=? AND state=?",
                                                           (self._bot_id, TopicState.READY.value)).fetchall()]
