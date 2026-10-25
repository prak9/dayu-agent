"""读取 Codex 的显式渠道配置和用户目录内的 alpha 凭据；不解析 ChatGPT 登录令牌。"""

import os
from pathlib import Path
import re
import tomllib

from alpha.contracts.env_keys import ALPHA_NOTION_TOKEN_ENV, ALPHA_TELEGRAM_BOT_TOKEN_ENV

_CODEX_HOME_ENV = "CODEX_HOME"
_CONFIG_FILENAME = "config.toml"
_ENV_REFERENCE = re.compile(r"(?:\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\{\{([A-Za-z_][A-Za-z0-9_]*)\}\})")
_NOTION_KEYS = ("NOTION_TOKEN", "NOTION_API_KEY")
_TELEGRAM_KEYS = ("TELEGRAM_BOT_TOKEN", "BOT_TOKEN", "TELEGRAM_TOKEN")
_ALPHA_CREDENTIALS_PATH = Path("alpha") / "credentials.toml"


def codex_config_path() -> Path:
    """定位本地 Codex 配置。参数：无。返回：配置路径。异常：无。"""
    return Path(os.environ.get(_CODEX_HOME_ENV) or Path.home() / ".codex").expanduser() / _CONFIG_FILENAME


def load_codex_mcp_names() -> tuple[str, ...]:
    """只读取服务名称供研究运行器关闭旁路能力。参数：无。返回：名称。异常：配置损坏。"""
    return tuple(_servers())


def _servers() -> dict[str, dict[str, str | dict[str, str]]]:
    """投影凭据所需配置字段。参数：无。返回：服务及字符串环境变量。异常：TOML 损坏。"""
    path = codex_config_path()
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as stream:
            parsed = tomllib.load(stream)
    except tomllib.TOMLDecodeError:
        raise ValueError("Codex config.toml 格式损坏，请检查本地配置") from None
    result: dict[str, dict[str, str | dict[str, str]]] = {}
    servers = parsed.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ValueError("Codex mcp_servers 必须为配置表")
    for name, server in servers.items():
        if not isinstance(server, dict):
            continue
        raw_env = server.get("env", {})
        environment = {key: value for key, value in raw_env.items() if isinstance(value, str)} if isinstance(raw_env, dict) else {}
        result[name] = {"env": environment}
    return result


def _saved_token(server_name: str, keys: tuple[str, ...]) -> str | None:
    """读取明确服务的已存凭据。参数：服务、支持的环境键。返回：密钥或空。异常：配置损坏。"""
    environment = _servers().get(server_name, {}).get("env", {})
    if not isinstance(environment, dict):
        return None
    for key in keys:
        value = environment.get(key, "").strip()
        reference = _ENV_REFERENCE.fullmatch(value)
        if reference is not None:
            value = os.environ.get(reference.group(1) or reference.group(2), "").strip()
        if value:
            return value
    return None


def load_notion_token() -> str | None:
    """优先显式覆盖，否则复用 Codex Notion token。参数：无。返回：密钥或空。异常：本地配置损坏。"""
    return os.environ.get(ALPHA_NOTION_TOKEN_ENV, "").strip() or _saved_token("notion", _NOTION_KEYS)


def load_telegram_token() -> str | None:
    """读取显式覆盖、Codex 服务或本地凭据。参数：无。返回：密钥或空。异常：本地配置损坏。"""
    return os.environ.get(ALPHA_TELEGRAM_BOT_TOKEN_ENV, "").strip() or _saved_token("telegram", _TELEGRAM_KEYS) or _local_telegram_token()


def _local_telegram_token() -> str | None:
    """读取 alpha 专属凭据，避免注册不存在的 MCP 服务。参数：无。返回：密钥或空。异常：配置损坏。"""
    path = codex_config_path().parent / _ALPHA_CREDENTIALS_PATH
    if not path.is_file():
        return None
    try:
        with path.open("rb") as stream:
            parsed = tomllib.load(stream)
    except tomllib.TOMLDecodeError:
        raise ValueError("alpha credentials.toml 格式损坏，请检查本地配置") from None
    telegram = parsed.get("telegram", {})
    if not isinstance(telegram, dict):
        raise ValueError("alpha credentials.toml.telegram 必须为配置表")
    token = telegram.get("bot_token", "")
    if not isinstance(token, str):
        raise ValueError("alpha credentials.toml.telegram.bot_token 必须为字符串")
    return token.strip() or None
