"""研究工作记录、正式提交前报告内容及受理作用域的共享契约。"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from alpha.contracts.research import ResearchEvidence


class ResearchWorkingKind(str, Enum):
    """工作记录类别，不表达 Host Run 状态。"""

    NOTE = "note"
    CALCULATION = "calculation"
    REPORT = "report"


@dataclass(frozen=True)
class ResearchWorkScope:
    """由受理记录解析的作用域，不由模型传入研究身份。"""

    research_id: str
    turn_id: str
    run_id: str
    as_of: datetime
    method_hash: str
    historical: bool
    owner_id: str


@dataclass(frozen=True)
class ResearchWorkingRecord:
    """按接受顺序保存的不可变工作记录。"""

    record_id: str
    source_run_id: str
    tool_call_id: str
    sequence: int
    kind: ResearchWorkingKind
    body_json: str
    content_hash: str
    created_at: datetime


@dataclass(frozen=True)
class ResearchReportContent:
    """报告正文与证据；研究身份、截止日和方法由作用域提供。"""

    report_markdown: str
    evidence: tuple[ResearchEvidence, ...] = ()
    data_contract_json: str | None = None
