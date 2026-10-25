"""指定不可变报告版本的显式发布意图与业务状态。"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class PublicationState(str, Enum):
    """发布状态，未知结果必须调和。"""

    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    RECONCILING = "reconciling"


@dataclass(frozen=True)
class PublishResearchRequest:
    """用户对明确版本的发布授权。"""

    revision_id: str
    owner_id: str
    request_key: str


@dataclass(frozen=True)
class ResearchPublication:
    """发布结果投影，Host 运行状态通过 run_id 查询。"""

    publication_id: str
    revision_id: str
    target_id: str
    content_hash: str
    state: PublicationState
    run_id: str | None
    page_id: str | None
    page_url: str | None
    remote_task_id: str | None
    error: str | None


@dataclass(frozen=True)
class PublicationPayload:
    """首次发布接受时固定的正文和所有权，不随后续研究版本变化。"""

    owner_id: str
    research_id: str
    title: str
    markdown: str
    payload_hash: str


@dataclass(frozen=True)
class PublicationClaim:
    """一个执行尝试的业务租约；Run 生命周期仍由 Host 查询。"""

    publication: ResearchPublication
    payload: PublicationPayload
    lease_id: str
    attempt: int
    interrupted: bool
    creation_started: bool
    segments: tuple[str, ...]
    written_segments: int


class ResearchPublicationGateway(Protocol):
    """UI 提交明确版本发布的窄服务接口。"""

    def request_publish(self, request: PublishResearchRequest) -> ResearchPublication:
        """持久接受发布。参数：显式授权。返回：原或新意图。异常：越权、目标或内容冲突。"""
        ...

    def get(self, publication_id: str, owner_id: str) -> ResearchPublication:
        """查询已授权意图。参数：发布、用户。返回：业务状态。异常：越权或缺失。"""
        ...


class ResearchCompletionPublisher(Protocol):
    """研究完成阶段只需要固定目标和持久接受发布，不依赖 HTTP。"""

    @property
    def target_id(self) -> str:
        """读取可信归档根目录。参数：无。返回：目标。异常：无。"""
        ...

    def request_publish(self, request: PublishResearchRequest) -> ResearchPublication:
        """持久接受指定版本。参数：明确授权。返回：发布意图。异常：越权或冲突。"""
        ...
