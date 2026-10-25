"""研究分析 schema 的显式一次性升级；运行时只接受当前版本。"""

import sqlite3
import json
from pathlib import Path
from typing import cast

from alpha.workspace_paths import build_research_store_path
from alpha.contracts.agent_types import JsonValue
from alpha.research.storage.encoding import canonical_json, content_hash

_SOURCE_VERSION = 1
_INTERMEDIATE_VERSION = 2
_EXECUTION_VERSION = 3
_TARGET_VERSION = 4


def _migrate_input_hash(row: sqlite3.Row) -> str:
    """升级请求摘要并核验旧身份。参数：旧输入行。返回：新摘要。异常：旧摘要损坏。"""
    base: dict[str, JsonValue] = {"user_text": str(row["user_text"]), "attachment_refs": cast(JsonValue, json.loads(str(row["attachment_refs_json"]))),
        "execution_options": cast(JsonValue, json.loads(str(row["execution_options_json"]))) if row["execution_options_json"] is not None else None}
    requirements = cast(JsonValue, json.loads(str(row["financial_requirements_json"])))
    for cutoff in (None, str(row["as_of"])):
        original = {**base, "as_of": cutoff}
        intermediate = {**original, "financial_requirements": requirements}
        execution = {**intermediate, "execution_mode": str(row["execution_mode"]), "publication_policy": str(row["publication_policy"])}
        if str(row["input_hash"]) in (content_hash(canonical_json(original)), content_hash(canonical_json(intermediate)), content_hash(canonical_json(execution))):
            return content_hash(canonical_json({**execution, "publication_target_id": None}))
    raise RuntimeError("旧研究输入摘要损坏，迁移已回滚")


def migrate_research_analysis_schema(base_dir: Path) -> bool:
    """保留旧研究并增加固定财报要求。参数：工作区。返回：是否升级。异常：未知版本或 SQLite 错误。"""
    path = build_research_store_path(base_dir)
    if not path.exists():
        return False
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version == _TARGET_VERSION:
            return False
        if version not in (_SOURCE_VERSION, _INTERMEDIATE_VERSION, _EXECUTION_VERSION):
            raise RuntimeError("未知研究库版本，拒绝推测迁移")
        if version == _SOURCE_VERSION:
            conn.execute("ALTER TABLE research_turns ADD COLUMN financial_requirements_json TEXT NOT NULL DEFAULT '[]'")
        if version < _EXECUTION_VERSION:
            conn.execute("ALTER TABLE research_turns ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'internal'")
            conn.execute("ALTER TABLE research_turns ADD COLUMN publication_policy TEXT NOT NULL DEFAULT 'manual'")
        conn.execute("ALTER TABLE research_turns ADD COLUMN publication_target_id TEXT")
        for row in conn.execute("SELECT * FROM research_turns").fetchall():
            conn.execute("UPDATE research_turns SET input_hash=? WHERE turn_id=?", (_migrate_input_hash(row), row["turn_id"]))
        conn.execute(f"PRAGMA user_version={_TARGET_VERSION}")
    return True
