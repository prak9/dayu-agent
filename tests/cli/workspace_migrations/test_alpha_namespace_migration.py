"""alpha 命名升级的真实文件与 SQLite 回归测试。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from typing import Callable

import pytest

from alpha.cli.workspace_migrations.alpha_namespace import migrate_alpha_namespace
from alpha.state_dir_lock import StateDirSingleInstanceLock


def _legacy_workspace(root: Path, *, owner_pid: int = 0) -> Path:
    """创建带旧状态和恢复快照的测试工作区。

    Args:
        root: 测试工作区。
        owner_pid: 活跃 run 的进程 ID，零表示不创建活跃 run。

    Returns:
        旧 Host 数据库路径。

    Raises:
        OSError: 写文件失败。
        sqlite3.Error: 构造数据库失败。
    """

    old_root = root / ".dayu"
    (old_root / "host").mkdir(parents=True)
    (old_root / "session").mkdir()
    (old_root / "session" / "history.json").write_text(
        '{"user_text":"请分析 dayu 这个名称"}', encoding="utf-8"
    )
    config = root / "config"
    config.mkdir()
    (config / "toolset_registrars.json").write_text(
        '{"fins":"dayu.fins.toolset_registrars.register_fins_read_toolset"}', encoding="utf-8"
    )
    database = old_root / "host" / "dayu_host.db"
    with sqlite3.connect(database) as conn:
        conn.executescript(
            "CREATE TABLE runs (run_id TEXT, state TEXT, owner_pid INTEGER);"
            "CREATE TABLE pending_conversation_turns (pending_turn_id TEXT, resume_source_json TEXT);"
        )
        snapshot = {
            "preparation_spec": {"execution_permissions": {"doc": {
                "allowed_read_paths": [str(old_root / "session")],
            }}},
            "message_inputs": {"user_message": "dayu.fins 是用户提供的历史文本"},
        }
        conn.execute("INSERT INTO pending_conversation_turns VALUES (?, ?)", ("turn1", json.dumps(snapshot)))
        if owner_pid:
            conn.execute("INSERT INTO runs VALUES (?, ?, ?)", ("run1", "running", owner_pid))
    return database


def test_upgrade_preserves_history_and_rewrites_only_runtime_references(tmp_path: Path) -> None:
    """验证数据库、配置及历史内容在升级后保持正确。

    Args:
        tmp_path: pytest 临时工作区。

    Returns:
        无。

    Raises:
        AssertionError: 升级丢数据或改写用户文本。
    """

    _legacy_workspace(tmp_path)
    assert migrate_alpha_namespace(tmp_path) is True
    database = tmp_path / ".alpha" / "host" / "alpha_host.db"
    with sqlite3.connect(database) as conn:
        row = conn.execute("SELECT resume_source_json FROM pending_conversation_turns").fetchone()
    assert row is not None
    snapshot = json.loads(row[0])
    paths = snapshot["preparation_spec"]["execution_permissions"]["doc"]["allowed_read_paths"]
    assert paths == [str(tmp_path / ".alpha" / "session")]
    assert snapshot["message_inputs"]["user_message"] == "dayu.fins 是用户提供的历史文本"
    assert "请分析 dayu" in (tmp_path / ".alpha" / "session" / "history.json").read_text()
    registrars = json.loads((tmp_path / "config" / "toolset_registrars.json").read_text())
    assert registrars["fins"] == "alpha.fins.toolset_registrars.register_fins_read_toolset"
    assert not (tmp_path / ".dayu").exists()
    assert (tmp_path / ".alpha_namespace_migration" / "original" / "host" / "dayu_host.db").exists()
    assert migrate_alpha_namespace(tmp_path) is False


def test_upgrade_rejects_live_runs_without_moving_data(tmp_path: Path) -> None:
    """验证旧进程仍活跃时升级在写入前拒绝。

    Args:
        tmp_path: pytest 临时工作区。

    Returns:
        无。

    Raises:
        AssertionError: 活跃进程未被阻止或旧目录被修改。
    """

    database = _legacy_workspace(tmp_path, owner_pid=os.getpid())
    with pytest.raises(RuntimeError, match="活跃"):
        migrate_alpha_namespace(tmp_path)
    assert database.exists()
    assert not (tmp_path / ".alpha").exists()


def test_upgrade_rejects_conflicting_namespace(tmp_path: Path) -> None:
    """验证两套状态目录并存时不猜测应覆盖哪一套。

    Args:
        tmp_path: pytest 临时工作区。

    Returns:
        无。

    Raises:
        AssertionError: 冲突未报错或旧数据被覆盖。
    """

    database = _legacy_workspace(tmp_path)
    (tmp_path / ".alpha").mkdir()
    with pytest.raises(RuntimeError, match="冲突"):
        migrate_alpha_namespace(tmp_path)
    assert database.exists()


def test_upgrade_respects_legacy_init_lock(tmp_path: Path) -> None:
    """验证另一个旧版 init 持锁时不能迁移。

    Args:
        tmp_path: pytest 临时工作区。

    Returns:
        无。

    Raises:
        AssertionError: 跨版本初始化锁未生效。
    """

    database = _legacy_workspace(tmp_path)
    lock = StateDirSingleInstanceLock(
        state_dir=tmp_path, lock_file_name=".dayu_init.lock", lock_name="legacy init"
    )
    lock.acquire()
    try:
        with pytest.raises(RuntimeError):
            migrate_alpha_namespace(tmp_path)
    finally:
        lock.release()
    assert database.exists()


def test_new_workspace_is_noop(tmp_path: Path) -> None:
    """验证全新工作区无需读取或创建旧目录。

    Args:
        tmp_path: pytest 临时工作区。

    Returns:
        无。

    Raises:
        AssertionError: 新工作区产生无意义迁移。
    """

    assert migrate_alpha_namespace(tmp_path) is False
    assert not (tmp_path / ".dayu").exists()


@pytest.mark.parametrize("phase", ["legacy_saved", "namespace_installed", "completed"])
def test_upgrade_recovers_after_namespace_effect_before_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str,
) -> None:
    """验证目录已移动但阶段回写失败时可恢复。

    Args:
        tmp_path: 临时工作区。
        monkeypatch: 故障注入工具。
        phase: 需要中断的阶段。
    Returns:
        无。
    Raises:
        AssertionError: 恢复未收敛或数据遗失。
    """
    from functools import partial
    from alpha.cli.workspace_migrations import alpha_namespace as migration

    _legacy_workspace(tmp_path)
    with monkeypatch.context() as patcher:
        patcher.setattr(migration, "_write_phase", partial(_fail_phase, failing=phase, original=migration._write_phase))
        with pytest.raises(OSError, match="injected"):
            migrate_alpha_namespace(tmp_path)
    assert migrate_alpha_namespace(tmp_path) is True
    assert migrate_alpha_namespace(tmp_path) is False
    assert (tmp_path / ".alpha" / "host" / "alpha_host.db").exists()


def _fail_phase(directory: Path, phase: str, *, failing: str, original: "Callable[[Path, str], None]") -> None:
    """在指定阶段模拟日志落盘故障。

    Args:
        directory: 日志目录。
        phase: 当前阶段。
        failing: 故障阶段。
        original: 原始写入函数。
    Returns:
        无。
    Raises:
        OSError: 命中注入阶段。
    """
    if phase == failing:
        raise OSError("injected journal failure")
    original(directory, phase)


@pytest.mark.parametrize("payload", ['[]', '{"phase":null}', '{"phase":"unexpected"}'])
def test_upgrade_rejects_damaged_journal(tmp_path: Path, payload: str) -> None:
    """拒绝无法解释的日志。参数：临时目录及日志文本。返回：无。异常：断言失败。"""
    directory = tmp_path / ".alpha_namespace_migration"
    directory.mkdir()
    (directory / "journal.json").write_text(payload)
    with pytest.raises(ValueError):
        migrate_alpha_namespace(tmp_path)


def test_configuration_only_upgrade_is_idempotent(tmp_path: Path) -> None:
    """仅有旧配置时也可升级。参数：临时目录。返回：无。异常：断言失败。"""
    config = tmp_path / "config"
    config.mkdir()
    (config / "toolset_registrars.json").write_text('{"fins":"dayu.fins.registrar"}')
    (config / "runtime.json").write_text(json.dumps({
        "module": "dayu.engine.runner", "api_key_name": "DAYU_CUSTOM_KEY",
        "allowed_read_paths": [".dayu/session"], "user_text": "dayu.engine 保持原文",
    }))
    assert migrate_alpha_namespace(tmp_path) is True
    payload = json.loads((config / "runtime.json").read_text())
    assert payload["module"] == "alpha.engine.runner"
    assert payload["api_key_name"] == "ALPHA_CUSTOM_KEY"
    assert payload["allowed_read_paths"] == [".alpha/session"]
    assert payload["user_text"] == "dayu.engine 保持原文"
    assert migrate_alpha_namespace(tmp_path) is False


def test_upgrade_rejects_live_channel(tmp_path: Path) -> None:
    """渠道仍运行时拒绝升级。参数：临时目录。返回：无。异常：断言失败。"""
    _legacy_workspace(tmp_path)
    directory = tmp_path / ".dayu" / "wechat-default"
    directory.mkdir()
    (directory / ".daemon.lock").write_text(str(os.getpid()))
    with pytest.raises(RuntimeError, match="活跃"):
        migrate_alpha_namespace(tmp_path)


def test_upgrade_invalid_snapshot_keeps_original(tmp_path: Path) -> None:
    """快照损坏不能半覆盖原件。参数：临时目录。返回：无。异常：断言失败。"""
    database = _legacy_workspace(tmp_path)
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE pending_conversation_turns SET resume_source_json='invalid'")
    with pytest.raises(ValueError):
        migrate_alpha_namespace(tmp_path)
    assert database.exists()
    assert not (tmp_path / ".alpha").exists()


def test_upgrade_copies_uncheckpointed_wal(tmp_path: Path) -> None:
    """一致性备份包含尚在 WAL 的提交。参数：临时目录。返回：无。异常：断言失败。"""
    database = _legacy_workspace(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE marker (value TEXT)")
        connection.execute("INSERT INTO marker VALUES ('preserved')")
        connection.commit()
        assert Path(str(database) + "-wal").exists()
        assert migrate_alpha_namespace(tmp_path) is True
    with sqlite3.connect(tmp_path / ".alpha" / "host" / "alpha_host.db") as migrated:
        assert migrated.execute("SELECT value FROM marker").fetchone() == ("preserved",)


def test_upgrade_preserves_user_change_during_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """中断期间用户改配置时不覆盖。参数：临时目录和故障工具。返回：无。异常：断言失败。"""
    from functools import partial
    from alpha.cli.workspace_migrations import alpha_namespace as migration

    _legacy_workspace(tmp_path)
    with monkeypatch.context() as patcher:
        patcher.setattr(migration, "_write_phase", partial(_fail_phase, failing="completed", original=migration._write_phase))
        with pytest.raises(OSError):
            migrate_alpha_namespace(tmp_path)
    target = tmp_path / "config" / "toolset_registrars.json"
    target.write_text('{"fins":"custom.user.registrar"}')
    with pytest.raises(RuntimeError, match="冲突"):
        migrate_alpha_namespace(tmp_path)
    assert "custom.user.registrar" in target.read_text()


def test_completed_upgrade_rejects_reappearing_legacy_directory(tmp_path: Path) -> None:
    """旧目录重新出现时拒绝猜测。参数：临时目录。返回：无。异常：断言失败。"""
    _legacy_workspace(tmp_path)
    migrate_alpha_namespace(tmp_path)
    (tmp_path / ".dayu").mkdir()
    with pytest.raises(RuntimeError, match="冲突"):
        migrate_alpha_namespace(tmp_path)


def test_upgrade_without_host_database_preserves_channel_files(tmp_path: Path) -> None:
    """无 Host 库仍保留渠道状态。参数：临时目录。返回：无。异常：断言失败。"""
    legacy = tmp_path / ".dayu"
    legacy.mkdir()
    (legacy / "channel.json").write_text('{"marker":"keep"}')
    assert migrate_alpha_namespace(tmp_path) is True
    assert (tmp_path / ".alpha" / "channel.json").read_text() == '{"marker":"keep"}'


def test_upgrade_database_without_execution_tables(tmp_path: Path) -> None:
    """仅缓存表的旧库仍可无损备份。参数：临时目录。返回：无。异常：断言失败。"""
    host_dir = tmp_path / ".dayu" / "host"
    host_dir.mkdir(parents=True)
    with sqlite3.connect(host_dir / "dayu_host.db") as conn:
        conn.execute("CREATE TABLE custom_cache (value INTEGER)")
        conn.execute("INSERT INTO custom_cache VALUES (7)")
    assert migrate_alpha_namespace(tmp_path) is True
    with sqlite3.connect(tmp_path / ".alpha" / "host" / "alpha_host.db") as conn:
        assert conn.execute("SELECT value FROM custom_cache").fetchone() == (7,)


def test_upgrade_dead_owner_and_empty_snapshot(tmp_path: Path) -> None:
    """死进程遗留记录可留待 Host 调和。参数：临时目录。返回：无。异常：断言失败。"""
    database = _legacy_workspace(tmp_path, owner_pid=2_000_000_000)
    with sqlite3.connect(database) as conn:
        conn.execute("INSERT INTO pending_conversation_turns VALUES ('empty', '')")
    assert migrate_alpha_namespace(tmp_path) is True
    with sqlite3.connect(tmp_path / ".alpha" / "host" / "alpha_host.db") as conn:
        assert conn.execute("SELECT count(*) FROM runs").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM pending_conversation_turns").fetchone() == (2,)


def test_upgrade_refuses_unrecognizable_live_schema(tmp_path: Path) -> None:
    """无法确认 owner 的旧库拒绝迁移。参数：临时目录。返回：无。异常：断言失败。"""
    database = _legacy_workspace(tmp_path)
    with sqlite3.connect(database) as conn:
        conn.execute("DROP TABLE runs")
        conn.execute("CREATE TABLE runs (state TEXT)")
    with pytest.raises(RuntimeError, match="无法确认"):
        migrate_alpha_namespace(tmp_path)
    assert database.exists()


def test_upgrade_refuses_invalid_registrar_shape(tmp_path: Path) -> None:
    """损坏旧 registrar 不被静默丢弃。参数：临时目录。返回：无。异常：断言失败。"""
    _legacy_workspace(tmp_path)
    (tmp_path / "config" / "toolset_registrars.json").write_text('["dayu.fins.registry"]')
    with pytest.raises(ValueError, match="字符串映射"):
        migrate_alpha_namespace(tmp_path)
    assert (tmp_path / ".dayu").exists()


def test_configuration_only_upgrade_releases_completed_update_plan(tmp_path: Path) -> None:
    """升级后用户自定义不与旧计划冲突。参数：临时目录。返回：无。异常：断言失败。"""
    config = tmp_path / "config"
    config.mkdir()
    target = config / "toolset_registrars.json"
    target.write_text('{"fins":"dayu.fins.registrar"}')
    assert migrate_alpha_namespace(tmp_path) is True
    target.write_text('{"fins":"custom.user.registrar"}')
    assert migrate_alpha_namespace(tmp_path) is False
    assert "custom.user.registrar" in target.read_text()


def test_configuration_only_upgrade_respects_legacy_init_lock(tmp_path: Path) -> None:
    """旧 init 尚未建状态目录时也需互斥。参数：临时目录。返回：无。异常：断言失败。"""
    config = tmp_path / "config"
    config.mkdir()
    target = config / "toolset_registrars.json"
    original = '{"fins":"dayu.fins.registrar"}'
    target.write_text(original)
    lock = StateDirSingleInstanceLock(
        state_dir=tmp_path, lock_file_name=".dayu_init.lock", lock_name="legacy init"
    )
    lock.acquire()
    try:
        with pytest.raises(RuntimeError):
            migrate_alpha_namespace(tmp_path)
    finally:
        lock.release()
    assert target.read_text() == original
