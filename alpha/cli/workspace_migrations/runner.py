"""工作区迁移统一入口。

所有一次性修复脚本在这里串联。新增规则只需：

1. 在 ``alpha/cli/workspace_migrations/`` 下新建模块；
2. 暴露一个幂等函数；
3. 在 :func:`apply_all_workspace_migrations` 里按顺序调用并打印结果。

**不要**把规则写回 ``init.py``；也不要在此文件里做除"调度 + 汇报"以外的事。

失败语义：任一迁移内部抛错（``OSError`` / ``sqlite3.Error`` / ``json.JSONDecodeError``
等）将原样向上传播，由 ``alpha init`` 命令显式失败。运行 ``init`` 时调用方
负责持有 workspace advisory lock，确保不会有第二个 init 在同一目录上并发改动。
"""

from __future__ import annotations

from pathlib import Path

from alpha.cli.workspace_migrations.alpha_namespace import migrate_alpha_namespace
from alpha.cli.workspace_migrations.research_store_init import migrate_research_store_init
from alpha.cli.workspace_migrations.research_analysis_schema import migrate_research_analysis_schema
from alpha.cli.workspace_migrations.host_admission_init import migrate_host_admission_init
from alpha.cli.workspace_migrations.telegram_store_init import migrate_telegram_store_init
from alpha.cli.workspace_migrations.research_runtime_config import migrate_research_runtime_config
from alpha.cli.workspace_migrations.codex_runtime_config import migrate_codex_runtime_config
from alpha.cli.workspace_migrations.conversation_archive_init import (
    migrate_conversation_archive_init,
)
from alpha.cli.workspace_migrations.host_store_rename_concurrency_lane import (
    migrate_host_store_rename_concurrency_lane,
)
from alpha.cli.workspace_migrations.host_store_strip_max_output_tokens import (
    migrate_host_store_strip_max_output_tokens,
)
from alpha.cli.workspace_migrations.run_json_write_chapter_lane import (
    migrate_run_json_add_write_chapter_lane,
)
from alpha.cli.workspace_migrations.run_json_market_download_lanes import (
    migrate_run_json_add_market_download_lanes,
)
from alpha.workspace_paths import build_host_store_default_path


def apply_all_workspace_migrations(*, base_dir: Path, config_dir: Path) -> None:
    """按顺序执行全部已登记的工作区迁移，并把结果打印到 stdout。

    Args:
        base_dir: 工作区根目录，用于解析 Host SQLite 数据库位置。
        config_dir: 工作区配置目录（通常是 ``base_dir / "config"``）。

    Returns:
        无。

    Raises:
        OSError: 文件 I/O 失败时由迁移函数原样抛出。
        sqlite3.Error: SQLite 操作失败时由迁移函数原样抛出。
        json.JSONDecodeError: JSON 解析失败时由迁移函数原样抛出。
    """

    if migrate_alpha_namespace(base_dir):
        print("✓ 工作区迁移: alpha 命名升级完成，原始状态保留在 .alpha_namespace_migration")

    if migrate_research_analysis_schema(base_dir):
        print("✓ 工作区迁移: 研究财报要求已升级，原研究与版本保留")
    if migrate_research_store_init(base_dir):
        print("✓ 工作区迁移: 研究库与不可变产物目录已初始化")

    if migrate_telegram_store_init(base_dir):
        print("✓ 工作区迁移: Telegram 渠道库已初始化")

    if migrate_host_admission_init(base_dir):
        print("✓ 工作区迁移: Host 持久受理表已初始化")

    if migrate_research_runtime_config(config_dir):
        print("✓ 工作区迁移: 已补齐研究工具、发布并发及新增渠道配置，保留已有定制值")
    if migrate_codex_runtime_config(config_dir):
        print("✓ 工作区迁移: 已补齐本地 Codex 模型定义，保留已有默认模型")

    if migrate_run_json_add_write_chapter_lane(config_dir):
        print("✓ 工作区迁移: run.json 已补齐 host_config.lane.write_chapter=5")

    if migrate_run_json_add_market_download_lanes(config_dir):
        print("✓ 工作区迁移: run.json 已补齐 host_config.lane.cn_download=1 / hk_download=1")

    host_db_path = build_host_store_default_path(base_dir)
    rewritten = migrate_host_store_rename_concurrency_lane(host_db_path)
    if rewritten > 0:
        print(
            "✓ 工作区迁移: Host SQLite pending turn 快照 "
            f"concurrency_lane → business_concurrency_lane（共 {rewritten} 行）"
        )

    stripped = migrate_host_store_strip_max_output_tokens(host_db_path)
    if stripped > 0:
        print(
            "✓ 工作区迁移: Host SQLite pending turn 快照已剥离 "
            f"max_output_tokens 字段（共 {stripped} 行）"
        )

    archive_rewritten = migrate_conversation_archive_init(base_dir)
    if archive_rewritten > 0:
        print(
            "✓ 工作区迁移: 旧 conversation transcript 已升级为 "
            f"ConversationSessionArchive（共 {archive_rewritten} 个会话）"
        )
