"""研究摘要复用 Host reply outbox，文件和远端消息 ID 留在渠道回执。"""

from dataclasses import dataclass

from alpha.contracts.reply_outbox import ReplyOutboxState
from alpha.contracts.research import ResearchRevision
from alpha.contracts.research_execution import ResearchOverview
from alpha.services.contracts import ReplyDeliveryFailureRequest, ReplyDeliverySubmitRequest
from alpha.services.reply_delivery_service import ReplyDeliveryService
from alpha.services.research_service import RESEARCH_SCENE, ResearchService
from alpha.telegram.cards import TelegramCards
from alpha.telegram.client import TelegramApiError
from alpha.telegram.sender import TelegramDeliveryUnknownError, TelegramSender


@dataclass(frozen=True)
class TelegramReportDelivery:
    """正式版本完成与渠道发送分别记录，未知发送不自动重复。"""

    bot_id: int
    research: ResearchService
    replies: ReplyDeliveryService
    cards: TelegramCards
    sender: TelegramSender

    async def summary(self, view: ResearchOverview, revision: ResearchRevision, user_id: int, chat_id: int, thread_id: int) -> None:
        """投递指定版本摘要。参数：研究详情、版本、地址。返回：无。异常：交付未知、限流或不可重试失败。"""
        key = f"telegram:{self.bot_id}:summary:{revision.revision_id}"
        card = self.cards.report(key, user_id, chat_id, thread_id, view, revision)
        delivery = self.replies.submit_reply_for_delivery(ReplyDeliverySubmitRequest(
            key, view.research.session_id, RESEARCH_SCENE, revision.source_run_id, card.text,
            metadata={"delivery_channel": "telegram", "delivery_target": str(chat_id), "delivery_thread_id": str(thread_id)},
        ))
        if delivery.state == ReplyOutboxState.DELIVERED:
            return
        if delivery.state == ReplyOutboxState.FAILED_TERMINAL:
            raise TelegramDeliveryUnknownError(f"摘要交付已停止自动重试；{delivery.delivery_id}")
        # 当前 Bot 的消费者持有实例锁；中断遗留的同一交付可用原 lease 结合渠道回执调和。
        claimed = delivery if delivery.state == ReplyOutboxState.DELIVERY_IN_PROGRESS else self.replies.claim_delivery(delivery.delivery_id)
        if claimed.lease_id is None:
            raise ValueError("reply outbox 未返回发送租约")
        try:
            await self.sender.text(key, chat_id, thread_id, claimed.reply_content, keyboard=card.keyboard)
        except (TelegramApiError, TelegramDeliveryUnknownError) as exc:
            retryable = isinstance(exc, TelegramApiError) and not exc.unknown and exc.retry_after is not None
            self.replies.mark_delivery_failed(ReplyDeliveryFailureRequest(claimed.delivery_id, retryable, str(exc), claimed.lease_id))
            raise
        self.replies.mark_delivery_delivered(claimed.delivery_id, lease_id=claimed.lease_id)

    async def file(self, key: str, revision: ResearchRevision, user_id: int, chat_id: int, thread_id: int | None) -> int:
        """发送用户选定的 Markdown 版本。参数：显式发送键、版本、地址。返回：message ID。异常：未知交付或报告损坏。"""
        content = self.research.read_report(revision.revision_id, str(user_id)).encode("utf-8")
        return await self.sender.document(key, chat_id, thread_id, f"alpha-report-v{revision.number}.md", content)
