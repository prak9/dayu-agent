"""双层报告组装、比较条件与判断引用的行为测试。"""
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research_judgments import InvestmentMandate, ReturnSource, JudgmentReview, ReviewOutcome, JudgmentChange, JudgmentError
from alpha.contracts.research_reports import ResearchSummary, CompanyResearchCase, CompanyComparison, ResearchReportKind
from alpha.engine.tool_registry import ToolRegistry
from alpha.contracts.protocols import ToolExecutionContext
from alpha.research.judgments import ResearchJudgments
from alpha.research.judgment_tools import register_judgment_tools
from alpha.research.report_composer import ResearchReportComposer
from alpha.research.report_encoding import decode_summary, encode_summary, decode_comparison, encode_comparison
from alpha.research.report_tools import register_report_tools
from tests.research.test_analysis import _setup
from tests.research.test_judgments import _claim, _evidence

_SUMMARY = ResearchSummary('等待价格', '常态利润', '涨价还是经营改善', ('新增财报',), ('成本尚需核验',), ())


def test_compose_single_company_links_judgment_and_saves_separate_summary(tmp_path: Path) -> None:
    """完整候选包含原判断与出处，摘要记录绑定正文摘要。参数：目录。返回：无。异常：断言失败。"""
    _, candidates, scope = _setup(tmp_path);judgments = ResearchJudgments(candidates.working)
    judgments.save_mandate(scope, 'mandate', InvestmentMandate((ReturnSource.BUSINESS_VALUE_GROWTH,), '五年', ('现金下降',), '未提供'))
    claim = judgments.save_judgment(scope, 'claim', _claim());composer = ResearchReportComposer(candidates, judgments)
    case = CompanyResearchCase('601899', '紫金：分清周期与经营能力', '经营、财务、估值与下行风险分析。', (claim.record_id,))
    result = composer.compose(scope, 'compose', title='紫金股东回报', kind=ResearchReportKind.SINGLE_COMPANY, summary=_SUMMARY,
        companies=(case,), comparison=(), ranking_rationale=None, context_markdown='', evidence=(), data_contract=None)
    body = require_body(result)
    assert '常态每股利润' in str(body['report_markdown']) and 'https://example.com/filing' in str(body['report_markdown'])
    assert '预期收益' in str(body['report_markdown']) and '归档成功' not in str(body['report_markdown'])
    assert result['summary'] == encode_summary(_SUMMARY)
    assert result['presentation_record_id']
    registry = ToolRegistry();assert register_judgment_tools(registry, judgments, candidates.working) == 4
    assert register_report_tools(registry, composer) == 1
    context = ToolExecutionContext(run_id=scope.run_id, tool_call_id='index')
    assert registry.execute('research_judgments', {}, context)['ok'] is True
    assert candidates.validate(scope, str(result['candidate_id']), context)['valid'] is True
    with pytest.raises(ValueError, match='其他证券'):
        composer.compose(scope, 'bad', title='错配', kind=ResearchReportKind.SINGLE_COMPANY, summary=_SUMMARY,
            companies=(replace(case, subject='OTHER'),), comparison=(), ranking_rationale=None, context_markdown='', evidence=(), data_contract=None)


def require_body(result: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """收窄公开候选结果。参数：结果。返回：正文对象。异常：断言失败。"""
    value = result['body'];assert isinstance(value, dict);return value


def test_comparison_allows_ties_but_requires_switch_conditions_and_complete_cases(tmp_path: Path) -> None:
    """并列不伪装精确排序，比较条件与代码必须一致。参数：目录。返回：无。异常：断言失败。"""
    _, candidates, scope = _setup(tmp_path);judgments = ResearchJudgments(candidates.working)
    judgments.save_mandate(scope, 'mandate', InvestmentMandate((ReturnSource.RISK_COMPENSATION,), '五年', ('风险补偿消失',), '未提供'))
    claims = [judgments.save_judgment(scope, 'claim'+t, replace(_claim(), subject=t)) for t in ['A','B']]
    cases = tuple(CompanyResearchCase(t, t+'公司自己的分析结构', '经营及估值依据', (claim.record_id,)) for t, claim in zip(['A','B'], claims))
    rows = tuple(CompanyComparison('并列1', t, 'A−', '实际经营依据', '100', 'USD', '2026-10-23', .10, -.40, None, '若股东现金改善，优先次序上调') for t in ['A','B'])
    composer = ResearchReportComposer(candidates, judgments)
    result = composer.compose(scope, 'comparison', title='比较', kind=ResearchReportKind.COMPARISON, summary=_SUMMARY, companies=cases,
        comparison=rows, ranking_rationale='两者现金把握接近，不强行区分。', context_markdown='', evidence=(), data_contract=None)
    assert str(require_body(result)['report_markdown']).count('并列1') == 2
    with pytest.raises(ValueError, match='至少两家'):
        composer.compose(scope, 'bad', title='比较', kind=ResearchReportKind.COMPARISON, summary=_SUMMARY, companies=cases,
            comparison=rows[:1], ranking_rationale=None, context_markdown='', evidence=(), data_contract=None)
    with pytest.raises(ValueError, match='交付状态'):decode_summary({**encode_summary(_SUMMARY), 'published': True})
    with pytest.raises(ValueError, match='有限情景'):decode_comparison({**encode_comparison(rows[0]), 'base_annual_return': True})
    assert decode_summary(encode_summary(_SUMMARY)) == _SUMMARY


def test_report_retains_original_mandate_and_disproven_forecast(tmp_path: Path) -> None:
    """报告可同时审阅原约定和纠错，不用新期限覆盖旧预测。参数：目录。返回：无。异常：断言失败。"""
    _, candidates, scope = _setup(tmp_path)
    judgments = ResearchJudgments(candidates.working)
    mandate = InvestmentMandate((ReturnSource.BUSINESS_VALUE_GROWTH,), '原五年期限', ('现金下降',), '未提供')
    judgments.save_mandate(scope, 'mandate', mandate)
    claim = judgments.save_judgment(scope, 'claim', _claim())
    judgments.save_mandate(scope, 'changed', replace(mandate, horizon='新一年期限', change_reason='重新审视资金期限'))
    judgments.save_review(scope, 'review', JudgmentReview(claim.record_id, '成本增长抵消产量增长', ReviewOutcome.CONTRADICTED,
        JudgmentChange.THESIS_BREACH, '原成本假设不成立', (JudgmentError.MECHANISM_ERROR,), (_evidence(),)))
    composer = ResearchReportComposer(candidates, judgments)
    case = CompanyResearchCase('601899', '经营判断复盘', '重新审视可付价格。', (claim.record_id,))
    result = composer.compose(scope, 'update', title='复盘', kind=ResearchReportKind.UPDATE, summary=_SUMMARY,
        companies=(case,), comparison=(), ranking_rationale=None, context_markdown='', evidence=(), data_contract=None)
    body = str(require_body(result)['report_markdown'])
    assert '原五年期限' in body and '新一年期限' in body
    assert '受到反证' in body and '原逻辑失效' in body and '机制误判' in body
    with pytest.raises(ValueError, match='证据ID冲突'):
        composer.compose(scope, 'conflicting-evidence', title='冲突', kind=ResearchReportKind.UPDATE, summary=_SUMMARY,
            companies=(case,), comparison=(), ranking_rationale=None, context_markdown='',
            evidence=(replace(_evidence(), excerpt='用同一ID换掉证据'),), data_contract=None)
