"""指定版本发布状态的中文卡片和原研究话题通知。"""

from dataclasses import dataclass

from alpha.contracts.publication import PublicationState, ResearchPublication
from alpha.services.research_service import ResearchService
from alpha.telegram.research_topics import TelegramResearchTopics
from alpha.telegram.sender import TelegramSender
from alpha.telegram.actions import ResearchAction, SQLiteTelegramActions
from alpha.contracts.agent_types import JsonValue

_STATE_LABELS: dict[PublicationState, str] = {
    PublicationState.PENDING: "待推送", PublicationState.PUBLISHING: "正在推送", PublicationState.PUBLISHED: "已推送到 Invest",
    PublicationState.FAILED_RETRYABLE: "推送暂时失败，将重试", PublicationState.FAILED_TERMINAL: "推送失败",
    PublicationState.RECONCILING: "正在核对结果，确认前不重复创建",
}


def publication_status_text(publication: ResearchPublication) -> str:
    """投影发布状态。参数：已授权记录。返回：中文文本。异常：无。"""
    return (f"alpha · {_STATE_LABELS[publication.state]}\n{publication.publication_id}\n版本 {publication.revision_id}"
            + (f"\n{publication.page_url}" if publication.page_url is not None else "")
            + (f"\n{publication.error[:500]}" if publication.error is not None else ""))


@dataclass(frozen=True)
class TelegramPublicationDelivery:
    """发布状态与研究完成状态分别投递，所有者和原研究地址由 Service 校验。"""

    research: ResearchService
    topics: TelegramResearchTopics
    sender: TelegramSender
    actions: SQLiteTelegramActions

    async def notify(self, publication: ResearchPublication, user_id: int) -> bool:
        """向原研究话题发送发布状态。参数：记录、已授权用户。返回：是否有可投递绑定。异常：交付未知或 API 错误。"""
        revision = self.research.revision_details(publication.revision_id, str(user_id))
        binding = self.topics.for_research(revision.research_id, str(user_id))
        if binding is None:
            return False
        key = f"publication-status:{publication.publication_id}:{publication.state.value}" + (f":{publication.run_id}" if publication.state == PublicationState.FAILED_TERMINAL else "")
        keyboard: list[JsonValue] | None = None
        if publication.state == PublicationState.PUBLISHED and publication.page_url is not None:
            keyboard = [[{"text": "打开 Notion", "url": publication.page_url}]]
        elif publication.state == PublicationState.FAILED_TERMINAL:
            token = self.actions.issue(key + ":retry", user_id=user_id, chat_id=int(binding.conversation_id), thread_id=int(binding.topic_id),
                                       action=ResearchAction.PUBLISH, research_id=revision.research_id, revision_id=revision.revision_id)
            keyboard = [[{"text": "重试推送", "callback_data": token.token}]]
        await self.sender.text(key, int(binding.conversation_id), int(binding.topic_id), publication_status_text(publication),
                               keyboard=keyboard)
        return True
