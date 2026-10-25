"""研究仓储内部的确定编码、行映射与所有权检查。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import cast

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research import ResearchDepth, ResearchExecutionMode, ResearchPublicationPolicy, ResearchRecord, ResearchState, ResearchTurn, ResearchTurnState, ResearchTurnPreparation
from alpha.contracts.agent_execution import ExecutionContractSnapshotValue
from alpha.contracts.agent_execution_serialization import deserialize_accepted_execution_spec
from alpha.contracts.execution_options import ExecutionOptionsSnapshot, deserialize_execution_options_snapshot
from alpha.contracts.research_financials import decode_financial_requirements


def utc_now() -> datetime:
    """读取 UTC 当前时间。参数：无。返回：带时区时间。异常：无。"""
    return datetime.now(timezone.utc)


def encode_time(value: datetime | None) -> str | None:
    """编码时间。参数：value 可空时间。返回：UTC ISO 文本或空。异常：无时区时 ValueError。"""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("研究截止时间必须包含时区")
    return value.astimezone(timezone.utc).isoformat()


def canonical_json(value: JsonValue) -> str:
    """生成稳定 JSON。参数：value 强类型 JSON 值。返回：规范文本。异常：不可编码时 ValueError。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value: str) -> str:
    """计算文本 SHA256。参数：value 原文。返回：十六进制摘要。异常：无。"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def decode_strings(value: str) -> tuple[str, ...]:
    """解码字符串数组。参数：value JSON 文本。返回：字符串元组。异常：损坏时 ValueError。"""
    decoded = cast(JsonValue, json.loads(value))
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        raise ValueError("研究字符串数组已损坏")
    return tuple(cast(str, item) for item in decoded)


def owned_research(conn: sqlite3.Connection, research_id: str, owner_id: str) -> sqlite3.Row:
    """校验所有权。参数：conn 连接、research_id 研究、owner_id 用户。返回：记录行。异常：不存在或越权。"""
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM research_catalog WHERE research_id=?", (research_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"研究不存在：{research_id}")
    if str(row["owner_id"]) != owner_id:
        raise PermissionError("无权访问该研究")
    return row


def research_from_row(row: sqlite3.Row) -> ResearchRecord:
    """投影研究记录。参数：row 数据行。返回：研究契约。异常：损坏字段导致 ValueError。"""
    return ResearchRecord(
        research_id=str(row["research_id"]), owner_id=str(row["owner_id"]),
        title=str(row["title"]), question=str(row["question"]), subjects=decode_strings(str(row["subjects_json"])),
        session_id=str(row["session_id"]), state=ResearchState(row["state"]), version=int(row["version"]),
        as_of=datetime.fromisoformat(str(row["as_of"])) if row["as_of"] is not None else None,
        depth=ResearchDepth(row["depth"]), created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def turn_from_row(row: sqlite3.Row) -> ResearchTurn:
    """投影输入记录。参数：row 数据行。返回：输入契约。异常：损坏字段导致 ValueError。"""
    spec = cast(JsonValue, json.loads(str(row["accepted_spec_json"])))
    if not isinstance(spec, dict):
        raise ValueError("已接受执行规格快照损坏")
    options = None
    if row["execution_options_json"] is not None:
        raw_options = cast(JsonValue, json.loads(str(row["execution_options_json"])))
        if not isinstance(raw_options, dict):
            raise ValueError("显式执行选项快照损坏")
        options = deserialize_execution_options_snapshot(cast(ExecutionOptionsSnapshot, raw_options))
    return ResearchTurn(
        turn_id=str(row["turn_id"]), research_id=str(row["research_id"]), request_key=str(row["request_key"]),
        sequence=int(row["sequence"]), user_text=str(row["user_text"]),
        attachment_refs=decode_strings(str(row["attachment_refs_json"])), input_hash=str(row["input_hash"]),
        as_of=datetime.fromisoformat(str(row["as_of"])), state=ResearchTurnState(row["state"]),
        run_id=str(row["run_id"]) if row["run_id"] is not None else None,
        created_at=datetime.fromisoformat(str(row["created_at"])),
        host_epoch=int(row["host_epoch"]) if row["host_epoch"] is not None else None,
        preparation=ResearchTurnPreparation(str(row["method_hash"]), deserialize_accepted_execution_spec(cast(dict[str, ExecutionContractSnapshotValue], spec))),
        execution_options=options,
        historical=bool(row["historical"]),
        resume_request_key=str(row["resume_request_key"]) if row["resume_request_key"] is not None else None,
        financial_requirements=decode_financial_requirements(cast(JsonValue, json.loads(str(row["financial_requirements_json"])))),
        execution_mode=ResearchExecutionMode(str(row["execution_mode"])), publication_policy=ResearchPublicationPolicy(str(row["publication_policy"])),
        publication_target_id=str(row["publication_target_id"]) if row["publication_target_id"] is not None else None,
    )
