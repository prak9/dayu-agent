"""Telegram offset/更新同事务、跨重启重放及 Bot 隔离测试。"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from alpha.cli.workspace_migrations.telegram_store_init import migrate_telegram_store_init
from alpha.telegram.database import TelegramDatabase
from alpha.telegram.inbox import InboxItem, SQLiteTelegramInbox


def test_entire_batch_and_offset_are_atomic(tmp_path: Path) -> None:
    """批内后续冲突回滚前面的新消息和 offset。参数：目录。返回：无。异常：断言失败。"""
    database = TelegramDatabase(tmp_path / "channel.db")
    inbox = SQLiteTelegramInbox(database, 1)
    assert inbox.offset() == 0
    assert inbox.accept_batch([{"update_id": 10, "message": {}}]) == 11
    assert inbox.accept_batch([{"update_id": 10, "message": {}}]) == 11
    with pytest.raises(ValueError, match="冲突"):
        inbox.accept_batch([{"update_id": 11}, {"update_id": 10, "message": {"text": "changed"}}])
    assert inbox.offset() == 11
    first = inbox.claim_next()
    assert first is not None and first.update_id == 10
    assert inbox.claim_next() is None
    other = SQLiteTelegramInbox(TelegramDatabase(tmp_path / "channel.db"), 1)
    assert other.recover_interrupted() == 1
    retry = other.claim_next()
    assert retry is not None and retry.attempt == 2
    with pytest.raises(ValueError, match="过期"):
        inbox.finish(first)
    other.finish(retry)
    assert other.claim_next() is None
    assert SQLiteTelegramInbox(database, 2).offset() == 0


def test_concurrent_claim_and_retry(tmp_path: Path) -> None:
    """独立连接不能领取同一尝试。参数：目录。返回：无。异常：断言失败。"""
    inbox = SQLiteTelegramInbox(TelegramDatabase(tmp_path / "channel.db"), 1)
    inbox.accept_batch([{"update_id": 1}])
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(_claim, [inbox, inbox]))
    assert sum(item is not None for item in claims) == 1
    first = next(item for item in claims if item is not None)
    inbox.finish(first, error="limited", retry_after=0)
    second = inbox.claim_next()
    assert second is not None and second.attempt == 2
    inbox.finish(second, error="terminal")
    assert inbox.claim_next() is None


def _claim(inbox: SQLiteTelegramInbox) -> InboxItem | None:
    """线程领取。参数：inbox。返回：尝试。异常：存储错误。"""
    return inbox.claim_next()


def test_unknown_schema_and_damaged_inbox_are_not_silently_read(tmp_path: Path) -> None:
    """未知 schema 和完整性损坏明确失败。参数：目录。返回：无。异常：断言失败。"""
    database = TelegramDatabase(tmp_path / "channel.db")
    inbox = SQLiteTelegramInbox(database, 1)
    inbox.accept_batch([{"update_id": 1}])
    with database.connection(write=True) as conn:
        conn.execute("UPDATE inbox SET body_json='{}'")
    with pytest.raises(ValueError, match="完整性"):
        inbox.claim_next()
    with database.connection(write=True) as conn:
        conn.execute("UPDATE channel_schema SET version=99")
    with pytest.raises(ValueError, match="版本"):
        TelegramDatabase(tmp_path / "channel.db")
    assert migrate_telegram_store_init(tmp_path) is True
    assert migrate_telegram_store_init(tmp_path) is False
