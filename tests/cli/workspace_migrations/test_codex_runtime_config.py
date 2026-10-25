"""本地 Codex 明确配置和无凭据复制的工作区升级测试。"""

import json
from pathlib import Path

import pytest

from alpha.cli.arg_parsing import _create_parser
from alpha.cli.commands.init import run_init_command
from alpha.cli.workspace_migrations.codex_runtime_config import configure_codex_defaults, migrate_codex_runtime_config


def test_codex_init_skips_all_key_and_profile_prompts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--codex 初始化不要求模型 Key 或写 shell profile。参数：目录、环境。返回：无。异常：断言失败。"""
    def fail_input(prompt: str) -> str:
        """禁止隐式交互。参数：提示。返回：不可达。异常：断言。"""
        raise AssertionError(prompt)

    monkeypatch.setattr("builtins.input", fail_input)
    args = _create_parser().parse_args(["init", "--base", str(tmp_path), "--codex"])
    assert run_init_command(args) == 0
    models = json.loads((tmp_path / "config/llm_models.json").read_text())
    assert models["codex-local"]["runner_type"] == "codex"
    assert "headers" not in models["codex-local"]
    for path in (tmp_path / "config/prompts/manifests").glob("*.json"):
        manifest = json.loads(path.read_text())
        if isinstance(manifest.get("model"), dict):
            assert manifest["model"]["default_name"] == "codex-local"
    assert run_init_command(args) == 0
    assert configure_codex_defaults(tmp_path / "config") == 0


def test_codex_catalog_migration_preserves_custom_entry_and_defaults(tmp_path: Path) -> None:
    """安装定义与明确选择分开，不覆盖用户自定义配置。参数：目录。返回：无。异常：断言失败。"""
    assert not migrate_codex_runtime_config(tmp_path)
    path = tmp_path / "llm_models.json"
    path.write_text('{"custom":{"runner_type":"openai_compatible"}}')
    assert migrate_codex_runtime_config(tmp_path)
    payload = json.loads(path.read_text())
    assert "custom" in payload and "codex-local" in payload
    assert not migrate_codex_runtime_config(tmp_path)
    payload["codex-local"]["executable"] = "custom-codex"
    path.write_text(json.dumps(payload))
    assert not migrate_codex_runtime_config(tmp_path)
    assert json.loads(path.read_text())["codex-local"]["executable"] == "custom-codex"
    path.write_text('[]')
    with pytest.raises(ValueError):
        migrate_codex_runtime_config(tmp_path)
