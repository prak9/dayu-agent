"""从摘要、公司正文及不可变判断组装报告，保留独立的聊天呈现记录。"""

import hashlib
from dataclasses import dataclass
from datetime import datetime

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research import ResearchEvidence
from alpha.contracts.research_reports import ResearchReportKind, ResearchSummary, CompanyResearchCase, CompanyComparison
from alpha.contracts.research_working import ResearchWorkScope
from alpha.research.candidates import ResearchCandidates
from alpha.research.evidence import encode_research_evidence
from alpha.research.judgments import ResearchJudgments, JudgmentEvent
from alpha.research.judgment_encoding import decode_judgment, decode_mandate, decode_review, require_map
from alpha.contracts.research_judgments import ReturnSource, ReviewOutcome, JudgmentChange, JudgmentError
from alpha.research.report_encoding import encode_summary, encode_comparison
from alpha.research.storage.encoding import canonical_json

PRESENTATION_NOTE_TITLE = 'alpha.report_presentation'
_RETURN_LABELS = {ReturnSource.BUSINESS_VALUE_GROWTH: '企业每股价值增长', ReturnSource.MISPRICING_CONVERGENCE: '低估修复',
                  ReturnSource.RISK_COMPENSATION: '承担风险获得补偿', ReturnSource.MARKET_BEHAVIOR: '市场交易行为变化'}
_OUTCOME_LABELS = {ReviewOutcome.SUPPORTED: '获得支持', ReviewOutcome.CONTRADICTED: '受到反证',
                   ReviewOutcome.INCONCLUSIVE: '证据不足', ReviewOutcome.DELAYED: '兑现延迟'}
_CHANGE_LABELS = {JudgmentChange.UNCHANGED: '判断不变', JudgmentChange.CONFIDENCE_UPDATE: '调整信心',
                 JudgmentChange.VALUATION_ONLY: '只改变估值', JudgmentChange.THESIS_BREACH: '原逻辑失效',
                 JudgmentChange.NEW_CASE: '形成新判断', JudgmentChange.UNRESOLVED: '尚不能判断'}
_ERROR_LABELS = {JudgmentError.DATA_ERROR: '数据错误', JudgmentError.MECHANISM_ERROR: '机制误判',
                JudgmentError.CAPITAL_UNDERESTIMATE: '资本需求低估', JudgmentError.TIMING_ERROR: '兑现延迟',
                JudgmentError.VALUATION_ERROR: '估值过高', JudgmentError.UNRESOLVED: '归因未定'}


def report_digest(markdown: str) -> str:
    """计算正文摘要以绑定呈现记录。参数：正文。返回：SHA256。异常：无。"""
    return hashlib.sha256(markdown.encode()).hexdigest()


def summary_markdown(summary: ResearchSummary) -> str:
    """渲染用户需要审视的判断。参数：摘要。返回：Markdown。异常：无。"""
    parts = [f'**{summary.conclusion}**', f'关键假设：{summary.critical_assumption}', f'主要分歧：{summary.main_disagreement}']
    for title, values in [('本轮变化', summary.changes), ('未解决问题', summary.open_questions), ('需要你决定', summary.human_decisions)]:
        if values:
            parts.append(f'**{title}**\n\n' + '\n'.join(f'- {value}' for value in values))
    return '\n\n'.join(parts)


def _cell(text: str) -> str:
    """转义表格单元格。参数：文本。返回：单行Markdown。异常：无。"""
    return text.replace('|', r'\|').replace('\n', '<br>')


def _return(value: float | None) -> str:
    """显示情景回报或缺口。参数：回报。返回：文字。异常：无。"""
    return '未核验' if value is None else f'{value:.1%}'


def comparison_markdown(rows: tuple[CompanyComparison, ...]) -> str:
    """输出允许并列的条件性比较表。参数：比较行。返回：Markdown。异常：无。"""
    lines = ['|优先级|公司|质量与依据|现价／币种／日期|基准情景年化|压力累计|买入参考|可能改变顺序的条件|',
             '|---|---|---|---|---|---|---|---|']
    for row in rows:
        cells = [row.priority, row.subject, f'{row.quality}：{row.quality_basis}', f'{row.quote} {row.currency}／{row.quote_as_of}',
                 _return(row.base_annual_return), _return(row.stress_total_return), row.buy_reference or '待证据，不设价格', row.ranking_condition]
        lines.append('|' + '|'.join(_cell(cell) for cell in cells) + '|')
    return '\n'.join(lines)


def _judgment_markdown(event: JudgmentEvent, reviews: list[JudgmentEvent], mandates: list[JudgmentEvent]) -> str:
    """展开原预测、原约定和纠错。参数：判断、复盘、约定。返回：可审阅文字。异常：事件缺字段。"""
    data = event.data
    judgment = decode_judgment(data)
    lines = [f"**{data['statement']}**", f"判断ID：`{event.record.record_id}`；原信息截止：{event.as_of}。",
             f"传导机制：{data['mechanism']}", '关键假设：' + '；'.join(judgment.assumptions),
             '反证与替代解释：' + '；'.join(judgment.counterarguments),
             f"原定检验：{data['expected_observation']}；时间：{data['check_at']}。"]
    original = next((item for item in mandates if item.record.record_id == event.mandate_id), None)
    if original is not None:
        mandate = decode_mandate(original.data)
        lines.append('判断形成时的约定：' + '、'.join(_RETURN_LABELS[item] for item in mandate.return_sources)
                     + f'；期限：{mandate.horizon}；失效条件：' + '；'.join(mandate.invalidation_conditions) + f'；资金约束：{mandate.capital_constraints}。')
    evidence = data['evidence']
    if isinstance(evidence, list):
        for value in evidence:
            item = require_map(value, 'evidence')
            lines.append(f"证据 `{item['evidence_id']}`（{item['classification']}）：{item['excerpt']} [原始来源]({item['source_ref']})。")
    if not data['supporting_evidence_ids']:
        lines.append('当前没有关联的支持证据，这条判断仍为待验证假设。')
    if data.get('previous_judgment_id'):
        lines.append(f"承接原判断：`{data['previous_judgment_id']}`，原记录保持不变。")
    for review in reviews:
        outcome = decode_review(review.data)
        lines.append(f'复盘（{review.as_of}）：{outcome.observed_outcome}；结果：{_OUTCOME_LABELS[outcome.outcome]}；判断变化：{_CHANGE_LABELS[outcome.change]}；原因：{outcome.reason}。')
        errors = '、'.join(_ERROR_LABELS[item] for item in outcome.error_categories) or '未认定错误'
        lines.append(f'错误归因：{errors}；下次检验：{outcome.next_check_at or "本次观察已记录，无新的约定时间"}。')
    return '\n\n'.join(lines)


def _merge_evidence(provided: tuple[ResearchEvidence, ...], events: list[JudgmentEvent], as_of: datetime) -> list[JsonValue]:
    """合并判断与复盘原始证据，拒绝同ID变义。参数：报告证据、事件和截止。返回：证据JSON。异常：证据冲突或晚于截止。"""
    evidence = encode_research_evidence(provided, as_of)
    for event in events:
        values = event.data.get('evidence', [])
        if isinstance(values, list):
            evidence.extend(require_map(value, 'evidence') for value in values)
    unique: dict[str, dict[str, JsonValue]] = {}
    for raw in evidence:
        item = require_map(raw, 'evidence')
        identity = str(item['evidence_id'])
        if identity in unique and unique[identity] != item:
            raise ValueError(f'报告与判断的证据ID冲突：{identity}')
        unique[identity] = item
    return list(unique.values())


@dataclass(frozen=True)
class ResearchReportComposer:
    """只组装可验证内容，不给研究判断评分，也不声明Notion发布成功。"""

    candidates: ResearchCandidates
    judgments: ResearchJudgments

    def compose(self, scope: ResearchWorkScope, call_id: str, *, title: str, kind: ResearchReportKind, summary: ResearchSummary,
                companies: tuple[CompanyResearchCase, ...], comparison: tuple[CompanyComparison, ...], ranking_rationale: str | None,
                context_markdown: str, evidence: tuple[ResearchEvidence, ...], data_contract: dict[str, JsonValue] | None) -> dict[str, JsonValue]:
        """保存完整候选与绑定摘要。参数：作用域、调用、标题、类型、摘要、公司、比较行、排序理由、范围正文、证据、数字契约。返回：候选及呈现记录。异常：对象不匹配、证据冲突或时间越界。"""
        if kind == ResearchReportKind.SINGLE_COMPANY and len(companies) != 1:
            raise ValueError('单公司报告必须且只能有一个公司案例')
        subjects = {company.subject for company in companies}
        if len(subjects) != len(companies):
            raise ValueError('公司案例的证券代码不能重复')
        if kind == ResearchReportKind.COMPARISON:
            if len(companies) < 2 or {row.subject for row in comparison} != subjects or len(comparison) != len(companies) or not ranking_rationale:
                raise ValueError('比较报告须覆盖至少两家公司、逐行比较及解释排序依据')
        elif comparison:
            raise ValueError('比较表只适用于comparison报告')
        if not companies and not context_markdown.strip():
            raise ValueError('报告须包含公司案例或明确的研究正文')
        if any(datetime.fromisoformat(row.quote_as_of).date() > scope.as_of.date() for row in comparison):
            raise ValueError('比较报价日期不能晚于信息截止日')
        all_events = self.judgments.events(scope)
        mandates = [event for event in all_events if event.kind == 'mandate']
        used: list[JudgmentEvent] = []
        parts = [f'# {title}', f'信息截止：{scope.as_of.isoformat()}。基准年化为指定情景回报，不是已校准概率的预期收益。', summary_markdown(summary)]
        if context_markdown.strip():
            parts.append(context_markdown)
        if comparison:
            parts += ['## 公司比较', comparison_markdown(comparison), ranking_rationale or '']
        for company in companies:
            parts += [f'## {company.title}', company.analysis_markdown, '### 核心判断与后续检验']
            for identity in company.judgment_ids:
                event = self.judgments.get_judgment(scope, identity)
                if event.data['subject'] != company.subject:
                    raise ValueError('公司案例引用了其他证券的判断')
                reviews = [item for item in all_events if item.kind == 'review' and item.data['judgment_id'] == identity]
                used += [event, *reviews]
                parts.append(_judgment_markdown(event, reviews, mandates))
        if mandates:
            mandate = decode_mandate(mandates[-1].data)
            parts += ['## 当前研究约定', '收益来源：' + '、'.join(_RETURN_LABELS[item] for item in mandate.return_sources) + f'；期限：{mandate.horizon}。',
                      '失效条件：' + '；'.join(mandate.invalidation_conditions) + f'；资金约束：{mandate.capital_constraints}。']
        merged = _merge_evidence(evidence, used, scope.as_of)
        if merged:
            parts += ['## 原始来源与证据', '\n'.join(f"- `{require_map(item, 'evidence')['evidence_id']}`：[原始来源]({require_map(item, 'evidence')['source_ref']})" for item in merged)]
        markdown = '\n\n'.join(parts)
        candidate = self.candidates.analysis.save_candidate(scope, call_id, {'report_markdown': markdown, 'evidence': merged, 'data_contract': data_contract})
        presentation: dict[str, JsonValue] = {'candidate_id': candidate['candidate_id'], 'report_digest': report_digest(markdown),
            'report_kind': kind.value, 'summary': encode_summary(summary), 'judgment_ids': [event.record.record_id for event in used if event.kind == 'judgment'],
            'comparison': [encode_comparison(row) for row in comparison]}
        record = self.candidates.working.append_note(scope, call_id + ':presentation', title=PRESENTATION_NOTE_TITLE, content=canonical_json(presentation))
        return {**candidate, 'presentation_record_id': record.record_id, 'summary': encode_summary(summary), 'report_kind': kind.value}
