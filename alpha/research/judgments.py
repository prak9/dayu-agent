"""围绕可检验投资判断组织收益约定、证据关联和不可变复盘。"""

import json
from dataclasses import dataclass
from typing import cast

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research_judgments import InvestmentMandate, InvestmentJudgment, JudgmentReview, ResearchJudgmentLog
from alpha.contracts.research_working import ResearchWorkScope, ResearchWorkingRecord
from alpha.research.judgment_encoding import decode_mandate, decode_judgment, decode_review, encode_mandate, encode_judgment, encode_review, require_map, require_text, timestamp
from alpha.research.storage.encoding import canonical_json

JUDGMENT_NOTE_TITLE = 'alpha.investment_judgments'
_MANDATE = 'mandate'
_JUDGMENT = 'judgment'
_REVIEW = 'review'
_MAX_PAGE = 50


@dataclass(frozen=True)
class JudgmentEvent:
    """已校验事件及其不可变工作记录身份。"""

    record: ResearchWorkingRecord
    kind: str
    as_of: str
    data: dict[str, JsonValue]
    mandate_id: str | None


def _event(record: ResearchWorkingRecord) -> JudgmentEvent:
    """解码并校验日志事件。参数：经仓储完整性校验的记录。返回：事件。异常：正文结构或分类非法。"""
    body = require_map(cast(JsonValue, json.loads(record.body_json)), 'note')
    value = require_map(cast(JsonValue, json.loads(require_text(body.get('content'), 'content'))), 'event')
    kind = require_text(value.get('kind'), 'kind');as_of = timestamp(value.get('as_of'), 'as_of')
    data = require_map(value.get('data'), 'data')
    if kind == _MANDATE:
        data = encode_mandate(decode_mandate(data))
    elif kind == _JUDGMENT:
        data = encode_judgment(decode_judgment(data), as_of)
    elif kind == _REVIEW:
        data = encode_review(decode_review(data), as_of)
    else:
        raise ValueError('未知的投资判断事件')
    mandate_id = require_text(value.get('mandate_id'), 'mandate_id') if kind == _JUDGMENT else None
    return JudgmentEvent(record, kind, as_of.isoformat(), data, mandate_id)


def event_view(event: JudgmentEvent) -> dict[str, JsonValue]:
    """提供原始来源而不重写判断。参数：事件。返回：可序列化视图。异常：无。"""
    return {'record_id': event.record.record_id, 'source_run_id': event.record.source_run_id, 'as_of': event.as_of,
            'kind': event.kind, 'data': event.data, 'mandate_id': event.mandate_id}


@dataclass(frozen=True)
class ResearchJudgments:
    """复用工作笔记的研究业务能力；不管理Host或外部发布。"""

    records: ResearchJudgmentLog

    def events(self, scope: ResearchWorkScope) -> list[JudgmentEvent]:
        """读取本研究可见的全部事件。参数：作用域。返回：已验证事件。异常：越权、时间越界或损坏。"""
        return [_event(record) for record in self.records.list_named_notes(scope, JUDGMENT_NOTE_TITLE)]

    def _save(self, scope: ResearchWorkScope, call_id: str, kind: str, data: dict[str, JsonValue], *, mandate_id: str | None = None) -> ResearchWorkingRecord:
        """追加固定截止的不可变事件。参数：作用域、调用、种类、内容、原约定ID。返回：记录。异常：冲突或迟到。"""
        content = canonical_json({'kind': kind, 'as_of': scope.as_of.isoformat(), 'method_hash': scope.method_hash, 'data': data, 'mandate_id': mandate_id})
        return self.records.append_note(scope, call_id, title=JUDGMENT_NOTE_TITLE, content=content)

    def save_mandate(self, scope: ResearchWorkScope, call_id: str, mandate: InvestmentMandate) -> ResearchWorkingRecord:
        """保存收益约定，变化须另留原因。参数：作用域、调用、约定。返回：记录。异常：字段缺失或无理由改约定。"""
        data = encode_mandate(mandate);decode_mandate(data)
        prior = [event for event in self.events(scope) if event.kind == _MANDATE]
        if any(event.record.source_run_id == scope.run_id and event.record.tool_call_id == call_id for event in prior):
            return self._save(scope, call_id, _MANDATE, data)
        if prior and prior[-1].data != data and not mandate.change_reason:
            raise ValueError('修改收益约定必须提供change_reason，保留原约定')
        return self._save(scope, call_id, _MANDATE, data)

    def get_judgment(self, scope: ResearchWorkScope, judgment_id: str) -> JudgmentEvent:
        """读取同主题原判断。参数：作用域、记录ID。返回：不可变判断。异常：越界、未来或不存在。"""
        for event in self.events(scope):
            if event.kind == _JUDGMENT and event.record.record_id == judgment_id:
                return event
        raise KeyError('判断不存在于当前研究的信息集合')

    def save_judgment(self, scope: ResearchWorkScope, call_id: str, judgment: InvestmentJudgment) -> ResearchWorkingRecord:
        """保存可检验判断和证据。参数：作用域、调用、判断。返回：记录。异常：缺约定、引用或时间非法。"""
        events = self.events(scope)
        mandates = [event for event in events if event.kind == _MANDATE]
        if not mandates:
            raise ValueError('先保存本研究的收益来源、期限和失效条件约定')
        data = encode_judgment(judgment, scope.as_of);decode_judgment(data)
        if judgment.check_at <= scope.as_of:
            raise ValueError('新判断的检验时间必须晚于本轮截止')
        if judgment.previous_judgment_id is not None:
            previous = self.get_judgment(scope, judgment.previous_judgment_id)
            if previous.data['subject'] != judgment.subject:
                raise ValueError('新旧判断必须属于同一研究对象')
        replay = next((event for event in events if event.kind == _JUDGMENT and event.record.source_run_id == scope.run_id and event.record.tool_call_id == call_id), None)
        mandate_id = replay.mandate_id if replay else mandates[-1].record.record_id
        return self._save(scope, call_id, _JUDGMENT, data, mandate_id=mandate_id)

    def save_review(self, scope: ResearchWorkScope, call_id: str, review: JudgmentReview) -> ResearchWorkingRecord:
        """对原预测另存经营复盘。参数：作用域、调用、复盘。返回：新记录。异常：旧判断越界或观察不完整。"""
        self.get_judgment(scope, review.judgment_id)
        data = encode_review(review, scope.as_of);decode_review(data)
        return self._save(scope, call_id, _REVIEW, data)

    def list_judgments(self, scope: ResearchWorkScope, *, due_only: bool = False, offset: int = 0, limit: int = 20) -> dict[str, JsonValue]:
        """分页列出原判断、新证据与到期项。参数：作用域、仅到期、偏移、数量。返回：含原约定及对照的索引。异常：范围或作用域非法。"""
        if offset < 0 or not 1 <= limit <= _MAX_PAGE:
            raise ValueError('判断分页范围非法')
        events = self.events(scope)
        mandates = [event for event in events if event.kind == _MANDATE]
        reviews = [event for event in events if event.kind == _REVIEW]
        superseded = {cast(str, event.data['previous_judgment_id']) for event in events if event.kind == _JUDGMENT and isinstance(event.data.get('previous_judgment_id'), str)}
        rows: list[JsonValue] = [];due_count = 0
        for event in events:
            if event.kind != _JUDGMENT:
                continue
            related = [review for review in reviews if review.data['judgment_id'] == event.record.record_id]
            latest = related[-1] if related else None
            next_check = latest.data.get('next_check_at') if latest else event.data['check_at']
            is_superseded = event.record.record_id in superseded
            # 新预测可以取代旧预测的决策用途，但不能抹掉旧预测到期后的复盘责任。
            due = isinstance(next_check, str) and timestamp(next_check, 'next_check_at') <= scope.as_of
            due_count += int(due)
            if due_only and not due:
                continue
            rows.append({**event_view(event), 'latest_review': event_view(latest) if latest else None,
                         'review_history': [event_view(review) for review in related], 'due': due, 'superseded': is_superseded,
                         'original_mandate': next((event_view(item) for item in mandates if item.record.record_id == event.mandate_id), None),
                         'support_status': 'linked_evidence' if event.data['supporting_evidence_ids'] else 'unverified_hypothesis'})
        return {'mandate': event_view(mandates[-1]) if mandates else None, 'judgments': rows[offset:offset+limit],
                'total': len(rows), 'due_count': due_count, 'next_offset': offset+limit if offset+limit < len(rows) else None,
                'as_of': scope.as_of.isoformat(), 'review_mode': 'on_demand_no_background_scheduler'}
