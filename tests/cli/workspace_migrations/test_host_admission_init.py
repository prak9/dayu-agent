"""Host 持久受理表进入 init 的一次性升级测试。"""

import sqlite3
from pathlib import Path

from alpha.cli.workspace_migrations.host_admission_init import migrate_host_admission_init
from alpha.workspace_paths import build_host_store_default_path


def test_missing_host_database_is_not_created(tmp_path: Path) -> None:
    """无 Host 库时保留首次启动建库职责。参数：目录。返回：无。异常：断言失败。"""
    assert not migrate_host_admission_init(tmp_path)
    assert not build_host_store_default_path(tmp_path).exists()


def test_explicit_upgrade_adds_tables_and_preserves_runs(tmp_path: Path) -> None:
    """旧库升级仅新增受理表。参数：目录。返回：无。异常：断言失败。"""
    path = build_host_store_default_path(tmp_path)
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE runs(run_id TEXT PRIMARY KEY, state TEXT)")
        conn.execute("INSERT INTO runs VALUES('historical','succeeded')")
    assert migrate_host_admission_init(tmp_path)
    assert not migrate_host_admission_init(tmp_path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM runs").fetchall() == [("historical", "succeeded")]
        assert conn.execute("SELECT COUNT(*) FROM agent_admissions").fetchone()[0] == 0
