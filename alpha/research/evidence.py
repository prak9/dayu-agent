"""研究证据的确定编码与时间校验，不存储文件或调用工具。"""

from __future__ import annotations

from datetime import datetime, timezone

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research import EvidenceClassification, ResearchEvidence


def _time(value: datetime | None) -> str | None:
    """编码带时区时间。参数：value 时间。返回：UTC ISO 或空。异常：无时区时 ValueError。"""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("证据时间必须包含时区")
    return value.astimezone(timezone.utc).isoformat()


def encode_research_evidence(evidence_records: tuple[ResearchEvidence, ...], as_of: datetime) -> list[JsonValue]:
    """校验并编码证据。参数：evidence_records 证据、as_of 截止时间。返回：JSON 数组。异常：字段或时间非法。"""
    payload: list[JsonValue] = []
    ids: set[str] = set()
    for evidence in evidence_records:
        if not evidence.evidence_id or not evidence.source_ref or not evidence.document_type or not evidence.excerpt:
            raise ValueError("证据 ID、来源、文档类型和摘录不能为空")
        if evidence.evidence_id in ids:
            raise ValueError("证据 ID 不能重复")
        ids.add(evidence.evidence_id)
        for timestamp in (evidence.available_at, evidence.published_at):
            _time(timestamp)
            if timestamp is not None and timestamp > as_of:
                raise ValueError("证据时间晚于本轮研究截止时间")
        if evidence.available_at is None and evidence.published_at is None and not evidence.time_missing_reason:
            raise ValueError("未知证据时间必须记录缺失原因")
        payload.append({
            "evidence_id": evidence.evidence_id, "source_ref": evidence.source_ref,
            "document_type": evidence.document_type, "excerpt": evidence.excerpt,
            "classification": evidence.classification.value, "accessed_at": _time(evidence.accessed_at),
            "locator": evidence.locator, "published_at": _time(evidence.published_at),
            "available_at": _time(evidence.available_at), "time_missing_reason": evidence.time_missing_reason,
        })
    return payload


def _text(data: dict[str, JsonValue], field: str, *, optional: bool = False) -> str | None:
    """读取证据文本字段。参数：对象、字段、是否可空。返回：文本或空。异常：字段类型非法。"""
    value = data.get(field)
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError(f"证据字段 {field} 必须是文本")
    return value


def _decoded_time(data: dict[str, JsonValue], field: str, *, optional: bool = False) -> datetime | None:
    """读取证据时间字段。参数：对象、字段、是否可空。返回：时间或空。异常：时间类型或格式非法。"""
    value = _text(data, field, optional=optional)
    if value is None:
        return None
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _time(result)
    return result


def decode_research_evidence(value: JsonValue) -> tuple[ResearchEvidence, ...]:
    """读取结构化证据。参数：value JSON 数组。返回：证据元组。异常：字段缺失或类型非法。"""
    if not isinstance(value, list):
        raise ValueError("evidence 必须是数组")
    result: list[ResearchEvidence] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("证据必须是对象")
        accessed_at = _decoded_time(item, "accessed_at")
        assert accessed_at is not None
        result.append(ResearchEvidence(
            evidence_id=_text(item, "evidence_id") or "", source_ref=_text(item, "source_ref") or "",
            document_type=_text(item, "document_type") or "", excerpt=_text(item, "excerpt") or "",
            classification=EvidenceClassification(_text(item, "classification")), accessed_at=accessed_at,
            locator=_text(item, "locator", optional=True), published_at=_decoded_time(item, "published_at", optional=True),
            available_at=_decoded_time(item, "available_at", optional=True), time_missing_reason=_text(item, "time_missing_reason", optional=True),
        ))
    return tuple(result)
