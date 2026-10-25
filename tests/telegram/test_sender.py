"""发送幂等、未知结果、限流与首发卡片冻结测试。"""

from pathlib import Path

import httpx
import pytest

from alpha.telegram.client import TelegramApiError, TelegramClient
from alpha.telegram.database import TelegramDatabase
from alpha.telegram.deliveries import SQLiteTelegramDeliveries
from alpha.telegram.sender import TelegramDeliveryUnknownError, TelegramSender
from tests.telegram.fakes import TelegramServer


@pytest.mark.asyncio
async def test_sender_freezes_first_card_and_retries_only_known_rejection(tmp_path: Path) -> None:
    """限流后保持首次卡片，响应丢失后不重复发消息。参数：目录。返回：无。异常：断言失败。"""
    server = TelegramServer(limited_message=True)
    client = TelegramClient("123:secret", transport=httpx.MockTransport(server))
    receipts = SQLiteTelegramDeliveries(TelegramDatabase(tmp_path / "channel.db"), 123)
    sender = TelegramSender(client, receipts)
    with pytest.raises(TelegramApiError):
        await sender.text("first", 42, 7, "首次状态", keyboard=[[{"text": "原按钮", "callback_data": "a"}]])
    message_id = await sender.text("first", 42, 7, "后来状态")
    assert server.messages[-1]["text"] == "首次状态"
    assert await sender.text("first", 42, 7, "再晚状态") == message_id
    assert len(server.messages) == 1
    server.unknown_message = True
    with pytest.raises(TelegramApiError):
        await sender.text("unknown", 42, 7, "远端已发送")
    with pytest.raises(TelegramDeliveryUnknownError):
        await sender.text("unknown", 42, 7, "重试")
    assert len(server.messages) == 2
    with pytest.raises(ValueError):
        await sender.text("first", 43, 7, "不同地址")
    await client.aclose()


@pytest.mark.asyncio
async def test_damaged_card_snapshot_is_not_sent(tmp_path: Path) -> None:
    """待发送卡片正文被改写时校验失败。参数：目录。返回：无。异常：断言失败。"""
    server = TelegramServer(limited_message=True)
    client = TelegramClient("123:secret", transport=httpx.MockTransport(server))
    database = TelegramDatabase(tmp_path / "channel.db")
    sender = TelegramSender(client, SQLiteTelegramDeliveries(database, 123))
    with pytest.raises(TelegramApiError):
        await sender.text("card", 42, None, "原始正文")
    with database.connection(write=True) as conn:
        conn.execute("UPDATE outbound_receipts SET text_content='changed'")
    with pytest.raises(ValueError, match="完整性"):
        await sender.text("card", 42, None, "ignored")
    assert not server.messages
    await client.aclose()
