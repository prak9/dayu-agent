"""研究与渠道绑定服务，外部协议 ID 仅通过共享地址契约进入。"""

from dataclasses import dataclass

from alpha.contracts.research_channels import BindResearchChannelRequest, ResearchChannelBinding
from alpha.research.storage.protocols import ResearchBindings
from alpha.services.research_service import ResearchService


@dataclass(frozen=True)
class ResearchChannelService:
    """绑定前校验研究归属，不推测最近标的或最近会话。"""

    research: ResearchService
    _bindings: ResearchBindings

    def bind(self, request: BindResearchChannelRequest) -> ResearchChannelBinding:
        """绑定显式话题。参数：共享地址请求。返回：持久绑定。异常：所有权或唯一性冲突。"""
        self.research.overview(request.research_id, request.owner_id)
        return self._bindings.bind(request)

    def resolve(self, *, owner_id: str, channel: str, instance_id: str, conversation_id: str, topic_id: str) -> ResearchChannelBinding | None:
        """解析外部地址。参数：操作者和完整地址。返回：绑定或空。异常：越权。"""
        return self._bindings.resolve(owner_id=owner_id, channel=channel, instance_id=instance_id, conversation_id=conversation_id, topic_id=topic_id)

    def for_research(self, research_id: str, owner_id: str, *, channel: str, instance_id: str) -> ResearchChannelBinding | None:
        """查研究的既有渠道地址。参数：研究、用户、渠道实例。返回：绑定或空。异常：越权。"""
        self.research.overview(research_id, owner_id)
        return self._bindings.for_research(research_id, owner_id, channel=channel, instance_id=instance_id)
