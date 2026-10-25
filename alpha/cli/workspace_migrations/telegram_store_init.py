"""通过显式 init 插件创建 Telegram 当前渠道 schema。"""

from pathlib import Path

from alpha.telegram.database import TelegramDatabase
from alpha.workspace_paths import build_telegram_database_path


def migrate_telegram_store_init(base_dir: Path) -> bool:
    """初始化渠道库。参数：工作区。返回：是否新建。异常：未知 schema 或数据库错误。"""
    path = build_telegram_database_path(base_dir)
    created = not path.exists()
    TelegramDatabase(path)
    return created
