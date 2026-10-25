"""研究工具边界：从 Host 调用上下文取得作用域，禁止模型指定研究身份。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import ClassVar

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.protocols import ToolExecutionContext
from alpha.contracts.research_working import ResearchReportContent, ResearchWorkingRecord, ResearchWorkScope
from alpha.contracts.toolset_registrar import ToolRegistryProtocol
from alpha.engine.tool_contracts import ToolFunctionSchema, ToolSchema, ToolTruncateSpec
from alpha.engine.tool_errors import ToolBusinessError
from alpha.engine.tools.base import ToolExtra
from alpha.research.calculations import ResearchCalculationError, ResearchCalculationRejectedError, run_research_calculation
from alpha.research.evidence import decode_research_evidence
from alpha.research.evidence_schema import EVIDENCE_SCHEMA
from alpha.research.methods.alpha_invest.__main__ import CalculationMethod
from alpha.research.storage.encoding import canonical_json
from alpha.research.storage.protocols import ResearchMethods, ResearchRevisions, ResearchWorkingRecords

_RESEARCH_TAG = "research"
_CONTEXT_PARAM = "_context"
_NOTE_NAME = "research_save_note"
_CALCULATE_NAME = "research_calculate"
_LIST_NAME = "research_list_records"
_READ_NAME = "research_read_record"
_REPORT_NAME = "research_submit_report"
_REFERENCE_NAME = "research_read_method"
_HISTORY_NAME = "research_read_report"
_RECORD_PREVIEW_CHARS = 6000
_CONTEXT_ERROR = "research_context_missing"
_CALCULATION_ERROR = "research_calculation_failed"
_REJECTED_CALCULATION = "research_calculation_rejected"
_MAX_REPORT_CHARS = 200000
_MAX_NOTE_CHARS = 50000


def _scoped_contract(scope: ResearchWorkScope, data: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """限定数据契约时间。参数：可信作用域、原始契约。返回：独立规范副本。异常：无。"""
    normalized = {**data, "as_of": scope.as_of.isoformat()}
    if scope.historical or "decision_time" in data:
        normalized["decision_time"] = scope.as_of.isoformat()
    return normalized


@dataclass(frozen=True)
class _Call:
    """经过作用域核验的一次工具调用。"""

    scope: ResearchWorkScope
    call_id: str
    context: ToolExecutionContext


def _resolve_call(records: ResearchWorkingRecords, context: ToolExecutionContext | None) -> _Call:
    """核验 Host 调用身份。参数：工作端口、上下文。返回：调用。异常：缺少或未绑定上下文。"""
    if context is None or not context.run_id or not context.tool_call_id:
        raise ToolBusinessError(_CONTEXT_ERROR, "研究工具需要 Host 的 Run 与工具调用身份")
    if context.cancellation_token is not None:
        context.cancellation_token.raise_if_cancelled()
    try:
        scope = records.scope_for_run(context.run_id)
    except KeyError as exc:
        raise ToolBusinessError(_CONTEXT_ERROR, "当前 Run 未关联已接受的研究输入") from exc
    return _Call(scope, context.tool_call_id, context)


def _extra(display_name: str, *, truncate: ToolTruncateSpec | None = None) -> ToolExtra:
    """构造工具执行元数据。参数：显示名、截断策略。返回：引擎元数据。异常：无。"""
    return ToolExtra(__file_path_params__=[], __truncate__=truncate or ToolTruncateSpec(), __dup_call__=None,
                     __execution_context_param_name__=_CONTEXT_PARAM, __display_name__=display_name)


def _metadata(record: ResearchWorkingRecord) -> dict[str, JsonValue]:
    """投影日志索引。参数：记录。返回：模型可读索引。异常：无。"""
    return {"record_id": record.record_id, "source_run_id": record.source_run_id, "sequence": record.sequence,
            "kind": record.kind.value, "created_at": record.created_at.isoformat()}


def _calculate(
    records: ResearchWorkingRecords, methods: ResearchMethods, call: _Call, method: CalculationMethod,
    data: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """执行并记录固定计算。参数：端口、调用、方法、数据。返回：通过结果。异常：取消或计算业务错误。"""
    try:
        return asyncio.run(run_research_calculation(methods.load(call.scope.method_hash), method, data,
                                                    timeout_seconds=call.context.timeout_seconds,
                                                    cancellation_token=call.context.cancellation_token))
    except ResearchCalculationRejectedError as exc:
        record = records.append_calculation(call.scope, call.call_id, method=method.value, inputs=data,
                                             result=exc.report, accepted=False)
        raise ToolBusinessError(_REJECTED_CALCULATION, str(exc),
                                hint=f"用 {_READ_NAME} 读取 {record.record_id}，核对问题后以新工具调用修正输入。") from exc
    except ResearchCalculationError as exc:
        raise ToolBusinessError(_CALCULATION_ERROR, str(exc)) from exc


@dataclass(frozen=True)
class _NoteTool:
    """只向当前研究输入保存笔记。"""

    records: ResearchWorkingRecords
    __tool_tags__: ClassVar[set[str]] = {_RESEARCH_TAG}
    __tool_extra__: ClassVar[ToolExtra] = _extra("保存研究笔记")

    def __call__(self, title: str, content: str, _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """保存笔记。参数：标题、正文、Host 上下文。返回：索引。异常：取消、缺上下文或输入冲突。"""
        call = _resolve_call(self.records, _context)
        return _metadata(self.records.append_note(call.scope, call.call_id, title=title, content=content))


@dataclass(frozen=True)
class _CalculateTool:
    """执行固定方法并保留原始输入和结构化结果。"""

    records: ResearchWorkingRecords
    methods: ResearchMethods
    __tool_tags__: ClassVar[set[str]] = {_RESEARCH_TAG}
    __tool_extra__: ClassVar[ToolExtra] = _extra("研究确定计算")

    def __call__(self, method: str, data: dict[str, JsonValue], _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """运行计算。参数：方法、JSON 数据、Host 上下文。返回：结果及记录 ID。异常：计算失败或取消。"""
        call = _resolve_call(self.records, _context)
        if method == CalculationMethod.VALIDATE_DATA.value:
            data = _scoped_contract(call.scope, data)
        result = _calculate(self.records, self.methods, call, CalculationMethod(method), data)
        record = self.records.append_calculation(call.scope, call.call_id, method=method, inputs=data, result=result, accepted=True)
        return {**result, "record_id": record.record_id}


@dataclass(frozen=True)
class _ListTool:
    """分页查看当前研究输入的记录索引。"""

    records: ResearchWorkingRecords
    __tool_tags__: ClassVar[set[str]] = {_RESEARCH_TAG}
    __tool_extra__: ClassVar[ToolExtra] = _extra("列出研究记录")

    def __call__(self, after_sequence: int = 0, limit: int = 20, _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """列出索引。参数：序号游标、数量、上下文。返回：索引列表。异常：作用域或范围非法。"""
        call = _resolve_call(self.records, _context)
        records: list[JsonValue] = [_metadata(record) for record in self.records.list_records(call.scope, after_sequence=after_sequence, limit=limit)]
        return {"records": records}


@dataclass(frozen=True)
class _ReadTool:
    """读取当前输入的完整记录，通过引擎续读限制上下文大小。"""

    records: ResearchWorkingRecords
    __tool_tags__: ClassVar[set[str]] = {_RESEARCH_TAG}
    __tool_extra__: ClassVar[ToolExtra] = _extra("读取研究记录", truncate=ToolTruncateSpec(
        enabled=True, strategy="text_chars", limits={"max_chars": _RECORD_PREVIEW_CHARS}, target_field="body_json"))

    def __call__(self, record_id: str, _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """读取记录。参数：ID、上下文。返回：正文及来源。异常：越界或记录损坏。"""
        call = _resolve_call(self.records, _context)
        record = self.records.get_record(call.scope, record_id)
        return {**_metadata(record), "body_json": record.body_json}


@dataclass(frozen=True)
class _ReferenceTool:
    """按需读取当前受理固定的方法参考。"""

    records: ResearchWorkingRecords
    methods: ResearchMethods
    __tool_tags__: ClassVar[set[str]] = {_RESEARCH_TAG}
    __tool_extra__: ClassVar[ToolExtra] = _extra("读取研究方法", truncate=ToolTruncateSpec(
        enabled=True, strategy="text_chars", limits={"max_chars": _RECORD_PREVIEW_CHARS}, target_field="content"))

    def __call__(self, path: str, _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """读取文档。参数：包内相对路径、Host 上下文。返回：正文。异常：作用域、路径或完整性错误。"""
        call = _resolve_call(self.records, _context)
        return {"path": path, "content": self.methods.read_reference(call.scope.method_hash, path)}


@dataclass(frozen=True)
class _HistoryTool:
    """读取当前研究的完整历史报告，不接受模型指定研究身份。"""

    records: ResearchWorkingRecords
    revisions: ResearchRevisions
    __tool_tags__: ClassVar[set[str]] = {_RESEARCH_TAG}
    __tool_extra__: ClassVar[ToolExtra] = _extra("读取历史研究报告", truncate=ToolTruncateSpec(
        enabled=True, strategy="text_chars", limits={"max_chars": _RECORD_PREVIEW_CHARS}, target_field="content"))

    def __call__(self, revision_id: str | None = None, _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """读取指定或最新版本。参数：可选版本、上下文。返回：正文及版本索引。异常：越权、缺失或损坏。"""
        scope = _resolve_call(self.records, _context).scope
        versions = self.revisions.list_revisions(scope.research_id, scope.owner_id)
        if not versions:
            return {"versions": [], "content": "尚无正式研究报告"}
        revision = self.revisions.get(revision_id, scope.owner_id) if revision_id is not None else versions[-1]
        if revision.research_id != scope.research_id:
            raise ToolBusinessError(_CONTEXT_ERROR, "不能读取其他研究的报告")
        return {"revision_id": revision.revision_id, "content": self.revisions.read_report(revision.revision_id, scope.owner_id),
                "versions": [item.revision_id for item in versions]}


@dataclass(frozen=True)
class _ReportTool:
    """校验证据与可选数据契约后保存本轮报告，不发布外部系统。"""

    records: ResearchWorkingRecords
    methods: ResearchMethods
    __tool_tags__: ClassVar[set[str]] = {_RESEARCH_TAG}
    __tool_extra__: ClassVar[ToolExtra] = _extra("提交研究报告")

    def __call__(
        self, report_markdown: str, evidence: list[JsonValue] | None = None,
        data_contract: dict[str, JsonValue] | None = None, _context: ToolExecutionContext | None = None,
    ) -> dict[str, JsonValue]:
        """保存报告。参数：正文、证据、数据契约、上下文。返回：记录及校验状态。异常：数据、来源或取消失败。"""
        call = _resolve_call(self.records, _context)
        if data_contract is not None:
            data_contract = _scoped_contract(call.scope, data_contract)
            _calculate(self.records, self.methods, call, CalculationMethod.VALIDATE_DATA, data_contract)
        report = ResearchReportContent(report_markdown, decode_research_evidence(evidence or []),
                                       canonical_json(data_contract) if data_contract is not None else None)
        record = self.records.append_report(call.scope, call.call_id, report)
        return {**_metadata(record), "data_contract_validated": data_contract is not None}


def _schema(name: str, description: str, parameters: dict[str, JsonValue]) -> ToolSchema:
    """构造声明式 schema。参数：名称、说明、参数结构。返回：工具 schema。异常：schema 配置错误。"""
    return ToolSchema(ToolFunctionSchema(name=name, description=description, parameters=parameters))


def register_research_tools(registry: ToolRegistryProtocol, records: ResearchWorkingRecords, methods: ResearchMethods, revisions: ResearchRevisions) -> int:
    """登记研究工具。参数：注册端口、工作日志、方法与版本仓储。返回：实际业务工具数。异常：schema 或注册失败。"""
    registry.register(_NOTE_NAME, _NoteTool(records), _schema(_NOTE_NAME, "保存当前研究的判断、来源定位与待核验缺口。", {
        "type": "object", "additionalProperties": False,
        "properties": {"title": {"type": "string"}, "content": {"type": "string", "maxLength": _MAX_NOTE_CHARS}}, "required": ["title", "content"],
    }))
    registry.register(_CALCULATE_NAME, _CalculateTool(records, methods), _schema(_CALCULATE_NAME, "用固定 invest 方法计算并保存输入输出；失败状态不能当作校验通过。", {
        "type": "object", "additionalProperties": False,
        "properties": {"method": {"type": "string", "enum": [method.value for method in CalculationMethod]}, "data": {"type": "object", "additionalProperties": True}},
        "required": ["method", "data"],
    }))
    registry.register(_LIST_NAME, _ListTool(records), _schema(_LIST_NAME, "列出当前研究输入的记录，恢复时先检查已完成工作。", {
        "type": "object", "additionalProperties": False,
        "properties": {"after_sequence": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
        "required": [],
    }))
    registry.register(_READ_NAME, _ReadTool(records), _schema(_READ_NAME, "读取当前输入的完整笔记或计算记录；截断时使用 fetch_more。", {
        "type": "object", "additionalProperties": False, "properties": {"record_id": {"type": "string"}}, "required": ["record_id"],
    }))
    registry.register(_REFERENCE_NAME, _ReferenceTool(records, methods), _schema(_REFERENCE_NAME, "读取固定 invest 方法参考。path 从 skills/ 开始；相对引用按所在文档目录解析，截断时用 fetch_more。", {
        "type": "object", "additionalProperties": False, "properties": {"path": {"type": "string"}}, "required": ["path"],
    }))
    registry.register(_HISTORY_NAME, _HistoryTool(records, revisions), _schema(_HISTORY_NAME, "读取当前研究的指定或最新正式报告；也返回版本索引，截断时用 fetch_more。", {
        "type": "object", "additionalProperties": False, "properties": {"revision_id": {"type": "string"}}, "required": [],
    }))
    registry.register(_REPORT_NAME, _ReportTool(records, methods), _schema(_REPORT_NAME, "完成证据和写作核对后提交本轮报告；Host 成功结束后由业务层形成不可变版本。该工具不会发布 Notion。", {
        "type": "object", "additionalProperties": False,
        "properties": {"report_markdown": {"type": "string", "maxLength": _MAX_REPORT_CHARS}, "evidence": {"type": "array", "items": EVIDENCE_SCHEMA},
                       "data_contract": {"type": "object", "additionalProperties": True}}, "required": ["report_markdown"],
    }))
    return len((_NOTE_NAME, _CALCULATE_NAME, _LIST_NAME, _READ_NAME, _REFERENCE_NAME, _HISTORY_NAME, _REPORT_NAME))
