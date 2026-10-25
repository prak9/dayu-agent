"""候选稿的字段校验、局部修订和按哈希提交，不形成外部副作用。"""

import asyncio
import copy
from dataclasses import dataclass, replace
from datetime import datetime
from typing import cast

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.protocols import ToolExecutionContext
from alpha.contracts.research_analysis import ResearchAnalysisRecords
from alpha.contracts.research_working import ResearchReportContent, ResearchWorkScope
from alpha.research.calculations import ResearchCalculationRejectedError, run_research_calculation
from alpha.research.evidence import decode_research_evidence, encode_research_evidence
from alpha.research.methods.alpha_invest.__main__ import CalculationMethod
from alpha.research.storage.encoding import canonical_json
from alpha.research.storage.protocols import ResearchMethods, ResearchWorkingRecords

_REQUIRED_EVIDENCE_TEXT = ("evidence_id", "source_ref", "document_type", "excerpt", "classification", "accessed_at")
_EVIDENCE_TIMES = ("accessed_at", "published_at", "available_at")


def patch_json(body: dict[str, JsonValue], path: str, value: JsonValue) -> dict[str, JsonValue]:
    """替换已存在的 JSON Pointer 字段。参数：原稿、路径、新值。返回：独立副本。异常：路径无效。"""
    if not path.startswith("/") or path == "/":
        raise ValueError("修订路径必须是非空 JSON Pointer")
    result = copy.deepcopy(body)
    parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
    current: JsonValue = result
    for part in parts[:-1]:
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            raise ValueError("修订路径不存在")
    key = parts[-1]
    if isinstance(current, dict):
        current[key] = value
    elif isinstance(current, list) and key.isdigit() and int(key) < len(current):
        current[int(key)] = value
    else:
        raise ValueError("修订目标不存在")
    return result


def _evidence_errors(body: dict[str, JsonValue], scope: ResearchWorkScope) -> list[JsonValue]:
    """一次返回可定位的证据错误。参数：原稿、固定截止。返回：字段错误。异常：无。"""
    evidence = body.get("evidence", [])
    if not isinstance(evidence, list):
        return [{"path": "/evidence", "message": "必须为数组"}]
    errors: list[JsonValue] = []
    seen: set[str] = set()
    for index, item in enumerate(evidence):
        prefix = f"/evidence/{index}"
        if not isinstance(item, dict):
            errors.append({"path": prefix, "message": "必须为对象"})
            continue
        valid = True
        for field in _REQUIRED_EVIDENCE_TEXT:
            if not isinstance(item.get(field), str) or not str(item[field]).strip():
                errors.append({"path": f"{prefix}/{field}", "message": "必须为非空字符串"})
                valid = False
        for field in _EVIDENCE_TIMES:
            value = item.get(field)
            if value is None and field != "accessed_at":
                continue
            try:
                if not isinstance(value, str):
                    raise ValueError("必须为 ISO 8601 时间字符串或空值")
                timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                    raise ValueError("时间必须包含时区")
                if field != "accessed_at" and timestamp > scope.as_of:
                    raise ValueError("来源时间晚于本轮截止时间")
            except ValueError as exc:
                errors.append({"path": f"{prefix}/{field}", "message": str(exc)})
                valid = False
        identity = item.get("evidence_id")
        if isinstance(identity, str):
            if identity in seen:
                errors.append({"path": f"{prefix}/evidence_id", "message": "证据 ID 重复"})
                valid = False
            seen.add(identity)
        if valid:
            try:
                encode_research_evidence(decode_research_evidence([item]), scope.as_of)
            except (ValueError, TypeError) as exc:
                errors.append({"path": prefix, "message": str(exc)})
    return errors


@dataclass(frozen=True)
class ResearchCandidates:
    """共享给内置 Agent 和外部 coding agent 的同一提交语义。"""

    analysis: ResearchAnalysisRecords
    working: ResearchWorkingRecords
    methods: ResearchMethods

    def validate(self, scope: ResearchWorkScope, candidate_id: str, context: ToolExecutionContext) -> dict[str, JsonValue]:
        """校验固定稿件和财务覆盖。参数：作用域、候选 ID、取消/预算。返回：完整字段错误及 hash。异常：候选缺失或执行失败。"""
        candidate = self.analysis.get_candidate(scope, candidate_id)
        body = candidate["body"]
        assert isinstance(body, dict)
        errors = _evidence_errors(body, scope) + self.analysis.coverage_errors(scope)
        markdown = body.get("report_markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            errors.append({"path": "/report_markdown", "message": "报告正文不能为空"})
        contract = body.get("data_contract")
        if self.analysis.requirements(scope) and contract is None:
            errors.append({"path": "/data_contract", "message": "财报研究必须提交数据口径与跨期核验契约"})
        if contract is not None:
            if not isinstance(contract, dict):
                errors.append({"path": "/data_contract", "message": "必须为对象"})
            else:
                normalized = {**contract, "as_of": scope.as_of.isoformat()}
                if scope.historical or "decision_time" in normalized:
                    normalized["decision_time"] = scope.as_of.isoformat()
                try:
                    asyncio.run(run_research_calculation(self.methods.load(scope.method_hash), CalculationMethod.VALIDATE_DATA, normalized,
                                timeout_seconds=context.timeout_seconds, cancellation_token=context.cancellation_token))
                except ResearchCalculationRejectedError as exc:
                    findings = exc.report.get("findings", [])
                    if isinstance(findings, list):
                        for finding in findings:
                            if isinstance(finding, dict) and finding.get("severity") == "error":
                                errors.append({"path": "/data_contract/" + str(finding.get("location", "")), "message": str(finding.get("message", "数据校验失败"))})
                    if not findings:
                        errors.append({"path": "/data_contract", "message": str(exc)})
        result: dict[str, JsonValue] = {"candidate_id": candidate_id, "content_hash": candidate["content_hash"], "valid": not errors, "errors": errors,
            "as_of": scope.as_of.isoformat(), "method_hash": scope.method_hash, "financial_receipts": self.analysis.financial_reads(scope)}
        if context.cancellation_token is not None:
            context.cancellation_token.raise_if_cancelled()
        if context.tool_call_id is not None:
            self.analysis.save_validation(scope, context.tool_call_id, candidate_id, result)
        return result

    def commit(self, scope: ResearchWorkScope, candidate_id: str, expected_hash: str, call_id: str,
               context: ToolExecutionContext) -> dict[str, JsonValue]:
        """重验后提交指定稿件。参数：作用域、ID、hash、调用、上下文。返回：提交身份或校验错误。异常：哈希或写入冲突。"""
        candidate = self.analysis.get_candidate(scope, candidate_id)
        if candidate["content_hash"] != expected_hash:
            raise ValueError("候选稿 hash 不匹配")
        checked = self.validate(scope, candidate_id, replace(context, tool_call_id=call_id))
        if not checked["valid"]:
            return checked
        body = self.analysis.get_candidate(scope, candidate_id)["body"]
        assert isinstance(body, dict)
        contract = body.get("data_contract")
        if isinstance(contract, dict):
            contract = {**contract, "as_of": scope.as_of.isoformat()}
            if scope.historical or "decision_time" in contract:
                contract["decision_time"] = scope.as_of.isoformat()
        record = self.working.append_report(scope, call_id, ResearchReportContent(cast(str, body["report_markdown"]),
                 decode_research_evidence(body.get("evidence", [])), canonical_json(contract) if contract is not None else None))
        return {**checked, "record_id": record.record_id, "submitted": True}
