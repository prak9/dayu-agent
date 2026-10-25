"""研究与外部会话/话题的通用绑定契约，不含 Telegram 实现类型。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BindResearchChannelRequest:
    """由所有者显式指定研究及渠道定位，禁止按话题标题猜绑定。"""

    research_id: str
    owner_id: str
    channel: str
    instance_id: str
    conversation_id: str
    topic_id: str


@dataclass(frozen=True)
class ResearchChannelBinding:
    """一个渠道话题的持久研究身份。"""

    binding_id: str
    research_id: str
    channel: str
    instance_id: str
    conversation_id: str
    topic_id: str
