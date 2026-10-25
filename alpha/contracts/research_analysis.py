"""候选稿、财报读取与恢复索引的窄仓储端口。"""

from typing import Protocol

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research_financials import FinancialRequirement
from alpha.contracts.research_working import ResearchWorkScope


class ResearchAnalysisRecords(Protocol):
    """只负责不可变分析记录，不持有模型或外部发布能力。"""

    def save_candidate(self, scope: ResearchWorkScope, call_id: str, body: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """保存原稿。参数：作用域、调用、原稿。返回：ID/hash。异常：冲突或迟到。"""
        ...

    def get_candidate(self, scope: ResearchWorkScope, candidate_id: str) -> dict[str, JsonValue]:
        """读取稿件。参数：作用域、ID。返回：稿件。异常：越界或损坏。"""
        ...

    def save_read(self, scope: ResearchWorkScope, call_id: str, body: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """保存实际读取。参数：作用域、调用、结果。返回：读取凭据。异常：冲突或迟到。"""
        ...

    def requirements(self, scope: ResearchWorkScope) -> tuple[FinancialRequirement, ...]:
        """读取固定要求。参数：作用域。返回：要求。异常：来源冲突。"""
        ...

    def coverage_errors(self, scope: ResearchWorkScope) -> list[JsonValue]:
        """检查财报覆盖。参数：作用域。返回：字段问题。异常：损坏。"""
        ...

    def checkpoints(self, scope: ResearchWorkScope) -> list[JsonValue]:
        """读取恢复索引。参数：作用域。返回：保留来源的索引。异常：越界。"""
        ...

    def financial_reads(self, scope: ResearchWorkScope) -> list[JsonValue]:
        """列出本轮实际读取凭据。参数：作用域。返回：带来源的索引。异常：越界或损坏。"""
        ...

    def save_validation(self, scope: ResearchWorkScope, call_id: str, candidate_id: str, result: dict[str, JsonValue]) -> None:
        """保存本次校验报告。参数：作用域、调用、候选、结果。返回：无。异常：迟到或冲突。"""
        ...
