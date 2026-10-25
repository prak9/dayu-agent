"""显式升级旧研究库并保留原版本和请求身份。"""

import sqlite3
from pathlib import Path

import pytest

from alpha.cli.workspace_migrations.research_analysis_schema import migrate_research_analysis_schema
from alpha.cli.workspace_migrations.runner import apply_all_workspace_migrations
from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research import CreateResearchRequest, SubmitResearchTurnRequest
from alpha.research.storage.catalog import SQLiteResearchCatalog
from alpha.research.storage.encoding import canonical_json, content_hash
from alpha.research.storage.store import ResearchStore
from alpha.research.storage.turns import SQLiteResearchTurns
from alpha.workspace_paths import build_research_store_path
from tests.research.factories import research_turn_preparation


@pytest.mark.parametrize("version", [1, 2, 3])
def test_init_upgrades_old_schema_and_original_request_is_idempotent(tmp_path: Path, version: int) -> None:
    """旧资料和输入标识不因加字段而丢失。参数：目录、旧版本。返回：无。异常：断言失败。"""
    path = build_research_store_path(tmp_path)
    store = ResearchStore(path)
    research = SQLiteResearchCatalog(store).create(CreateResearchRequest("owner", "create", "原研究"))
    request = SubmitResearchTurnRequest(research.research_id, "owner", "begin", "原始问题")
    turn = SQLiteResearchTurns(store).enqueue(request, research_turn_preparation())
    old_body: dict[str, JsonValue] = {"user_text": "原始问题", "as_of": None, "attachment_refs": [], "execution_options": None}
    if version >= 2:
        old_body["financial_requirements"] = []
    if version == 3:
        old_body.update({"execution_mode": "internal", "publication_policy": "manual"})
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE research_turns SET input_hash=?", (content_hash(canonical_json(old_body)),))
        conn.execute("ALTER TABLE research_turns DROP COLUMN publication_target_id")
        if version < 3:
            conn.execute("ALTER TABLE research_turns DROP COLUMN publication_policy")
            conn.execute("ALTER TABLE research_turns DROP COLUMN execution_mode")
        if version == 1:
            conn.execute("ALTER TABLE research_turns DROP COLUMN financial_requirements_json")
        conn.execute(f"PRAGMA user_version={version}")
    with pytest.raises(RuntimeError, match="init"):
        ResearchStore(path)
    apply_all_workspace_migrations(base_dir=tmp_path, config_dir=tmp_path / "config")
    upgraded = ResearchStore(path)
    restored_research = SQLiteResearchCatalog(upgraded).get(research.research_id, "owner")
    assert restored_research.research_id == research.research_id and restored_research.question == research.question
    restored = SQLiteResearchTurns(upgraded).find(request)
    assert restored is not None and restored.turn_id == turn.turn_id and restored.financial_requirements == ()
    assert not migrate_research_analysis_schema(tmp_path)


def test_missing_database_and_unknown_schema(tmp_path: Path) -> None:
    """缺库不虚构升级，未知版本明确拒绝。参数：目录。返回：无。异常：断言失败。"""
    assert not migrate_research_analysis_schema(tmp_path)
    path = build_research_store_path(tmp_path)
    ResearchStore(path)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=99")
    with pytest.raises(RuntimeError, match="未知"):
        migrate_research_analysis_schema(tmp_path)
