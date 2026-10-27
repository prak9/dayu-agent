"""对内置Agent和coding agent提供同一组判断日志工具。"""

from dataclasses import dataclass
from typing import ClassVar

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.protocols import ToolExecutionContext
from alpha.contracts.toolset_registrar import ToolRegistryProtocol
from alpha.research.evidence_schema import EVIDENCE_SCHEMA
from alpha.research.judgment_encoding import decode_mandate, decode_judgment, decode_review
from alpha.research.judgments import ResearchJudgments
from alpha.research.storage.protocols import ResearchWorkingRecords
from alpha.research.tools import _extra, _resolve_call, _schema

_TEXT_ARRAY: dict[str, JsonValue] = {'type': 'array', 'items': {'type': 'string', 'minLength': 1}, 'uniqueItems': True}
_REQUIRED_ARRAY: dict[str, JsonValue] = {**_TEXT_ARRAY, 'minItems': 1}
_TEXT: dict[str, JsonValue] = {'type': 'string', 'minLength': 1}

MANDATE_SCHEMA: dict[str, JsonValue] = {'type': 'object', 'additionalProperties': False, 'properties': {
    'return_sources': {'type': 'array', 'minItems': 1, 'uniqueItems': True, 'items': {'type': 'string', 'enum': ['business_value_growth', 'mispricing_convergence', 'risk_compensation', 'market_behavior']}},
    'horizon': _TEXT, 'invalidation_conditions': _REQUIRED_ARRAY, 'capital_constraints': _TEXT,
    'change_reason': {'type': ['string', 'null']}},
    'required': ['return_sources', 'horizon', 'invalidation_conditions', 'capital_constraints']}

JUDGMENT_SCHEMA: dict[str, JsonValue] = {'type': 'object', 'additionalProperties': False, 'properties': {
    'subject': _TEXT, 'statement': _TEXT, 'mechanism': _TEXT, 'assumptions': _REQUIRED_ARRAY, 'counterarguments': _REQUIRED_ARRAY,
    'expected_observation': _TEXT, 'check_at': {'type': 'string', 'format': 'date-time'},
    'evidence': {'type': 'array', 'items': EVIDENCE_SCHEMA}, 'supporting_evidence_ids': _TEXT_ARRAY, 'opposing_evidence_ids': _TEXT_ARRAY,
    'previous_judgment_id': {'type': ['string', 'null']}},
    'required': ['subject', 'statement', 'mechanism', 'assumptions', 'counterarguments', 'expected_observation', 'check_at', 'evidence', 'supporting_evidence_ids']}

REVIEW_SCHEMA: dict[str, JsonValue] = {'type': 'object', 'additionalProperties': False, 'properties': {
    'judgment_id': _TEXT, 'observed_outcome': _TEXT, 'outcome': {'type': 'string', 'enum': ['supported', 'contradicted', 'inconclusive', 'delayed']},
    'change': {'type': 'string', 'enum': ['unchanged', 'confidence_update', 'valuation_only', 'thesis_breach', 'new_case', 'unresolved']},
    'reason': _TEXT, 'error_categories': {'type': 'array', 'uniqueItems': True, 'items': {'type': 'string', 'enum': ['data_error', 'mechanism_error', 'capital_underestimate', 'timing_error', 'valuation_error', 'unresolved']}},
    'evidence': {'type': 'array', 'items': EVIDENCE_SCHEMA}, 'next_check_at': {'type': ['string', 'null'], 'format': 'date-time'}},
    'required': ['judgment_id', 'observed_outcome', 'outcome', 'change', 'reason', 'error_categories', 'evidence']}


@dataclass(frozen=True)
class _SaveMandate:
    """保存研究收益约定，身份来自Host。"""

    judgments: ResearchJudgments
    working: ResearchWorkingRecords
    __tool_tags__: ClassVar[set[str]] = {'research'}
    __tool_extra__ = _extra('保存投资研究约定')

    def __call__(self, mandate: dict[str, JsonValue], _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """校验并保存约定。参数：约定、上下文。返回：不可变记录ID。异常：字段、约定变更或作用域非法。"""
        call = _resolve_call(self.working, _context)
        record = self.judgments.save_mandate(call.scope, call.call_id, decode_mandate(mandate))
        return {'record_id': record.record_id, 'content_hash': record.content_hash, 'source_run_id': record.source_run_id}


@dataclass(frozen=True)
class _SaveJudgment:
    """保存经营预测及其证据链。"""

    judgments: ResearchJudgments
    working: ResearchWorkingRecords
    __tool_tags__: ClassVar[set[str]] = {'research'}
    __tool_extra__ = _extra('保存可检验判断')

    def __call__(self, judgment: dict[str, JsonValue], _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """校验并保存判断。参数：判断、上下文。返回：判断ID及hash。异常：证据、时间或原判断引用非法。"""
        call = _resolve_call(self.working, _context)
        record = self.judgments.save_judgment(call.scope, call.call_id, decode_judgment(judgment))
        return {'judgment_id': record.record_id, 'content_hash': record.content_hash, 'source_run_id': record.source_run_id}


@dataclass(frozen=True)
class _ReviewJudgment:
    """用经营结果复盘原预测，保存新事件。"""

    judgments: ResearchJudgments
    working: ResearchWorkingRecords
    __tool_tags__: ClassVar[set[str]] = {'research'}
    __tool_extra__ = _extra('复盘原投资判断')

    def __call__(self, review: dict[str, JsonValue], _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """校验并记录复盘。参数：复盘、上下文。返回：复盘ID与hash。异常：原预测越界或观察不完整。"""
        call = _resolve_call(self.working, _context)
        record = self.judgments.save_review(call.scope, call.call_id, decode_review(review))
        return {'review_id': record.record_id, 'content_hash': record.content_hash, 'source_run_id': record.source_run_id}


@dataclass(frozen=True)
class _ListJudgments:
    """提供新旧对照和按固定截止判断的到期索引。"""

    judgments: ResearchJudgments
    working: ResearchWorkingRecords
    __tool_tags__: ClassVar[set[str]] = {'research'}
    __tool_extra__ = _extra('查看投资判断与到期复盘')

    def __call__(self, due_only: bool = False, offset: int = 0, limit: int = 20,
                 _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """查询判断。参数：仅到期、偏移、数量、上下文。返回：分页对照。异常：作用域或范围非法。"""
        call = _resolve_call(self.working, _context)
        return self.judgments.list_judgments(call.scope, due_only=due_only, offset=offset, limit=limit)


def register_judgment_tools(registry: ToolRegistryProtocol, judgments: ResearchJudgments, working: ResearchWorkingRecords) -> int:
    """装配判断工具。参数：注册表、判断能力、作用域端口。返回：工具数量。异常：schema或注册错误。"""
    registry.register('research_save_mandate', _SaveMandate(judgments, working), _schema('research_save_mandate', '保存收益来源、期限、失效条件与资金约束；用户未提供的资金条件明确写未提供，不能编造仓位。', {
        'type': 'object', 'additionalProperties': False, 'properties': {'mandate': MANDATE_SCHEMA}, 'required': ['mandate']}))
    registry.register('research_save_judgment', _SaveJudgment(judgments, working), _schema('research_save_judgment', '保存可检验经营判断及支持/反对证据。新判断引用previous_judgment_id保留旧预测；没有支持证据的判断标为待验证假设。', {
        'type': 'object', 'additionalProperties': False, 'properties': {'judgment': JUDGMENT_SCHEMA}, 'required': ['judgment']}))
    registry.register('research_review_judgment', _ReviewJudgment(judgments, working), _schema('research_review_judgment', '记录实际经营结果、证据、判断变化和错误归因；延期或信息不足必须解释并给新检验时间，不改写原期限。股价不能单独验证经营判断。', {
        'type': 'object', 'additionalProperties': False, 'properties': {'review': REVIEW_SCHEMA}, 'required': ['review']}))
    registry.register('research_judgments', _ListJudgments(judgments, working), _schema('research_judgments', '查看同研究原判断、最新复盘、全部复盘历史、取代关系与到期项；按本轮固定截止计算，不含后台定时执行。', {
        'type': 'object', 'additionalProperties': False, 'properties': {'due_only': {'type': 'boolean'}, 'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50}}, 'required': []}))
    return 4
