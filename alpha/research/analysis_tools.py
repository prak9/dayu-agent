"""内置与外部 Agent 共用的候选稿、恢复和财报读取工具。"""

from dataclasses import dataclass
from typing import ClassVar

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.protocols import ToolExecutionContext
from alpha.contracts.research_analysis import ResearchAnalysisRecords
from alpha.contracts.research_financials import FinancialResearchReader, encode_financial_requirements
from alpha.contracts.toolset_registrar import ToolRegistryProtocol
from alpha.engine.tool_contracts import ToolTruncateSpec
from alpha.engine.tools.base import ToolExtra
from alpha.research.candidates import ResearchCandidates, patch_json
from alpha.research.evidence_schema import EVIDENCE_SCHEMA
from alpha.research.storage.protocols import ResearchWorkingRecords
from alpha.research.storage.encoding import canonical_json
from alpha.research.tools import _extra, _resolve_call, _schema

_TAG = {"research"}
_PREVIEW_CHARS = 12000
_MAX_REPORT_CHARS = 200000


@dataclass(frozen=True)
class _Draft:
    """保存原始稿件，字段错误由独立校验统一返回。"""

    candidates: ResearchCandidates
    __tool_tags__: ClassVar[set[str]] = _TAG
    __tool_extra__: ClassVar[ToolExtra] = _extra("保存候选稿")

    def __call__(self, report_markdown: str, evidence: list[JsonValue] | None = None, data_contract: dict[str, JsonValue] | None = None,
                 _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """保存原稿。参数：正文、证据、契约、上下文。返回：ID/hash。异常：取消、迟到或存储失败。"""
        call = _resolve_call(self.candidates.working, _context)
        saved = self.candidates.analysis.save_candidate(call.scope, call.call_id, {"report_markdown": report_markdown,
                                                        "evidence": evidence or [], "data_contract": data_contract})
        return {key: value for key, value in saved.items() if key != "body"}


@dataclass(frozen=True)
class _Patch:
    """局部修订形成新候选稿，原稿不可变。"""

    candidates: ResearchCandidates
    __tool_tags__: ClassVar[set[str]] = _TAG
    __tool_extra__: ClassVar[ToolExtra] = _extra("修订候选稿")

    def __call__(self, candidate_id: str, path: str, value: JsonValue, _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """替换一个字段。参数：候选、JSON Pointer、新值、上下文。返回：新 ID/hash。异常：路径或作用域非法。"""
        call = _resolve_call(self.candidates.working, _context)
        original = self.candidates.analysis.get_candidate(call.scope, candidate_id)["body"]
        assert isinstance(original, dict)
        saved = self.candidates.analysis.save_candidate(call.scope, call.call_id, patch_json(original, path, value))
        return {key: part for key, part in saved.items() if key != "body"}


@dataclass(frozen=True)
class _Validate:
    """只校验指定稿件，不提交正式报告。"""

    candidates: ResearchCandidates
    __tool_tags__: ClassVar[set[str]] = _TAG
    __tool_extra__: ClassVar[ToolExtra] = _extra("校验候选稿")

    def __call__(self, candidate_id: str, _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """校验稿件。参数：候选、上下文。返回：字段错误及 hash。异常：取消或计算失败。"""
        call = _resolve_call(self.candidates.working, _context)
        return self.candidates.validate(call.scope, candidate_id, call.context)


@dataclass(frozen=True)
class _Commit:
    """以 ID/hash 提交已固定稿件，提交前再次校验。"""

    candidates: ResearchCandidates
    __tool_tags__: ClassVar[set[str]] = _TAG
    __tool_extra__: ClassVar[ToolExtra] = _extra("提交候选稿")

    def __call__(self, candidate_id: str, content_hash: str, _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """提交稿件。参数：候选、hash、上下文。返回：本轮提交身份。异常：取消、迟到或 hash 冲突。"""
        call = _resolve_call(self.candidates.working, _context)
        return self.candidates.commit(call.scope, candidate_id, content_hash, call.call_id, call.context)


@dataclass(frozen=True)
class _Checkpoints:
    """恢复同研究的历史候选稿来源，并显示本轮固定覆盖要求。"""

    working: ResearchWorkingRecords
    analysis: ResearchAnalysisRecords
    __tool_tags__: ClassVar[set[str]] = _TAG
    __tool_extra__: ClassVar[ToolExtra] = _extra("恢复研究检查点")

    def __call__(self, _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """读取恢复索引。参数：上下文。返回：来源、要求、覆盖缺口。异常：作用域非法。"""
        call = _resolve_call(self.working, _context)
        history: list[JsonValue] = [record for record in self.working.list_checkpoints(call.scope)]
        return {"checkpoints": self.analysis.checkpoints(call.scope), "as_of": call.scope.as_of.isoformat(),
                "working_records": history,
                "financial_reads": self.analysis.financial_reads(call.scope),
                "financial_requirements": encode_financial_requirements(self.analysis.requirements(call.scope)),
                "coverage_errors": self.analysis.coverage_errors(call.scope)}


@dataclass(frozen=True)
class _ReadCheckpoint:
    """恢复时完整读取原笔记或候选稿，保留其来源。"""

    candidates: ResearchCandidates
    __tool_tags__: ClassVar[set[str]] = _TAG
    __tool_extra__: ClassVar[ToolExtra] = _extra("读取研究检查点", truncate=ToolTruncateSpec(
        enabled=True, strategy="text_chars", limits={"max_chars": _PREVIEW_CHARS}, target_field="content"))

    def __call__(self, record_id: str | None = None, candidate_id: str | None = None,
                 _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """读取检查点。参数：二选一记录或候选、上下文。返回：完整来源与内容。异常：越界或损坏。"""
        call = _resolve_call(self.candidates.working, _context)
        if (record_id is None) == (candidate_id is None):
            raise ValueError("必须且只能指定 record_id 或 candidate_id")
        if candidate_id is not None:
            result = self.candidates.analysis.get_candidate(call.scope, candidate_id)
            return {**{key: value for key, value in result.items() if key != "body"}, "content": canonical_json(result["body"])}
        result = self.candidates.working.read_checkpoint(call.scope, record_id or "")
        return {**{key: value for key, value in result.items() if key != "body_json"}, "content": result["body_json"]}


@dataclass(frozen=True)
class _PrepareSource:
    """选定已下载文档，在 Host 工具取消作用域内处理。"""

    working: ResearchWorkingRecords
    reader: FinancialResearchReader
    __tool_tags__: ClassVar[set[str]] = _TAG
    __tool_extra__: ClassVar[ToolExtra] = _extra("处理选定财报")

    def __call__(self, ticker: str, document_id: str, _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """处理文档。参数：公司、文档、上下文。返回：处理摘要。异常：缺失、取消或解析失败。"""
        call = _resolve_call(self.working, _context)
        return self.reader.prepare(ticker, document_id, call.context.cancellation_token)


@dataclass(frozen=True)
class _DownloadSources:
    """在当前 Host 工具作用域下载，不创建独立后台任务。"""

    working: ResearchWorkingRecords
    reader: FinancialResearchReader
    __tool_tags__: ClassVar[set[str]] = _TAG
    __tool_extra__: ClassVar[ToolExtra] = _extra("下载研究财报")

    def __call__(self, ticker: str, form_types: list[str] | None = None, start_date: str | None = None, end_date: str | None = None,
                 _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """下载明确范围。参数：公司、表单、日期、上下文。返回：源文件清单。异常：取消或下载失败。"""
        call = _resolve_call(self.working, _context)
        return self.reader.download(ticker, tuple(form_types or []), start_date, end_date, call.context.cancellation_token)


@dataclass(frozen=True)
class _ReadFinancial:
    """实际读取结果与原件、处理快照一并记录，模型不能自填读取证明。"""

    working: ResearchWorkingRecords
    analysis: ResearchAnalysisRecords
    reader: FinancialResearchReader
    __tool_tags__: ClassVar[set[str]] = _TAG
    __tool_extra__: ClassVar[ToolExtra] = _extra("读取财报并保存证据", truncate=ToolTruncateSpec(
        enabled=True, strategy="text_chars", limits={"max_chars": _PREVIEW_CHARS}, target_field="result"))

    def __call__(self, ticker: str, document_id: str, statement_type: str | None = None, table_ref: str | None = None,
                 _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """读取一张报表或表格。参数：公司、文档、二选一定位、上下文。返回：数据及读取凭据。异常：读取或保存失败。"""
        call = _resolve_call(self.working, _context)
        result = self.reader.read(ticker, document_id, statement_type=statement_type, table_ref=table_ref, token=call.context.cancellation_token)
        return self.analysis.save_read(call.scope, call.call_id, result)


def register_analysis_tools(registry: ToolRegistryProtocol, candidates: ResearchCandidates, reader: FinancialResearchReader) -> int:
    """装配九个分析工具。参数：注册表、候选服务、财报读取端口。返回：数量。异常：注册失败。"""
    registry.register("research_draft_report", _Draft(candidates), _schema("research_draft_report", "保存候选稿并返回 ID/hash；随后校验、局部修订并按 ID 提交。", {
        "type": "object", "additionalProperties": False, "properties": {"report_markdown": {"type": "string", "maxLength": _MAX_REPORT_CHARS},
        "evidence": {"type": "array", "items": {}, "description": "候选稿可暂存错误字段，完整校验在 validate 阶段返回。最终证据契约：" + canonical_json(EVIDENCE_SCHEMA)},
        "data_contract": {"type": "object", "additionalProperties": True}}, "required": ["report_markdown"]}))
    registry.register("research_patch_candidate", _Patch(candidates), _schema("research_patch_candidate", "按 JSON Pointer 局部修订，返回新 ID/hash；原候选不变。", {
        "type": "object", "additionalProperties": False, "properties": {"candidate_id": {"type": "string"}, "path": {"type": "string"},
        "value": {"type": ["null", "boolean", "number", "object", "array", "string"],
                  "maxLength": _MAX_REPORT_CHARS, "additionalProperties": True, "items": {}}},
        "required": ["candidate_id", "path", "value"]}))
    registry.register("research_validate_candidate", _Validate(candidates), _schema("research_validate_candidate", "返回候选稿的字段路径错误和财报覆盖缺口；错误属于可修正结果。", {
        "type": "object", "additionalProperties": False, "properties": {"candidate_id": {"type": "string"}}, "required": ["candidate_id"]}))
    registry.register("research_commit_candidate", _Commit(candidates), _schema("research_commit_candidate", "按固定 ID/hash 重验并提交本轮稿件，Host 成功后才生成正式版本。", {
        "type": "object", "additionalProperties": False, "properties": {"candidate_id": {"type": "string"}, "content_hash": {"type": "string"}},
        "required": ["candidate_id", "content_hash"]}))
    registry.register("research_checkpoints", _Checkpoints(candidates.working, candidates.analysis), _schema("research_checkpoints", "读取同研究跨 Run 的检查点来源、本轮截止及必需财报覆盖。", {
        "type": "object", "additionalProperties": False, "properties": {}, "required": []}))
    registry.register("research_read_checkpoint", _ReadCheckpoint(candidates), _schema("research_read_checkpoint", "完整读取同研究历史笔记、计算或候选稿；来源截止不晚于本轮，截断用 fetch_more。", {
        "type": "object", "additionalProperties": False, "properties": {"record_id": {"type": "string"}, "candidate_id": {"type": "string"}}, "required": []}))
    registry.register("research_prepare_source", _PrepareSource(candidates.working, reader), _schema("research_prepare_source", "在当前 Host 工具作用域处理一个已下载的财报源文档，完成后用 research_read_financial 读取。", {
        "type": "object", "additionalProperties": False, "properties": {"ticker": {"type": "string"}, "document_id": {"type": "string"}}, "required": ["ticker", "document_id"]}))
    registry.register("research_download_filings", _DownloadSources(candidates.working, reader), _schema("research_download_filings", "在当前 Host 工具作用域下载财报，返回源文档 ID；下一步逐个 research_prepare_source，再 research_read_financial。", {
        "type": "object", "additionalProperties": False, "properties": {"ticker": {"type": "string"}, "form_types": {"type": "array", "items": {"type": "string"}},
        "start_date": {"type": "string"}, "end_date": {"type": "string"}}, "required": ["ticker"]}))
    registry.register("research_read_financial", _ReadFinancial(candidates.working, candidates.analysis, reader), _schema("research_read_financial", "实际读取标准报表或表格并保存原件/处理产物/结果 hash；财报必需覆盖仅认可这些实际读取。", {
        "type": "object", "additionalProperties": False, "properties": {"ticker": {"type": "string"}, "document_id": {"type": "string"},
        "statement_type": {"type": "string", "enum": ["income", "balance_sheet", "cash_flow"]}, "table_ref": {"type": "string"}}, "required": ["ticker", "document_id"]}))
    return 9
