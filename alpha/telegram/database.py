"""Telegram 渠道 SQLite 事务基础设施；schema 由 init 与运行装配共用。"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3

_SCHEMA_VERSION = 1
_BUSY_TIMEOUT_MS = 10000
_SCHEMA = """
CREATE TABLE channel_schema(version INTEGER NOT NULL);
CREATE TABLE polling_offsets(bot_id INTEGER PRIMARY KEY, next_offset INTEGER NOT NULL);
CREATE TABLE inbox(
    bot_id INTEGER NOT NULL,update_id INTEGER NOT NULL,body_json TEXT NOT NULL,body_hash TEXT NOT NULL,
    state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,retry_at REAL NOT NULL DEFAULT 0,error TEXT,
    PRIMARY KEY(bot_id,update_id)
);
CREATE TABLE action_tokens(
    bot_id INTEGER NOT NULL,token TEXT NOT NULL,action_key TEXT NOT NULL,user_id INTEGER NOT NULL,chat_id INTEGER NOT NULL,thread_id INTEGER,
    action TEXT NOT NULL,research_id TEXT,revision_id TEXT,expected_version INTEGER,page_offset INTEGER NOT NULL,list_state TEXT,expires_at REAL NOT NULL,
    PRIMARY KEY(bot_id,token),UNIQUE(bot_id,action_key)
);
CREATE TABLE topic_provisions(
    bot_id INTEGER NOT NULL,research_id TEXT NOT NULL,user_id INTEGER NOT NULL,chat_id INTEGER NOT NULL,
    marker TEXT NOT NULL,name TEXT NOT NULL,state TEXT NOT NULL,thread_id INTEGER,error TEXT,
    PRIMARY KEY(bot_id,research_id),UNIQUE(bot_id,marker),UNIQUE(bot_id,chat_id,thread_id)
);
CREATE TABLE outbound_receipts(
    bot_id INTEGER NOT NULL,delivery_key TEXT NOT NULL,chat_id INTEGER NOT NULL,thread_id INTEGER,
    content_hash TEXT NOT NULL,state TEXT NOT NULL,message_id INTEGER,error TEXT,text_content TEXT,keyboard_json TEXT,
    PRIMARY KEY(bot_id,delivery_key)
);
"""


class TelegramDatabase:
    """每次操作独立连接，写事务串行；Bot 身份由各窄仓储固定。"""

    def __init__(self, path: Path) -> None:
        """初始化当前 schema。参数：数据库路径。返回：无。异常：未知 schema 或数据库错误。"""
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection(write=True) as conn:
            tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if not tables:
                for statement in _SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("INSERT INTO channel_schema VALUES (?)", (_SCHEMA_VERSION,))
            elif "channel_schema" not in tables:
                raise ValueError("Telegram 渠道库 schema 未知，请先执行显式工作区升级")
            versions = conn.execute("SELECT version FROM channel_schema").fetchall()
            if len(versions) != 1 or int(versions[0][0]) != _SCHEMA_VERSION:
                raise ValueError("Telegram 渠道库版本不受支持")

    @contextmanager
    def connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        """提供事务连接。参数：是否写入。返回：连接上下文。异常：数据库或调用方错误，写入回滚。"""
        conn = sqlite3.connect(self._path, timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
