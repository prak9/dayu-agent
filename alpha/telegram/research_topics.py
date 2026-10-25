"""原生话题与研究绑定流程；调用业务服务，不跨层读取研究数据库。"""

from dataclasses import dataclass

from alpha.contracts.research import CreateResearchRequest, ResearchRecord, SubmitResearchTurnRequest
from alpha.contracts.research_channels import BindResearchChannelRequest, ResearchChannelBinding
from alpha.services.research_channel_service import ResearchChannelService
from alpha.services.research_service import ResearchService
from alpha.telegram.client import TelegramApiError, TelegramClient
from alpha.telegram.topics import SQLiteTelegramTopics, TopicState
from alpha.telegram.types import TelegramIncoming

TELEGRAM_CHANNEL = "telegram"


class TelegramTopicUnknownError(RuntimeError):
    """创建结果未知，需要服务消息调和或显式绑定。"""


@dataclass(frozen=True)
class TelegramResearchTopics:
    """确保研究身份先持久化，话题绑定后才进入渠道执行调度。"""

    bot_id: int
    research: ResearchService
    channels: ResearchChannelService
    log: SQLiteTelegramTopics
    client: TelegramClient

    def resolve(self, incoming: TelegramIncoming) -> ResearchChannelBinding | None:
        """解析当前话题。参数：已授权消息。返回：绑定或空。异常：越权或存储错误。"""
        if incoming.thread_id is None:
            return None
        return self.channels.resolve(owner_id=str(incoming.user_id), channel=TELEGRAM_CHANNEL, instance_id=str(self.bot_id),
                                     conversation_id=str(incoming.chat_id), topic_id=str(incoming.thread_id))

    def for_research(self, research_id: str, owner_id: str) -> ResearchChannelBinding | None:
        """查研究的本 Bot 地址。参数：研究、所有者。返回：绑定或空。异常：越权。"""
        return self.channels.for_research(research_id, owner_id, channel=TELEGRAM_CHANNEL, instance_id=str(self.bot_id))

    def bind(self, research_id: str, user_id: int, chat_id: int, thread_id: int) -> ResearchChannelBinding:
        """显式绑定并调和本地创建日志。参数：研究、地址。返回：绑定。异常：越权或唯一性冲突。"""
        view = self.research.overview(research_id, str(user_id))
        self.log.prepare(research_id, user_id, chat_id, view.research.title)
        binding = self.channels.bind(BindResearchChannelRequest(research_id, str(user_id), TELEGRAM_CHANNEL, str(self.bot_id), str(chat_id), str(thread_id)))
        self.log.confirm(research_id, user_id, chat_id, thread_id)
        return binding

    async def create(self, incoming: TelegramIncoming, question: str, request_key: str) -> ResearchRecord:
        """创建研究与原生话题。参数：消息、问题、稳定创建键。返回：研究。异常：创建未知、明确 API 失败或接受失败。"""
        research = self.research.create(CreateResearchRequest(str(incoming.user_id), request_key, question))
        self.research.submit(SubmitResearchTurnRequest(research.research_id, str(incoming.user_id), f"initial:{research.research_id}", question))
        existing = self.for_research(research.research_id, str(incoming.user_id))
        if existing is not None:
            return research
        provision = self.log.prepare(research.research_id, incoming.user_id, incoming.chat_id, research.title)
        if provision.state == TopicState.READY and provision.thread_id is not None:
            self.bind(research.research_id, incoming.user_id, incoming.chat_id, provision.thread_id)
            return research
        if not self.log.claim(research.research_id):
            raise TelegramTopicUnknownError(f"话题尚未确认。请在目标话题发送 /bind {research.research_id}，不要重复创建。")
        try:
            thread_id = await self.client.create_topic(incoming.chat_id, provision.name)
        except TelegramApiError as exc:
            self.log.record_failure(research.research_id, unknown=exc.unknown, retryable=exc.retry_after is not None, error=str(exc))
            if exc.unknown:
                raise TelegramTopicUnknownError(f"话题创建结果未知，请在已有话题发送 /bind {research.research_id}") from None
            raise
        self.log.confirm(research.research_id, incoming.user_id, incoming.chat_id, thread_id)
        self.bind(research.research_id, incoming.user_id, incoming.chat_id, thread_id)
        return research

    def created_event(self, incoming: TelegramIncoming) -> bool:
        """使用持久随机标记调和服务消息。参数：已验证来源的创建事件。返回：是否调和。异常：多个候选冲突。"""
        if incoming.topic_name is None or incoming.thread_id is None:
            return False
        provision = self.log.find_marker(incoming.chat_id, incoming.chat_id, incoming.topic_name)
        if provision is None:
            return False
        self.bind(provision.research_id, provision.user_id, provision.chat_id, incoming.thread_id)
        return True

    def repair_ready_bindings(self) -> None:
        """修复话题已确认而研究绑定尚未落盘的中断。参数：无。返回：无。异常：绑定冲突。"""
        for provision in self.log.ready():
            if provision.thread_id is not None:
                self.bind(provision.research_id, provision.user_id, provision.chat_id, provision.thread_id)
