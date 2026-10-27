"""投资约定、判断与复盘的显式JSON契约，不推断缺失证据或日期。"""

from datetime import datetime
from typing import cast

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research_judgments import InvestmentMandate, InvestmentJudgment, JudgmentReview, ReturnSource, ReviewOutcome, JudgmentChange, JudgmentError
from alpha.research.evidence import decode_research_evidence, encode_research_evidence


def require_text(value: JsonValue, field: str) -> str:
    """读取必填文本。参数：JSON值、字段名。返回：文本。异常：缺失或空白。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field}必须为非空字符串')
    return value


def text_list(value: JsonValue, field: str, *, required: bool = False) -> tuple[str, ...]:
    """读取文本数组。参数：JSON值、字段、是否至少一项。返回：去重元组。异常：格式或重复非法。"""
    if not isinstance(value, list):
        raise ValueError(f'{field}必须为数组')
    result = tuple(require_text(item, field) for item in value)
    if len(set(result)) != len(result) or required and not result:
        raise ValueError(f'{field}不能重复，且必需数组不能为空')
    return result


def timestamp(value: JsonValue, field: str) -> datetime:
    """读取带时区时间。参数：JSON值、字段。返回：时间。异常：日期或时区无效。"""
    result = datetime.fromisoformat(require_text(value, field).replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f'{field}必须包含时区')
    return result


def decode_mandate(data: dict[str, JsonValue]) -> InvestmentMandate:
    """解析研究约定。参数：显式字段。返回：类型化约定。异常：字段非法。"""
    return InvestmentMandate(tuple(ReturnSource(item) for item in text_list(data.get('return_sources'), 'return_sources', required=True)),
        require_text(data.get('horizon'), 'horizon'), text_list(data.get('invalidation_conditions'), 'invalidation_conditions', required=True),
        require_text(data.get('capital_constraints'), 'capital_constraints'),
        require_text(data['change_reason'], 'change_reason') if data.get('change_reason') is not None else None)


def encode_mandate(value: InvestmentMandate) -> dict[str, JsonValue]:
    """编码约定。参数：约定。返回：JSON。异常：无。"""
    return {'return_sources': [item.value for item in value.return_sources], 'horizon': value.horizon,
        'invalidation_conditions': list(value.invalidation_conditions), 'capital_constraints': value.capital_constraints, 'change_reason': value.change_reason}


def decode_judgment(data: dict[str, JsonValue]) -> InvestmentJudgment:
    """解析判断及全部证据。参数：显式字段。返回：类型化判断。异常：字段、证据或时间非法。"""
    return InvestmentJudgment(require_text(data.get('subject'), 'subject'), require_text(data.get('statement'), 'statement'),
        require_text(data.get('mechanism'), 'mechanism'), text_list(data.get('assumptions'), 'assumptions', required=True),
        text_list(data.get('counterarguments'), 'counterarguments', required=True), require_text(data.get('expected_observation'), 'expected_observation'),
        timestamp(data.get('check_at'), 'check_at'), decode_research_evidence(data.get('evidence', [])),
        text_list(data.get('supporting_evidence_ids', []), 'supporting_evidence_ids'), text_list(data.get('opposing_evidence_ids', []), 'opposing_evidence_ids'),
        require_text(data['previous_judgment_id'], 'previous_judgment_id') if data.get('previous_judgment_id') is not None else None)


def encode_judgment(value: InvestmentJudgment, as_of: datetime) -> dict[str, JsonValue]:
    """编码判断并核验引用。参数：判断、截止。返回：JSON。异常：证据ID重复、未知或晚于截止。"""
    evidence = encode_research_evidence(value.evidence, as_of)
    identities = {item.evidence_id for item in value.evidence}
    references = set(value.supporting_evidence_ids + value.opposing_evidence_ids)
    if len(identities) != len(evidence) or not references <= identities:
        raise ValueError('判断证据ID重复或引用了未提供的证据')
    if set(value.supporting_evidence_ids) & set(value.opposing_evidence_ids):
        raise ValueError('同一证据不能同时标作支持与反对')
    return {'subject': value.subject, 'statement': value.statement, 'mechanism': value.mechanism, 'assumptions': list(value.assumptions),
        'counterarguments': list(value.counterarguments), 'expected_observation': value.expected_observation, 'check_at': value.check_at.isoformat(),
        'evidence': evidence, 'supporting_evidence_ids': list(value.supporting_evidence_ids), 'opposing_evidence_ids': list(value.opposing_evidence_ids),
        'previous_judgment_id': value.previous_judgment_id}


def decode_review(data: dict[str, JsonValue]) -> JudgmentReview:
    """解析原判断复盘。参数：显式字段。返回：类型化复盘。异常：状态、归因或日期非法。"""
    return JudgmentReview(require_text(data.get('judgment_id'), 'judgment_id'), require_text(data.get('observed_outcome'), 'observed_outcome'),
        ReviewOutcome(require_text(data.get('outcome'), 'outcome')), JudgmentChange(require_text(data.get('change'), 'change')),
        require_text(data.get('reason'), 'reason'), tuple(JudgmentError(item) for item in text_list(data.get('error_categories', []), 'error_categories')),
        decode_research_evidence(data.get('evidence', [])), timestamp(data['next_check_at'], 'next_check_at') if data.get('next_check_at') is not None else None)


def encode_review(value: JudgmentReview, as_of: datetime) -> dict[str, JsonValue]:
    """编码复盘并验证证据与延期。参数：复盘、截止。返回：JSON。异常：缺少观察证据或延期未定义。"""
    if value.outcome in (ReviewOutcome.SUPPORTED, ReviewOutcome.CONTRADICTED) and not value.evidence:
        raise ValueError('确定性复盘必须提供实际经营结果的证据')
    if value.outcome in (ReviewOutcome.INCONCLUSIVE, ReviewOutcome.DELAYED) and (value.next_check_at is None or value.next_check_at <= as_of):
        raise ValueError('信息不足或延期必须提供晚于本轮截止的新检验时间，并在reason说明原因')
    return {'judgment_id': value.judgment_id, 'observed_outcome': value.observed_outcome, 'outcome': value.outcome.value,
        'change': value.change.value, 'reason': value.reason, 'error_categories': [item.value for item in value.error_categories],
        'evidence': encode_research_evidence(value.evidence, as_of), 'next_check_at': value.next_check_at.isoformat() if value.next_check_at else None}


def require_map(value: JsonValue, field: str) -> dict[str, JsonValue]:
    """读取JSON对象。参数：值、字段。返回：映射。异常：类型非法。"""
    if not isinstance(value, dict):
        raise ValueError(f'{field}必须为对象')
    return cast(dict[str, JsonValue], value)
