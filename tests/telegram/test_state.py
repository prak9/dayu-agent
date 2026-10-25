"""话题未知创建、按钮目标固定和交付回执的恢复测试。"""

from pathlib import Path

import pytest

from alpha.telegram.actions import ResearchAction, SQLiteTelegramActions
from alpha.telegram.database import TelegramDatabase
from alpha.telegram.deliveries import DeliveryState, SQLiteTelegramDeliveries
from alpha.telegram.topics import SQLiteTelegramTopics, TopicState


def test_tokens_bind_exact_actor_location_and_revision(tmp_path: Path) -> None:
    """旧版本按钮保持旧版本目标且不能跨话题点击。参数：目录。返回：无。异常：断言失败。"""
    database = TelegramDatabase(tmp_path / "channel.db")
    actions = SQLiteTelegramActions(database, 1)
    token = actions.issue("card:publish", user_id=42, chat_id=42, thread_id=7, action=ResearchAction.PUBLISH, research_id="research", revision_id="v1")
    assert len(token.token.encode()) <= 64
    assert actions.issue("card:publish", user_id=42, chat_id=42, thread_id=7, action=ResearchAction.PUBLISH, research_id="research", revision_id="v1") == token
    assert actions.resolve(token.token, user_id=42, chat_id=42, thread_id=7).revision_id == "v1"
    with pytest.raises(ValueError, match="目标"):
        actions.issue("card:publish", user_id=42, chat_id=42, thread_id=7, action=ResearchAction.PUBLISH, revision_id="v2")
    for user, chat, topic in ((43, 42, 7), (42, 43, 7), (42, 42, 8)):
        with pytest.raises(PermissionError):
            actions.resolve(token.token, user_id=user, chat_id=chat, thread_id=topic)
    with pytest.raises(ValueError):
        SQLiteTelegramActions(database, 2).resolve(token.token, user_id=42, chat_id=42, thread_id=7)
    with database.connection(write=True) as conn:
        conn.execute("UPDATE action_tokens SET expires_at=0")
    with pytest.raises(ValueError, match="过期"):
        actions.resolve(token.token, user_id=42, chat_id=42, thread_id=7)


def test_unknown_topic_creation_requires_marker_or_explicit_confirmation(tmp_path: Path) -> None:
    """创建后退出不能盲目再建同名话题。参数：目录。返回：无。异常：断言失败。"""
    database = TelegramDatabase(tmp_path / "channel.db")
    topics = SQLiteTelegramTopics(database, 1)
    first = topics.prepare("research", 42, 42, "同一公司研究")
    assert topics.prepare("research", 42, 42, "changed title") == first
    assert topics.claim("research") and not topics.claim("research")
    assert topics.recover_interrupted() == 1
    unknown = topics.prepare("research", 42, 42, first.name)
    assert unknown.state == TopicState.UNKNOWN and not topics.claim("research")
    assert topics.find_marker(42, 42, "同一公司研究") is None
    assert topics.find_marker(43, 42, first.name) is None
    assert topics.find_marker(42, 42, first.name) == unknown
    ready = topics.confirm("research", 42, 42, 7)
    assert ready.state == TopicState.READY and topics.confirm("research", 42, 42, 7) == ready
    with pytest.raises(ValueError, match="多个"):
        topics.confirm("research", 42, 42, 8)
    with pytest.raises(PermissionError):
        topics.confirm("research", 43, 42, 7)
    with pytest.raises(PermissionError):
        topics.prepare("research", 43, 42, "title")
    with pytest.raises(KeyError):
        topics.confirm("missing", 42, 42, 7)
    with pytest.raises(ValueError):
        topics.record_failure("research", unknown=True, retryable=False, error="late")
    topics.prepare("retry", 42, 42, "retry")
    topics.claim("retry")
    topics.record_failure("retry", unknown=False, retryable=True, error="limited")
    assert topics.claim("retry")
    topics.record_failure("retry", unknown=False, retryable=False, error="permission")
    assert not topics.claim("retry")


def test_receipts_do_not_replay_unknown_sends(tmp_path: Path) -> None:
    """未知发送不转回待发送，明确限流可以重试。参数：目录。返回：无。异常：断言失败。"""
    database = TelegramDatabase(tmp_path / "channel.db")
    deliveries = SQLiteTelegramDeliveries(database, 1)
    deliveries.prepare("summary", 42, 7, "hash")
    assert deliveries.claim("summary")
    assert deliveries.recover_interrupted() == 1
    assert deliveries.prepare("summary", 42, 7, "hash").state == DeliveryState.UNKNOWN
    assert not deliveries.claim("summary")
    with pytest.raises(ValueError, match="变化"):
        deliveries.prepare("summary", 42, 7, "changed")
    deliveries.prepare("file", 42, 7, "hash")
    assert deliveries.claim("file")
    deliveries.fail("file", unknown=False, retryable=True, error="limited")
    assert deliveries.claim("file")
    acknowledged = deliveries.acknowledge("file", 9)
    assert acknowledged.message_id == 9 and deliveries.acknowledge("file", 9) == acknowledged
    with pytest.raises(ValueError):
        deliveries.acknowledge("file", 10)
    with pytest.raises(ValueError):
        deliveries.fail("file", unknown=True, retryable=False, error="late")
