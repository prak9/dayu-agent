"""聊天摘要与完整研究报告的内容契约，交付状态由服务端另行提供。"""

from dataclasses import dataclass
from enum import Enum


class ResearchReportKind(str, Enum):
    """报告的组织方式，不代表研究深度或证据可信程度。"""

    SINGLE_COMPANY = 'single_company'
    COMPARISON = 'comparison'
    UPDATE = 'update'
    RESEARCH_NOTE = 'research_note'


@dataclass(frozen=True)
class ResearchSummary:
    """需要读者关注的判断，不接受模型填写正式版本或发布成功状态。"""

    conclusion: str
    critical_assumption: str
    main_disagreement: str
    changes: tuple[str, ...]
    open_questions: tuple[str, ...]
    human_decisions: tuple[str, ...]


@dataclass(frozen=True)
class CompanyResearchCase:
    """公司自己的叙述结构及其不可变核心判断引用。"""

    subject: str
    title: str
    analysis_markdown: str
    judgment_ids: tuple[str, ...]


@dataclass(frozen=True)
class CompanyComparison:
    """比较表的条件性优先次序，允许并列和不可比。"""

    priority: str
    subject: str
    quality: str
    quality_basis: str
    quote: str
    currency: str
    quote_as_of: str
    base_annual_return: float | None
    stress_total_return: float | None
    buy_reference: str | None
    ranking_condition: str
