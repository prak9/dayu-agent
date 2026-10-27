"""双层报告内容的显式校验与序列化。"""

import math
from datetime import date
from dataclasses import asdict
from typing import cast

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research_reports import ResearchSummary, CompanyResearchCase, CompanyComparison
from alpha.research.judgment_encoding import require_text, text_list

_SUMMARY_FIELDS = frozenset({'conclusion', 'critical_assumption', 'main_disagreement', 'changes', 'open_questions', 'human_decisions'})


def decode_summary(data: dict[str, JsonValue]) -> ResearchSummary:
    """解析摘要并拒绝伪造交付状态。参数：摘要字段。返回：摘要。异常：缺失、额外字段或类型错误。"""
    if set(data) != _SUMMARY_FIELDS:
        raise ValueError('摘要只接受结论、关键假设、主要分歧、变化、未解决问题和人类决策；不接受模型自填交付状态')
    return ResearchSummary(require_text(data.get('conclusion'), 'conclusion'), require_text(data.get('critical_assumption'), 'critical_assumption'),
        require_text(data.get('main_disagreement'), 'main_disagreement'), text_list(data.get('changes'), 'changes'),
        text_list(data.get('open_questions'), 'open_questions'), text_list(data.get('human_decisions'), 'human_decisions'))


def encode_summary(summary: ResearchSummary) -> dict[str, JsonValue]:
    """编码摘要。参数：摘要。返回：JSON对象。异常：无。"""
    return {'conclusion': summary.conclusion, 'critical_assumption': summary.critical_assumption, 'main_disagreement': summary.main_disagreement,
        'changes': list(summary.changes), 'open_questions': list(summary.open_questions), 'human_decisions': list(summary.human_decisions)}


def decode_case(data: dict[str, JsonValue]) -> CompanyResearchCase:
    """解析公司正文与判断引用。参数：公司字段。返回：公司研究。异常：字段缺失。"""
    return CompanyResearchCase(require_text(data.get('subject'), 'subject'), require_text(data.get('title'), 'title'),
        require_text(data.get('analysis_markdown'), 'analysis_markdown'), text_list(data.get('judgment_ids'), 'judgment_ids', required=True))


def _optional_return(value: JsonValue, field: str) -> float | None:
    """读取情景回报，缺失不填零。参数：数值、字段。返回：回报或空。异常：类型或范围非法。"""
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < -1:
        raise ValueError(f'{field}必须是有限情景回报小数或null，不能作为已校准期望收益')
    return float(value)


def decode_comparison(data: dict[str, JsonValue]) -> CompanyComparison:
    """解析有日期与换序条件的比较行。参数：比较字段。返回：比较行。异常：报价日期或回报非法。"""
    quote_as_of = require_text(data.get('quote_as_of'), 'quote_as_of');date.fromisoformat(quote_as_of)
    return CompanyComparison(require_text(data.get('priority'), 'priority'), require_text(data.get('subject'), 'subject'),
        require_text(data.get('quality'), 'quality'), require_text(data.get('quality_basis'), 'quality_basis'),
        require_text(data.get('quote'), 'quote'), require_text(data.get('currency'), 'currency'), quote_as_of,
        _optional_return(data.get('base_annual_return'), 'base_annual_return'), _optional_return(data.get('stress_total_return'), 'stress_total_return'),
        require_text(data['buy_reference'], 'buy_reference') if data.get('buy_reference') is not None else None,
        require_text(data.get('ranking_condition'), 'ranking_condition'))


def encode_comparison(row: CompanyComparison) -> dict[str, JsonValue]:
    """编码比较行。参数：比较行。返回：JSON。异常：无。"""
    return cast(dict[str, JsonValue], asdict(row))
