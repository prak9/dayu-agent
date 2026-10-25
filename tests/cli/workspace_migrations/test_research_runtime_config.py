"""旧工作区研究 registrar 与新渠道配置的增量升级测试。"""

import json
from pathlib import Path

from alpha.cli.commands.init import _copy_config
from alpha.cli.workspace_migrations import apply_all_workspace_migrations
from alpha.cli.workspace_migrations.research_runtime_config import migrate_research_runtime_config
import pytest


def test_existing_workspace_gets_research_registrar_and_missing_channel_configs(tmp_path: Path) -> None:
    """升级不覆盖用户配置，新增研究与渠道入口能装配。参数：目录。返回：无。异常：断言失败。"""
    config = tmp_path / "config"
    config.mkdir()
    registrar = config / "toolset_registrars.json"
    registrar.write_text(json.dumps({"fins": "alpha.fins.toolset_registrars.register_fins_read_toolset", "custom": "custom.module.register"}))
    (config / "run.json").write_text(json.dumps({"host_config": {"lane": {"llm_api": 3}}}))
    apply_all_workspace_migrations(base_dir=tmp_path, config_dir=config)
    _copy_config(tmp_path, overwrite=False)
    loaded = json.loads(registrar.read_text())
    assert loaded["research"] == "alpha.research.toolset_registrars.register_research_toolset"
    assert loaded["custom"] == "custom.module.register"
    assert (config / "notion.json").is_file() and (config / "telegram.json").is_file()
    assert (config / "prompts/manifests/research.json").is_file()
    lane = json.loads((config / "run.json").read_text())["host_config"]["lane"]
    assert lane["llm_api"] == 3 and lane["publication"] == 1


def test_runtime_config_preserves_custom_entries_and_is_idempotent(tmp_path: Path) -> None:
    """定制 registrar、目标和并发均保留，重复执行不写入。参数：目录。返回：无。异常：断言失败。"""
    custom = tmp_path / "config"
    custom.mkdir()
    registrar = custom / "toolset_registrars.json"
    registrar.write_text('{"research":"custom.research.register"}')
    notion = custom / "notion.json"
    notion.write_text('{"parent_page_id":"custom-parent"}')
    (custom / "run.json").write_text('{"host_config":{"lane":{"publication":2}}}')
    assert migrate_research_runtime_config(custom)
    assert registrar.read_text() == '{"research":"custom.research.register"}'
    assert notion.read_text() == '{"parent_page_id":"custom-parent"}'
    assert not migrate_research_runtime_config(custom)
    assert not migrate_research_runtime_config(tmp_path / "missing")
    assert json.loads((custom / "run.json").read_text())["host_config"]["lane"]["publication"] == 2


@pytest.mark.parametrize("tags", [["research", "web", "fins", "ingestion"], ["research", "custom"]])
def test_research_manifest_removes_only_previous_default_ingestion_tag(tmp_path: Path, tags: list[str]) -> None:
    """仅升级旧默认标签，保留自定义选择和提示。参数：目录、标签。返回：无。异常：断言失败。"""
    manifest = tmp_path / "prompts/manifests/research.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"tool_selection": {"tool_tags_any": tags}, "model": "custom"}))
    prompt = tmp_path / "prompts/scenes/research.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("自定义提示")
    migrate_research_runtime_config(tmp_path)
    value = json.loads(manifest.read_text())
    assert value["tool_selection"]["tool_tags_any"] == (["research", "web", "fins"] if "ingestion" in tags else tags)
    assert value["model"] == "custom" and prompt.read_text() == "自定义提示"
    assert not migrate_research_runtime_config(tmp_path)


@pytest.mark.parametrize("file,body", [("toolset_registrars.json", "[]"), ("run.json", "[]"), ("run.json", '{"host_config":false}')])
def test_damaged_runtime_config_is_not_overwritten(tmp_path: Path, file: str, body: str) -> None:
    """不把损坏配置默默替换成默认值。参数：目录、文件、内容。返回：无。异常：断言失败。"""
    target = tmp_path / file
    target.write_text(body)
    with pytest.raises(ValueError):
        migrate_research_runtime_config(tmp_path)
    assert target.read_text() == body
