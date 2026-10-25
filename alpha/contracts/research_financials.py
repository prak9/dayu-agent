"""研究的固定财报要求与受治理的财务读取端口。"""

from dataclasses import dataclass
from typing import Protocol

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.cancellation import CancellationToken

CORE_STATEMENTS = ("income", "balance_sheet", "cash_flow")


@dataclass(frozen=True)
class FinancialRequirement:
    """每轮固定的公司、文档及报表覆盖要求；空文档集合表示不限定文档。"""

    ticker: str
    document_ids: tuple[str, ...] = ()
    statement_types: tuple[str, ...] = CORE_STATEMENTS
    minimum_periods: int = 1

    def __post_init__(self) -> None:
        """拒绝无法验证的要求。参数：无。返回：无。异常：值非法。"""
        if not self.ticker.strip() or isinstance(self.minimum_periods, bool) or self.minimum_periods < 1 or not self.statement_types:
            raise ValueError("财报要求需要公司、至少一个期间和报表类型")
        if any(kind not in CORE_STATEMENTS for kind in self.statement_types):
            raise ValueError("财报覆盖仅支持三张核心报表")
        if any(not value.strip() for value in self.document_ids):
            raise ValueError("财报文档 ID 不能为空")
        object.__setattr__(self, "ticker", self.ticker.strip().upper())


def encode_financial_requirements(requirements: tuple[FinancialRequirement, ...]) -> list[JsonValue]:
    """编码明确要求。参数：要求元组。返回：JSON 数组。异常：无。"""
    return [{"ticker": item.ticker, "document_ids": list(item.document_ids),
             "statement_types": list(item.statement_types), "minimum_periods": item.minimum_periods} for item in requirements]


def decode_financial_requirements(value: JsonValue) -> tuple[FinancialRequirement, ...]:
    """严格恢复固定要求。参数：JSON。返回：要求元组。异常：结构非法。"""
    if not isinstance(value, list):
        raise ValueError("财报要求必须是数组")
    result: list[FinancialRequirement] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("财报要求必须是对象")
        ticker, documents, statements, periods = item.get("ticker"), item.get("document_ids", []), item.get("statement_types", list(CORE_STATEMENTS)), item.get("minimum_periods", 1)
        if not isinstance(ticker, str) or not isinstance(documents, list) or not isinstance(statements, list):
            raise ValueError("财报要求的公司和范围非法")
        if not isinstance(periods, int) or isinstance(periods, bool):
            raise ValueError("财报要求的期间数量非法")
        if any(not isinstance(part, str) for part in documents + statements):
            raise ValueError("财报范围必须为字符串")
        result.append(FinancialRequirement(ticker, tuple(str(part) for part in documents), tuple(str(part) for part in statements), periods))
    return tuple(result)


class FinancialResearchReader(Protocol):
    """财报处理和读取能力，原件与解析产物的访问由 Fins 仓储完成。"""

    def download(self, ticker: str, form_types: tuple[str, ...], start_date: str | None, end_date: str | None,
                 token: CancellationToken | None) -> dict[str, JsonValue]:
        """下载选定范围的财报。参数：公司、表单、日期范围、取消。返回：下载清单。异常：取消或下载失败。"""
        ...

    def prepare(self, ticker: str, document_id: str, token: CancellationToken | None) -> dict[str, JsonValue]:
        """处理已下载的源文档。参数：公司、文档、取消真源。返回：处理结果。异常：取消或解析失败。"""
        ...

    def read(self, ticker: str, document_id: str, *, statement_type: str | None, table_ref: str | None,
             token: CancellationToken | None) -> dict[str, JsonValue]:
        """读取并固定财报快照。参数：公司、文档、报表或表格、取消。返回：实际结果及哈希。异常：缺失、变化或取消。"""
        ...
