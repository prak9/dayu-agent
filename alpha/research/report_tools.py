"""组装单公司、比较与增量报告，显式绑定判断和聊天摘要。"""

from dataclasses import dataclass
from typing import ClassVar

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.protocols import ToolExecutionContext
from alpha.contracts.research_reports import ResearchReportKind
from alpha.contracts.toolset_registrar import ToolRegistryProtocol
from alpha.research.evidence import decode_research_evidence
from alpha.research.evidence_schema import EVIDENCE_SCHEMA
from alpha.research.judgment_encoding import require_map
from alpha.research.report_encoding import decode_summary, decode_case, decode_comparison
from alpha.research.report_composer import ResearchReportComposer
from alpha.research.tools import _extra, _resolve_call, _schema

_TEXT: dict[str, JsonValue] = {'type': 'string', 'minLength': 1}
_TEXTS: dict[str, JsonValue] = {'type': 'array', 'items': _TEXT}
SUMMARY_SCHEMA: dict[str, JsonValue] = {'type': 'object', 'additionalProperties': False, 'properties': {
    'conclusion': _TEXT, 'critical_assumption': _TEXT, 'main_disagreement': _TEXT,
    'changes': _TEXTS, 'open_questions': _TEXTS, 'human_decisions': _TEXTS},
    'required': ['conclusion', 'critical_assumption', 'main_disagreement', 'changes', 'open_questions', 'human_decisions']}
_CASE_SCHEMA: dict[str, JsonValue] = {'type': 'object', 'additionalProperties': False, 'properties': {
    'subject': _TEXT, 'title': _TEXT, 'analysis_markdown': _TEXT, 'judgment_ids': {**_TEXTS, 'minItems': 1}},
    'required': ['subject', 'title', 'analysis_markdown', 'judgment_ids']}
_COMPARISON_SCHEMA: dict[str, JsonValue] = {'type': 'object', 'additionalProperties': False, 'properties': {
    'priority': _TEXT, 'subject': _TEXT, 'quality': _TEXT, 'quality_basis': _TEXT, 'quote': _TEXT, 'currency': _TEXT,
    'quote_as_of': {'type': 'string', 'format': 'date'}, 'base_annual_return': {'type': ['number', 'null'], 'minimum': -1},
    'stress_total_return': {'type': ['number', 'null'], 'minimum': -1}, 'buy_reference': {'type': ['string', 'null']}, 'ranking_condition': _TEXT},
    'required': ['priority', 'subject', 'quality', 'quality_basis', 'quote', 'currency', 'quote_as_of', 'base_annual_return', 'stress_total_return', 'buy_reference', 'ranking_condition']}


@dataclass(frozen=True)
class _ComposeReport:
    """从经过显式校验的内容构造完整报告，不执行发布。"""

    composer: ResearchReportComposer
    __tool_tags__: ClassVar[set[str]] = {'research'}
    __tool_extra__ = _extra('组装研究报告与聊天摘要')

    def __call__(self, title: str, report_kind: str, summary: dict[str, JsonValue], companies: list[JsonValue],
                 comparison: list[JsonValue] | None = None, ranking_rationale: str | None = None, context_markdown: str = '',
                 evidence: list[JsonValue] | None = None, data_contract: dict[str, JsonValue] | None = None,
                 _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """组装并保存候选。参数：标题、类型、摘要、公司、比较、排序理由、范围正文、证据、数字契约及上下文。返回：候选身份和摘要。异常：内容或引用非法。"""
        call = _resolve_call(self.composer.candidates.working, _context)
        return self.composer.compose(call.scope, call.call_id, title=title, kind=ResearchReportKind(report_kind), summary=decode_summary(summary),
            companies=tuple(decode_case(require_map(value, 'company')) for value in companies),
            comparison=tuple(decode_comparison(require_map(value, 'comparison')) for value in comparison or []),
            ranking_rationale=ranking_rationale, context_markdown=context_markdown, evidence=decode_research_evidence(evidence or []), data_contract=data_contract)


def register_report_tools(registry: ToolRegistryProtocol, composer: ResearchReportComposer) -> int:
    """注册完整报告组装入口。参数：注册表、报告组装器。返回：工具数。异常：注册失败。"""
    registry.register('research_compose_report', _ComposeReport(composer), _schema('research_compose_report',
        '报告主入口：单公司按其经营逻辑写正文，比较报告先给条件性总表再解释公司差异；每家公司必须关联已保存的判断。自动附原预测及复盘，保存独立聊天摘要和完整候选，随后校验提交。摘要不接受模型自填正式或Notion状态。', {
        'type': 'object', 'additionalProperties': False, 'properties': {
            'title': _TEXT, 'report_kind': {'type': 'string', 'enum': ['single_company', 'comparison', 'update', 'research_note']},
            'summary': SUMMARY_SCHEMA, 'companies': {'type': 'array', 'items': _CASE_SCHEMA},
            'comparison': {'type': 'array', 'items': _COMPARISON_SCHEMA}, 'ranking_rationale': {'type': ['string', 'null']},
            'context_markdown': {'type': 'string'}, 'evidence': {'type': 'array', 'items': EVIDENCE_SCHEMA},
            'data_contract': {'type': ['object', 'null'], 'additionalProperties': True}},
        'required': ['title', 'report_kind', 'summary', 'companies']}))
    return 1
