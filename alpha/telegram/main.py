"""alpha-telegram 前台入口：加载私聊白名单，预检后持锁运行。"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import cast

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.env_keys import ALPHA_TELEGRAM_BOT_TOKEN_ENV
from alpha.startup.codex_credentials import load_notion_token, load_telegram_token
from alpha.console_output import configure_standard_streams_for_console_output
from alpha.process_lifecycle.exit_codes import EXIT_CODE_SIGINT
from alpha.services.research_preparation import prepare_research_channels, prepare_research_service
from alpha.services.research_material_service import prepare_research_materials
from alpha.services.publication_preparation import PublicationConnection, load_notion_parent_id, prepare_publication_service
from alpha.services.publication_worker import PublicationWorker
from alpha.integrations.notion.client import NotionClient
from alpha.services.reply_delivery_service import ReplyDeliveryService
from alpha.services.startup_preparation import prepare_host_runtime_dependencies
from alpha.state_dir_lock import StateDirSingleInstanceLock
from alpha.telegram.actions import SQLiteTelegramActions
from alpha.telegram.cards import TelegramCards
from alpha.telegram.client import TelegramClient
from alpha.telegram.controller import TelegramController
from alpha.telegram.daemon import TelegramDaemon
from alpha.telegram.database import TelegramDatabase
from alpha.telegram.deliveries import SQLiteTelegramDeliveries
from alpha.telegram.inbox import SQLiteTelegramInbox
from alpha.telegram.report_delivery import TelegramReportDelivery
from alpha.telegram.research_topics import TelegramResearchTopics
from alpha.telegram.sender import TelegramSender
from alpha.telegram.topics import SQLiteTelegramTopics
from alpha.telegram.types import require_int, require_map
from alpha.workspace_paths import build_telegram_database_path, build_telegram_state_dir

_BOT_LOCK_PREFIX = "bot-"
_LOCK_NAME = "Telegram Bot 接收实例"
_CONFIG_NAME = "telegram.json"


def load_allowed_users(workspace: Path, config_root: Path | None, explicit_users: list[int]) -> frozenset[int]:
    """读取显式白名单。参数：工作区、配置覆盖、命令行用户。返回：非空正整数集合。异常：缺失或非法授权。"""
    users = explicit_users
    if not users:
        config = (config_root or workspace / "config") / _CONFIG_NAME
        if config.exists():
            payload = require_map(cast(JsonValue, json.loads(config.read_text(encoding="utf-8"))))
            raw_users = payload.get("allowed_user_ids")
            if not isinstance(raw_users, list):
                raise ValueError("telegram.json.allowed_user_ids 必须是整数数组")
            users = [require_int(item) for item in raw_users]
    if not users or any(user <= 0 for user in users):
        raise ValueError("请在 telegram.json.allowed_user_ids 或 --user 中明确配置允许的 Telegram user ID")
    return frozenset(users)


def build_daemon(workspace: Path, config: Path | None, client: TelegramClient, bot_id: int, users: frozenset[int], *, publication_connection: PublicationConnection | None = None) -> TelegramDaemon:
    """装配渠道入口。参数：工作区、配置、已预检客户端、Bot、白名单、可选发布连接。返回：daemon。异常：业务或渠道初始化失败。"""
    dependencies = prepare_host_runtime_dependencies(workspace_root=workspace, config_root=config, execution_options=None,
                                                     runtime_label="telegram", log_module="TELEGRAM")
    research = prepare_research_service(workspace, dependencies)
    database = TelegramDatabase(build_telegram_database_path(workspace))
    channels = prepare_research_channels(workspace, research)
    topics = TelegramResearchTopics(bot_id, research, channels, SQLiteTelegramTopics(database, bot_id), client)
    cards = TelegramCards(research, SQLiteTelegramActions(database, bot_id))
    sender = TelegramSender(client, SQLiteTelegramDeliveries(database, bot_id))
    reports = TelegramReportDelivery(bot_id, research, ReplyDeliveryService(dependencies.host), cards, sender)
    publication = prepare_publication_service(workspace, dependencies, publication_connection) if publication_connection is not None else None
    return TelegramDaemon(TelegramController(users, research, topics, cards, sender, reports, publication, prepare_research_materials(workspace, research)), SQLiteTelegramInbox(database, bot_id),
                           PublicationWorker(publication) if publication is not None else None)


async def _run(workspace: Path, config: Path | None, users: frozenset[int], *, check_only: bool) -> None:
    """预检并持锁运行。参数：工作区、配置、用户、仅预检。返回：无。异常：密钥、预检、实例冲突或运行错误。"""
    token = load_telegram_token()
    if not token:
        raise ValueError(f"未找到 Telegram 凭据；可配置 Codex 用户目录 alpha/credentials.toml 的 telegram.bot_token，或显式覆盖 {ALPHA_TELEGRAM_BOT_TOKEN_ENV}")
    client = TelegramClient(token)
    notion_client: NotionClient | None = None
    try:
        bot_id = await client.preflight()
        if check_only:
            print(f"Telegram 预检通过：bot_id={bot_id}，已配置 {len(users)} 个允许用户")
            return
        lock = StateDirSingleInstanceLock(state_dir=build_telegram_state_dir(workspace), lock_file_name=f"{_BOT_LOCK_PREFIX}{bot_id}.lock", lock_name=_LOCK_NAME)
        lock.acquire()
        try:
            notion_token = load_notion_token()
            connection: PublicationConnection | None = None
            if notion_token:
                notion_client = NotionClient(notion_token)
                connection = PublicationConnection(notion_client, load_notion_parent_id(workspace, config))
            await build_daemon(workspace, config, client, bot_id, users, publication_connection=connection).run()
        finally:
            lock.release()
    finally:
        if notion_client is not None:
            notion_client.close()
        await client.aclose()


def main() -> int:
    """解析运行参数。参数：无。返回：退出码。异常：参数和初始化错误向终端明确报告。"""
    configure_standard_streams_for_console_output()
    parser = argparse.ArgumentParser(prog="alpha-telegram", description="alpha Telegram 私聊多研究入口")
    parser.add_argument("--base", default="./workspace", help="已初始化的工作区")
    parser.add_argument("--config", default=None, help="配置目录覆盖")
    parser.add_argument("--user", action="append", type=int, default=[], help="允许的 user ID，可重复；覆盖配置文件白名单")
    parser.add_argument("--check", action="store_true", help="只验证 Bot、话题模式和 webhook 条件")
    args = parser.parse_args()
    workspace = Path(str(args.base)).expanduser().resolve()
    config = Path(str(args.config)).expanduser().resolve() if args.config else None
    users = load_allowed_users(workspace, config, list(args.user))
    try:
        asyncio.run(_run(workspace, config, users, check_only=bool(args.check)))
    except KeyboardInterrupt:
        return EXIT_CODE_SIGINT
    return 0
