"""问题驱动研究、输入队列及不可变报告的共享强类型契约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from alpha.contracts.agent_execution import AcceptedExecutionSpec
from alpha.contracts.execution_options import ExecutionOptions
from alpha.contracts.research_financials import FinancialRequirement


class ResearchConflictError(RuntimeError):
    """研究状态、幂等输入或不可变成果发生冲突。"""


class ResearchState(str, Enum):
    """研究业务生命周期，独立于 Host 执行状态。"""

    ACTIVE = "active"
    ARCHIVED = "archived"


class ResearchDepth(str, Enum):
    """invest 方法的研究深度路由。"""

    QUICK = "quick"
    STANDARD = "standard"
    FULL = "full"
    MONITORING = "monitoring"


class ResearchExecutionMode(str, Enum):
    """本地模型执行或外部 coding agent 驱动；两者均受 Host 治理。"""

    INTERNAL = "internal"
    EXTERNAL = "external"


class ResearchPublicationPolicy(str, Enum):
    """由用户入口固定的发布策略，不接受报告正文授权。"""

    MANUAL = "manual"
    ON_COMPLETE = "on_complete"


class ResearchTurnState(str, Enum):
    """业务输入的派发状态，SETTLED 不表达 Host 成败。"""

    QUEUED = "queued"
    DISPATCHING = "dispatching"
    SUBMITTED = "submitted"
    SETTLED = "settled"
    CANCELLED = "cancelled"


class EvidenceClassification(str, Enum):
    """证据与数字在 invest 契约中的归属。"""

    REPORTED_FACT = "reported_fact"
    MANAGEMENT_GUIDANCE = "management_guidance"
    CONSENSUS = "consensus"
    ANALYST_ASSUMPTION = "analyst_assumption"


@dataclass(frozen=True)
class CreateResearchRequest:
    """创建研究的显式业务输入，request_key 由渠道稳定生成。"""

    owner_id: str
    request_key: str
    question: str
    subjects: tuple[str, ...] = ()
    title: str = ""
    as_of: datetime | None = None
    depth: ResearchDepth = ResearchDepth.STANDARD


@dataclass(frozen=True)
class ResearchRecord:
    """研究元数据；as_of 为空表示每轮接受时取当前时间。"""

    research_id: str
    owner_id: str
    title: str
    question: str
    subjects: tuple[str, ...]
    session_id: str
    state: ResearchState
    version: int
    as_of: datetime | None
    depth: ResearchDepth
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SubmitResearchTurnRequest:
    """提交研究输入；相同键重试复用首次接受的截止时间。"""

    research_id: str
    owner_id: str
    request_key: str
    user_text: str
    as_of: datetime | None = None
    attachment_refs: tuple[str, ...] = ()
    execution_options: ExecutionOptions | None = None
    financial_requirements: tuple[FinancialRequirement, ...] = ()
    execution_mode: ResearchExecutionMode = ResearchExecutionMode.INTERNAL
    publication_policy: ResearchPublicationPolicy = ResearchPublicationPolicy.MANUAL
    publication_target_id: str | None = None


@dataclass(frozen=True)
class ResumeResearchTurnRequest:
    """显式恢复原输入；稳定键区别于原始输入键。"""

    turn_id: str
    owner_id: str
    request_key: str


@dataclass(frozen=True)
class ResearchTurnPreparation:
    """首次业务接受时固定的方法身份和模型/工具运行规格。"""

    method_hash: str
    accepted_spec: AcceptedExecutionSpec


@dataclass(frozen=True)
class ResearchTurn:
    """可持久派发的研究输入，不复制 Host Run 状态机。"""

    turn_id: str
    research_id: str
    request_key: str
    sequence: int
    user_text: str
    attachment_refs: tuple[str, ...]
    input_hash: str
    as_of: datetime
    state: ResearchTurnState
    run_id: str | None
    created_at: datetime
    preparation: ResearchTurnPreparation
    historical: bool
    host_epoch: int | None = None
    execution_options: ExecutionOptions | None = None
    resume_request_key: str | None = None
    financial_requirements: tuple[FinancialRequirement, ...] = ()
    execution_mode: ResearchExecutionMode = ResearchExecutionMode.INTERNAL
    publication_policy: ResearchPublicationPolicy = ResearchPublicationPolicy.MANUAL
    publication_target_id: str | None = None


@dataclass(frozen=True)
class ResearchStopFence:
    """一次持久停止边界；完成前的新输入保留但暂停派发。"""

    stop_id: str
    research_id: str
    request_key: str
    through_sequence: int
    completed_epoch: int | None


@dataclass(frozen=True)
class ResearchEvidence:
    """原始证据定位和时间归属，未知时间保留明确原因。"""

    evidence_id: str
    source_ref: str
    document_type: str
    excerpt: str
    classification: EvidenceClassification
    accessed_at: datetime
    locator: str | None = None
    published_at: datetime | None = None
    available_at: datetime | None = None
    time_missing_reason: str | None = None


@dataclass(frozen=True)
class CommitResearchRevisionRequest:
    """由已受理研究输入提交正式报告快照。"""

    research_id: str
    owner_id: str
    source_turn_id: str
    source_run_id: str
    report_markdown: str
    skill_hash: str
    evidence: tuple[ResearchEvidence, ...] = ()
    data_contract_json: str | None = None


@dataclass(frozen=True)
class ResearchRevision:
    """不可变研究版本，正文由研究产物仓储保存。"""

    revision_id: str
    research_id: str
    number: int
    parent_revision_id: str | None
    source_turn_id: str
    source_run_id: str
    as_of: datetime
    content_hash: str
    skill_hash: str
    created_at: datetime
