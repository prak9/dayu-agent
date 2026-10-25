"""持久按钮 token：服务端固定动作和版本，校验卡片位置与操作者。"""

from dataclasses import dataclass
from enum import Enum
import secrets
import sqlite3
import time

from alpha.telegram.database import TelegramDatabase

_TOKEN_BYTES = 12
_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60


class ResearchAction(str, Enum):
    """首版明确开放的研究管理动作。"""

    LIST = "list"
    STATUS = "status"
    STOP = "stop"
    ARCHIVE = "archive"
    REOPEN = "reopen"
    REPORT = "report"
    PUBLISH = "publish"
    UPDATE = "update"
    COUNTERCASE = "countercase"


@dataclass(frozen=True)
class ActionToken:
    """按钮绑定的不可变业务目标。"""

    token: str
    action: ResearchAction
    research_id: str | None
    revision_id: str | None
    expected_version: int | None
    page_offset: int
    list_state: str | None


def _action(row: sqlite3.Row) -> ActionToken:
    """映射按钮。参数：数据行。返回：动作。异常：数据损坏。"""
    return ActionToken(str(row["token"]), ResearchAction(str(row["action"])),
                       str(row["research_id"]) if row["research_id"] is not None else None,
                       str(row["revision_id"]) if row["revision_id"] is not None else None,
                       int(row["expected_version"]) if row["expected_version"] is not None else None,
                       int(row["page_offset"]), str(row["list_state"]) if row["list_state"] is not None else None)


class SQLiteTelegramActions:
    """短 token 不携带可篡改参数，同一卡片重试复用原 token。"""

    def __init__(self, database: TelegramDatabase, bot_id: int) -> None:
        """注入存储。参数：数据库、Bot。返回：无。异常：无。"""
        self._database = database
        self._bot_id = bot_id

    def issue(
        self, action_key: str, *, user_id: int, chat_id: int, thread_id: int | None, action: ResearchAction,
        research_id: str | None = None, revision_id: str | None = None, expected_version: int | None = None,
        page_offset: int = 0, list_state: str | None = None,
    ) -> ActionToken:
        """签发按钮。参数：稳定卡片键、身份位置、动作及显式目标。返回：token。异常：同键改变目标。"""
        if not action_key:
            raise ValueError("按钮键不能为空")
        with self._database.connection(write=True) as conn:
            existing = conn.execute("SELECT * FROM action_tokens WHERE bot_id=? AND action_key=?", (self._bot_id, action_key)).fetchone()
            expected = (user_id, chat_id, thread_id, action.value, research_id, revision_id, expected_version, page_offset, list_state)
            if existing is not None:
                actual = tuple(existing[name] for name in ("user_id", "chat_id", "thread_id", "action", "research_id", "revision_id", "expected_version", "page_offset", "list_state"))
                if actual != expected:
                    raise ValueError("相同按钮键的目标发生变化")
                return _action(existing)
            token = secrets.token_urlsafe(_TOKEN_BYTES)
            conn.execute("INSERT INTO action_tokens VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (self._bot_id, token, action_key, *expected, time.time() + _TOKEN_TTL_SECONDS))
            row = conn.execute("SELECT * FROM action_tokens WHERE bot_id=? AND token=?", (self._bot_id, token)).fetchone()
            return _action(row)

    def resolve(self, token: str, *, user_id: int, chat_id: int, thread_id: int | None) -> ActionToken:
        """验证点击来源。参数：token、真实操作者及卡片位置。返回：固定动作。异常：未知、过期或越权。"""
        with self._database.connection() as conn:
            row = conn.execute("SELECT * FROM action_tokens WHERE bot_id=? AND token=?", (self._bot_id, token)).fetchone()
            if row is None or float(row["expires_at"]) < time.time():
                raise ValueError("按钮不存在或已过期，请重新打开研究列表")
            if (row["user_id"], row["chat_id"], row["thread_id"]) != (user_id, chat_id, thread_id):
                raise PermissionError("按钮不属于当前操作者或会话话题")
            return _action(row)
