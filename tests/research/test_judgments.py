"""收益约定、证据关联、跨轮复盘和到期检验的实际仓储测试。"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from alpha.contracts.research import CreateResearchRequest, ResearchEvidence, EvidenceClassification, SubmitResearchTurnRequest, ResearchConflictError
from alpha.contracts.research_judgments import InvestmentMandate, InvestmentJudgment, JudgmentReview, ReturnSource, ReviewOutcome, JudgmentChange
from alpha.contracts.research_working import ResearchWorkScope
from alpha.research.judgments import ResearchJudgments
from alpha.research.storage.catalog import SQLiteResearchCatalog
from alpha.research.storage.store import ResearchStore
from alpha.research.storage.turns import SQLiteResearchTurns
from alpha.research.storage.working import SQLiteResearchWorkingRecords
from tests.research.factories import research_turn_preparation

_CUTOFF = datetime(2026, 10, 25, tzinfo=timezone.utc)


def _setup(path: Path, *, key: str = 'create') -> tuple[ResearchStore, ResearchJudgments, ResearchWorkScope]:
    """创建实际受理和日志。参数：路径、创建键。返回：库、判断服务、作用域。异常：存储错误。"""
    store = ResearchStore(path / 'research.db');catalog = SQLiteResearchCatalog(store)
    record = catalog.create(CreateResearchRequest('owner', key, '金铜价格与权益产量', as_of=_CUTOFF))
    turns = SQLiteResearchTurns(store);turn = turns.enqueue(SubmitResearchTurnRequest(record.research_id, 'owner', key, '研究'), research_turn_preparation())
    turns.claim_next(record.research_id, 'owner');turns.mark_submitted(turn.turn_id, key)
    working = SQLiteResearchWorkingRecords(store)
    return store, ResearchJudgments(working), working.scope_for_run(key)


def _evidence() -> ResearchEvidence:
    """给出有截止的实际观察示例。参数：无。返回：证据。异常：无。"""
    return ResearchEvidence('e1', 'https://example.com/filing', 'quarterly report', '产量与价格分别披露', EvidenceClassification.REPORTED_FACT,
        _CUTOFF, 'production table', _CUTOFF-timedelta(days=1), _CUTOFF-timedelta(days=1))


def _claim() -> InvestmentJudgment:
    """构造可检验的经营预测。参数：无。返回：判断。异常：无。"""
    return InvestmentJudgment('601899', '常态每股利润取决于权益产量与成本', '产量增加扣成本和少数股东后流向每股利润', ('常态金铜价格不变',),
        ('涨价可能掩盖经营问题',), '下季权益产量增加且单位成本不恶化', _CUTOFF+timedelta(days=30), (_evidence(),), ('e1',))


def test_judgments_require_mandate_and_valid_evidence_and_are_immutable(tmp_path: Path) -> None:
    """无约定、坏引用及同键改写必须拒绝。参数：目录。返回：无。异常：断言失败。"""
    _, service, scope = _setup(tmp_path)
    with pytest.raises(ValueError, match='约定'):service.save_judgment(scope, 'claim', _claim())
    mandate = InvestmentMandate((ReturnSource.BUSINESS_VALUE_GROWTH,), '五年', ('权益现金持续下降',), '未提供资金约束，不建议仓位')
    service.save_mandate(scope, 'mandate', mandate)
    with pytest.raises(ValueError, match='证据'):service.save_judgment(scope, 'invalid', replace(_claim(), supporting_evidence_ids=('missing',)))
    record = service.save_judgment(scope, 'claim', _claim())
    assert service.save_judgment(scope, 'claim', _claim()) == record
    with pytest.raises(ResearchConflictError):service.save_judgment(scope, 'claim', replace(_claim(), statement='偷偷改变原预测'))
    listed = service.list_judgments(scope)
    assert listed['total'] == 1 and listed['due_count'] == 0


def test_new_run_reviews_preserve_old_prediction_and_report_due_without_future_leak(tmp_path: Path) -> None:
    """新一轮复盘保存原预测，过去截止不能读未来复盘。参数：目录。返回：无。异常：断言失败。"""
    store, service, scope = _setup(tmp_path)
    service.save_mandate(scope, 'mandate', InvestmentMandate((ReturnSource.BUSINESS_VALUE_GROWTH,), '五年', ('利润恶化',), '未提供'))
    original = service.save_judgment(scope, 'claim', _claim())
    turns = SQLiteResearchTurns(store);turns.settle(scope.turn_id, scope.run_id)
    next_turn = turns.enqueue(SubmitResearchTurnRequest(scope.research_id, 'owner', 'next', '复盘', as_of=_CUTOFF+timedelta(days=40)), research_turn_preparation())
    turns.claim_next(scope.research_id, 'owner');turns.mark_submitted(next_turn.turn_id, 'next-run')
    next_scope = SQLiteResearchWorkingRecords(store).scope_for_run('next-run')
    assert service.list_judgments(next_scope, due_only=True)['total'] == 1
    review = JudgmentReview(original.record_id, '矿山尚未恢复，下一季仍需观察', ReviewOutcome.DELAYED, JudgmentChange.UNRESOLVED,
        '供电约束延迟，保留旧期限和预测', (), (), next_scope.as_of+timedelta(days=30))
    service.save_review(next_scope, 'review', review)
    assert service.list_judgments(next_scope, due_only=True)['total'] == 0
    assert service.list_judgments(scope)['total'] == 1
    assert service.records.list_named_notes(scope, 'alpha.investment_judgments')[1].body_json == original.body_json
    with pytest.raises(ValueError, match='检验时间'):service.save_review(next_scope, 'bad-review', replace(review, next_check_at=None))
    with pytest.raises(ValueError, match='证据'):service.save_review(next_scope, 'bad-supported', replace(review, outcome=ReviewOutcome.SUPPORTED, evidence=()))
    _, other, other_scope = _setup(tmp_path, key='other')
    with pytest.raises(KeyError):other.save_review(other_scope, 'other-review', review)
    with pytest.raises(ResearchConflictError):service.list_judgments(replace(next_scope, owner_id='other'))


def test_changed_mandate_cannot_rewrite_original_forecast_or_cancel_review(tmp_path: Path) -> None:
    """修改约定与新预测均不消除旧预测责任。参数：目录。返回：无。异常：断言失败。"""
    store, service, scope = _setup(tmp_path)
    mandate = InvestmentMandate((ReturnSource.BUSINESS_VALUE_GROWTH,), '五年', ('现金下降',), '未提供')
    first = service.save_mandate(scope, 'mandate', mandate)
    original = service.save_judgment(scope, 'claim', _claim())
    with pytest.raises(ValueError, match='change_reason'):
        service.save_mandate(scope, 'changed', replace(mandate, horizon='一个月'))
    service.save_mandate(scope, 'changed', replace(mandate, horizon='一个月', change_reason='另行检验交易行为'))
    assert service.save_mandate(scope, 'mandate', mandate) == first
    assert service.save_judgment(scope, 'claim', _claim()) == original
    turns = SQLiteResearchTurns(store)
    turns.settle(scope.turn_id, scope.run_id)
    turn = turns.enqueue(SubmitResearchTurnRequest(scope.research_id, 'owner', 'review', '复盘', as_of=_CUTOFF+timedelta(days=40)), research_turn_preparation())
    turns.claim_next(scope.research_id, 'owner')
    turns.mark_submitted(turn.turn_id, 'review-run')
    later = SQLiteResearchWorkingRecords(store).scope_for_run('review-run')
    service.save_judgment(later, 'replacement', replace(_claim(), previous_judgment_id=original.record_id, check_at=later.as_of+timedelta(days=30)))
    result = service.list_judgments(later, due_only=True)
    assert result['total'] == 1
    rows = result['judgments'];assert isinstance(rows, list)
    row = rows[0];assert isinstance(row, dict)
    assert row['superseded'] is True
    pinned = row['original_mandate'];assert isinstance(pinned, dict)
    assert pinned['record_id'] == first.record_id
    with pytest.raises(ValueError, match='同一研究对象'):
        service.save_judgment(later, 'wrong-subject', replace(_claim(), subject='OTHER', previous_judgment_id=original.record_id, check_at=later.as_of+timedelta(days=30)))
    with pytest.raises(ValueError, match='晚于'):
        service.save_judgment(later, 'past', _claim())
    with pytest.raises(ValueError, match='分页'):
        service.list_judgments(later, limit=51)
    service.save_judgment(later, 'hypothesis', replace(_claim(), subject='OTHER', check_at=later.as_of+timedelta(days=30), evidence=(), supporting_evidence_ids=()))
    assert service.list_judgments(later, limit=1)['next_offset'] == 1
    with pytest.raises(ValueError, match='同时'):
        service.save_judgment(later, 'both', replace(_claim(), check_at=later.as_of+timedelta(days=30), opposing_evidence_ids=('e1',)))
    with pytest.raises(ValueError, match='时区'):
        service.save_judgment(later, 'naive', replace(_claim(), check_at=datetime(2027, 1, 1)))
