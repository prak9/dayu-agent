"""本地连接凭据解析不会读取登录密钥或复制其他连接的秘密。"""

from pathlib import Path

import pytest

from alpha.startup.codex_credentials import codex_config_path, load_codex_mcp_names, load_notion_token, load_telegram_token


def test_saved_connections_and_explicit_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """服务各自取自己的密钥，显式覆盖优先且文件不变。参数：目录、环境。返回：无。异常：断言失败。"""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.delenv("ALPHA_NOTION_TOKEN", raising=False)
    monkeypatch.delenv("ALPHA_TELEGRAM_BOT_TOKEN", raising=False)
    content = '[mcp_servers.notion.env]\nNOTION_TOKEN="notion-saved"\n[mcp_servers.telegram.env]\nTELEGRAM_BOT_TOKEN="123:saved"\n'
    path = tmp_path / "config.toml"
    path.write_text(content)
    (tmp_path / "auth.json").write_text("not read as a Notion token")
    assert codex_config_path() == path
    assert load_codex_mcp_names() == ("notion", "telegram")
    assert load_notion_token() == "notion-saved" and load_telegram_token() == "123:saved"
    monkeypatch.setenv("ALPHA_NOTION_TOKEN", "explicit")
    assert load_notion_token() == "explicit" and path.read_text() == content


def test_environment_references_missing_connection_and_bad_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """明确环境引用可解析，未配置不猜测，损坏错误不含原文。参数：目录、环境。返回：无。异常：断言失败。"""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.delenv("ALPHA_NOTION_TOKEN", raising=False)
    monkeypatch.delenv("ALPHA_TELEGRAM_BOT_TOKEN", raising=False)
    assert load_notion_token() is None and load_telegram_token() is None
    path = tmp_path / "config.toml"
    path.write_text('[mcp_servers.notion.env]\nNOTION_TOKEN="${SAVED_NOTION}"\n')
    monkeypatch.setenv("SAVED_NOTION", "referenced")
    assert load_notion_token() == "referenced"
    monkeypatch.delenv("SAVED_NOTION")
    assert load_notion_token() is None
    path.write_text('secret-token [broken')
    with pytest.raises(ValueError) as error:
        load_notion_token()
    assert "secret-token" not in str(error.value)
    path.write_text('mcp_servers="wrong"')
    with pytest.raises(ValueError):
        load_notion_token()


def test_local_telegram_credentials_and_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """独立凭据不创建假 MCP 服务，已有服务与显式覆盖优先。参数：目录、环境。返回：无。异常：断言失败。"""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.delenv("ALPHA_TELEGRAM_BOT_TOKEN", raising=False)
    path = tmp_path / "alpha" / "credentials.toml"
    path.parent.mkdir()
    content = '[telegram]\nbot_token=" 123:local "\n'
    path.write_text(content)
    assert load_telegram_token() == "123:local"
    assert load_codex_mcp_names() == ()
    (tmp_path / "config.toml").write_text('[mcp_servers.telegram.env]\nBOT_TOKEN="123:mcp"\n')
    assert load_telegram_token() == "123:mcp"
    monkeypatch.setenv("ALPHA_TELEGRAM_BOT_TOKEN", "123:explicit")
    assert load_telegram_token() == "123:explicit"
    assert path.read_text() == content


@pytest.mark.parametrize("content", ['secret-token [broken', 'telegram="wrong"', '[telegram]\nbot_token=123'])
def test_local_telegram_credentials_reject_bad_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str) -> None:
    """损坏文件显式报错且不泄漏内容。参数：目录、环境、配置。返回：无。异常：断言失败。"""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.delenv("ALPHA_TELEGRAM_BOT_TOKEN", raising=False)
    path = tmp_path / "alpha" / "credentials.toml"
    path.parent.mkdir()
    path.write_text(content)
    with pytest.raises(ValueError) as error:
        load_telegram_token()
    assert "secret-token" not in str(error.value)
