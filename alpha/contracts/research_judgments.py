"""投资判断日志的窄持久端口，复用不可变工作笔记而不管理执行状态。"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from alpha.contracts.research import ResearchEvidence
from alpha.contracts.research_working import ResearchWorkScope, ResearchWorkingRecord


class ResearchJudgmentLog(Protocol):
    """研究内可恢复、带原始来源的判断事件日志。"""

    def append_note(self, scope: ResearchWorkScope, tool_call_id: str, *, title: str, content: str) -> ResearchWorkingRecord:
        """追加不可变事件。参数：作用域、调用、类别标题、序列化内容。返回：记录。异常：冲突、迟到或越权。"""
        ...

    def list_named_notes(self, scope: ResearchWorkScope, title: str) -> list[ResearchWorkingRecord]:
        """读取同主题且不晚于截止的指定笔记。参数：作用域、标题。返回：时间升序记录。异常：越权或损坏。"""
        ...


class ReturnSource(str, Enum):
    """可并存但需分别检验的收益来源。"""

    BUSINESS_VALUE_GROWTH = 'business_value_growth'
    MISPRICING_CONVERGENCE = 'mispricing_convergence'
    RISK_COMPENSATION = 'risk_compensation'
    MARKET_BEHAVIOR = 'market_behavior'


class ReviewOutcome(str, Enum):
    """经营证据对原预测的检验结果，不由股价代替。"""

    SUPPORTED = 'supported'
    CONTRADICTED = 'contradicted'
    INCONCLUSIVE = 'inconclusive'
    DELAYED = 'delayed'


class JudgmentChange(str, Enum):
    """新证据对原投资判断的影响。"""

    UNCHANGED = 'unchanged'
    CONFIDENCE_UPDATE = 'confidence_update'
    VALUATION_ONLY = 'valuation_only'
    THESIS_BREACH = 'thesis_breach'
    NEW_CASE = 'new_case'
    UNRESOLVED = 'unresolved'


class JudgmentError(str, Enum):
    """允许多项并存的复盘归因，信息不足可不定性。"""

    DATA_ERROR = 'data_error'
    MECHANISM_ERROR = 'mechanism_error'
    CAPITAL_UNDERESTIMATE = 'capital_underestimate'
    TIMING_ERROR = 'timing_error'
    VALUATION_ERROR = 'valuation_error'
    UNRESOLVED = 'unresolved'


@dataclass(frozen=True)
class InvestmentMandate:
    """本研究的收益来源、期限和失效条件，修改另存一条约定。"""

    return_sources: tuple[ReturnSource, ...]
    horizon: str
    invalidation_conditions: tuple[str, ...]
    capital_constraints: str
    change_reason: str | None = None


@dataclass(frozen=True)
class InvestmentJudgment:
    """可检验的经营判断及其证据链，原预测写入后不修改。"""

    subject: str
    statement: str
    mechanism: str
    assumptions: tuple[str, ...]
    counterarguments: tuple[str, ...]
    expected_observation: str
    check_at: datetime
    evidence: tuple[ResearchEvidence, ...]
    supporting_evidence_ids: tuple[str, ...]
    opposing_evidence_ids: tuple[str, ...] = ()
    previous_judgment_id: str | None = None


@dataclass(frozen=True)
class JudgmentReview:
    """实际结果与原判断的不可变对照，延期也须说明原因和新检验时间。"""

    judgment_id: str
    observed_outcome: str
    outcome: ReviewOutcome
    change: JudgmentChange
    reason: str
    error_categories: tuple[JudgmentError, ...]
    evidence: tuple[ResearchEvidence, ...]
    next_check_at: datetime | None = None
