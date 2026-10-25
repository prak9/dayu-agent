"""Telegram 白名单配置、无副作用预检和持锁入口验证。"""

import asyncio
import json
from pathlib import Path
import runpy

import httpx
import pytest
from pytest_mock import MockerFixture

from alpha.contracts.env_keys import ALPHA_TELEGRAM_BOT_TOKEN_ENV
from alpha.telegram.client import TelegramClient
from alpha.telegram.main import _run, load_allowed_users, main
from alpha.workspace_paths import build_telegram_database_path
from tests.telegram.fakes import TelegramServer


def test_allowed_users_require_explicit_positive_ids(tmp_path: Path) -> None:
    """白名单不隐式接受所有人。参数：目录。返回：无。异常：断言失败。"""
    with pytest.raises(ValueError, match="明确配置"):
        load_allowed_users(tmp_path, None, [])
    config = tmp_path / "custom"
    config.mkdir()
    path = config / "telegram.json"
    path.write_text(json.dumps({"allowed_user_ids": [42, 42]}))
    assert load_allowed_users(tmp_path, config, []) == frozenset({42})
    assert load_allowed_users(tmp_path, config, [43]) == frozenset({43})
    for invalid in ({"allowed_user_ids": "42"}, {"allowed_user_ids": [True]}, {"allowed_user_ids": [-1]}):
        path.write_text(json.dumps(invalid))
        with pytest.raises(ValueError):
            load_allowed_users(tmp_path, config, [])


def test_cli_check_does_not_create_business_state_and_run_assembles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """预检只读，实际运行装配当前 schema。参数：目录、环境、mock。返回：无。异常：断言失败。"""
    first = TelegramClient("123:secret", transport=httpx.MockTransport(TelegramServer()))
    second = TelegramClient("123:secret", transport=httpx.MockTransport(TelegramServer()))
    mocker.patch("alpha.telegram.main.TelegramClient", side_effect=[first, second])
    mocker.patch("alpha.telegram.main.TelegramDaemon.run", return_value=None)
    monkeypatch.setenv(ALPHA_TELEGRAM_BOT_TOKEN_ENV, "123:secret")
    monkeypatch.setattr("sys.argv", ["alpha-telegram", "--base", str(tmp_path), "--user", "42", "--check"])
    assert main() == 0 and not build_telegram_database_path(tmp_path).exists()
    monkeypatch.setattr("sys.argv", ["alpha-telegram", "--base", str(tmp_path), "--user", "42"])
    assert main() == 0 and build_telegram_database_path(tmp_path).is_file()


def test_missing_token_and_module_help(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """缺少 token 明确失败，模块帮助无需密钥。参数：目录、环境。返回：无。异常：断言失败。"""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.delenv(ALPHA_TELEGRAM_BOT_TOKEN_ENV, raising=False)
    with pytest.raises(ValueError, match="ALPHA_TELEGRAM_BOT_TOKEN"):
        asyncio.run(_run(tmp_path, None, frozenset({42}), check_only=True))
    monkeypatch.setattr("sys.argv", ["alpha-telegram", "--help"])
    with pytest.raises(SystemExit) as result:
        runpy.run_module("alpha.telegram", run_name="__main__")
    assert result.value.code == 0
