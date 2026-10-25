"""将旧命名工作区一次性升级为 alpha，并保留可恢复的原始副本。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import cast

from alpha.contracts.agent_types import JsonValue
from alpha.process_liveness import OwnerIdentity, is_owner_identity_alive, is_pid_alive
from alpha.state_dir_lock import StateDirSingleInstanceLock

_LEGACY_ROOT = ".dayu"
_CURRENT_ROOT = ".alpha"
_LEGACY_DATABASE = "dayu_host.db"
_CURRENT_DATABASE = "alpha_host.db"
_MIGRATION_DIRECTORY = ".alpha_namespace_migration"
_JOURNAL = "journal.json"
_ORIGINAL = "original"
_PREPARED = "prepared"
_CONFIG_BACKUPS = "config-backups"
_CONFIG_UPDATES = "config-updates"
_PHASE_PREPARED = "prepared"
_PHASE_SAVED = "legacy_saved"
_PHASE_INSTALLED = "namespace_installed"
_PHASE_COMPLETED = "completed"
_ACTIVE_STATES = ("created", "queued", "running")
_LEGACY_INIT_LOCK = ".dayu_init.lock"
_DAEMON_LOCK = ".daemon.lock"
_DATABASE_TIMEOUT_SECONDS = 30.0
_PATH_FIELDS = frozenset({
    "path", "file_path", "allowed_paths", "allowed_read_paths", "allowed_write_paths",
    "workspace_dir", "output_dir", "host_store_path", "trace_dir", "storage_dir",
    "store_path", "playwright_storage_state_dir",
})
_IMPORT_FIELDS = frozenset({"module", "import_path", "registrar", "registrar_path"})
_TEXT_FIELDS = frozenset({
    "messages", "user_message", "user_text", "system_prompt", "reply_content", "question",
})
_LEGACY_REFERENCE_TOKENS = ("dayu.", ".dayu", "DAYU_", "dayu_host.db")


def _write_text_atomic(path: Path, text: str) -> None:
    """以同目录临时文件原子替换文本。

    Args:
        path: 目标路径。
        text: 完整文本。
    Returns:
        无。
    Raises:
        OSError: 创建目录、写入或替换失败。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".alpha-migration.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _write_phase(directory: Path, phase: str) -> None:
    """保存可重入升级阶段。

    Args:
        directory: 升级工作目录。
        phase: 已完成阶段。
    Returns:
        无。
    Raises:
        OSError: 日志保存失败。
    """
    _write_text_atomic(directory / _JOURNAL, json.dumps({"phase": phase}) + "\n")


def _read_phase(directory: Path) -> str | None:
    """读取升级阶段，不从目录是否存在推测成功。

    Args:
        directory: 升级工作目录。
    Returns:
        阶段名，尚无日志则为空。
    Raises:
        ValueError: 日志结构非法。
        OSError: 日志读取失败。
    """
    journal = directory / _JOURNAL
    if not journal.exists():
        return None
    payload = cast(JsonValue, json.loads(journal.read_text(encoding="utf-8")))
    if not isinstance(payload, dict) or not isinstance(payload.get("phase"), str):
        raise ValueError("alpha 升级日志损坏，请检查备份后恢复")
    phase = payload["phase"]
    assert isinstance(phase, str)
    if phase not in {_PHASE_PREPARED, _PHASE_SAVED, _PHASE_INSTALLED, _PHASE_COMPLETED}:
        raise ValueError("alpha 升级阶段无法识别，请检查备份后恢复")
    return phase


def _ensure_legacy_idle(old_root: Path) -> None:
    """拒绝仍有活跃执行或渠道进程的旧工作区。

    Args:
        old_root: 旧隐藏目录。
    Returns:
        无。
    Raises:
        RuntimeError: 检测到活跃进程或无法解释的锁。
        OSError: 读取锁失败。
        sqlite3.Error: 读取旧数据库失败。
    """
    for lock_path in old_root.rglob(_DAEMON_LOCK):
        owner = lock_path.read_text(encoding="utf-8").strip()
        if owner and (not owner.isdecimal() or is_pid_alive(int(owner))):
            raise RuntimeError(f"旧工作区仍有活跃渠道，请先停止: {lock_path}")
    database = old_root / "host" / _LEGACY_DATABASE
    if not database.exists():
        return
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=_DATABASE_TIMEOUT_SECONDS) as conn:
        conn.row_factory = sqlite3.Row
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'").fetchone() is None:
            return
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(runs)")}
        if not {"state", "owner_pid"}.issubset(columns):
            raise RuntimeError("旧 Host schema 无法确认活跃进程，请先检查数据库")
        rows = conn.execute("SELECT * FROM runs WHERE state IN (?, ?, ?)", _ACTIVE_STATES).fetchall()
        for row in rows:
            identity = OwnerIdentity(
                pid=int(row["owner_pid"]),
                process_start_time=(float(row["owner_process_start_time"])
                    if "owner_process_start_time" in columns and row["owner_process_start_time"] is not None else None),
                boot_id=(str(row["owner_boot_id"])
                    if "owner_boot_id" in columns and row["owner_boot_id"] is not None else None),
            )
            if identity.pid <= 0 or is_owner_identity_alive(identity):
                raise RuntimeError("旧工作区存在活跃 run，请先停止旧进程再执行 alpha init")


def _rewrite_runtime_value(value: JsonValue, field_name: str = "") -> JsonValue:
    """仅转换执行路径与导入字段，保留用户消息原文。

    Args:
        value: JSON 值。
        field_name: 当前语义字段名。
    Returns:
        转换后的 JSON 值。
    Raises:
        无。
    """
    if field_name in _TEXT_FIELDS:
        return value
    if isinstance(value, dict):
        return {key: _rewrite_runtime_value(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_runtime_value(item, field_name) for item in value]
    if isinstance(value, str):
        if field_name in _PATH_FIELDS:
            if value == _LEGACY_ROOT:
                return _CURRENT_ROOT
            rewritten = value.replace("/.dayu/", "/.alpha/").replace("\\.dayu\\", "\\.alpha\\")
            if rewritten.startswith(_LEGACY_ROOT + "/") or rewritten.startswith(_LEGACY_ROOT + "\\"):
                rewritten = _CURRENT_ROOT + rewritten[len(_LEGACY_ROOT):]
            if rewritten.endswith("/" + _LEGACY_ROOT) or rewritten.endswith("\\" + _LEGACY_ROOT):
                rewritten = rewritten[:-len(_LEGACY_ROOT)] + _CURRENT_ROOT
            return rewritten.replace(_LEGACY_DATABASE, _CURRENT_DATABASE)
        if field_name in _IMPORT_FIELDS and value.startswith("dayu."):
            return "alpha." + value.removeprefix("dayu.")
        if field_name == "api_key_name" and value.startswith("DAYU_"):
            return "ALPHA_" + value.removeprefix("DAYU_")
    return value


def _prepare_configuration_updates(base_dir: Path, directory: Path) -> None:
    """在修改任何原始配置前准备转换内容和备份。

    Args:
        base_dir: 工作区目录。
        directory: 升级工作目录。
    Returns:
        无。
    Raises:
        ValueError: JSON 或 registrar 配置损坏。
        OSError: 读取、备份或写入失败。
    """
    config_dir = base_dir / "config"
    for path in sorted(config_dir.rglob("*.json")) if config_dir.exists() else ():
        original = path.read_text(encoding="utf-8")
        # 迁移只解释旧命名引用；无关配置的错误继续由其原有入口校验和报告。
        if not any(token in original for token in _LEGACY_REFERENCE_TOKENS):
            continue
        payload = cast(JsonValue, json.loads(original))
        rewritten = _rewrite_runtime_value(payload)
        if path.name == "toolset_registrars.json":
            if not isinstance(payload, dict) or not all(isinstance(item, str) for item in payload.values()):
                raise ValueError("toolset_registrars.json 必须是字符串映射")
            rewritten = {key: "alpha." + item.removeprefix("dayu.")
                if isinstance(item, str) and item.startswith("dayu.") else item
                for key, item in payload.items()}
        if rewritten == payload:
            continue
        relative = path.relative_to(config_dir)
        backup = directory / _CONFIG_BACKUPS / relative
        update = directory / _CONFIG_UPDATES / relative
        if not backup.exists():
            _write_text_atomic(backup, original)
        _write_text_atomic(update, json.dumps(rewritten, ensure_ascii=False, indent=2) + "\n")


def _install_configuration_updates(base_dir: Path, directory: Path) -> bool:
    """安装已准备配置，拒绝覆盖准备之后发生的用户修改。

    Args:
        base_dir: 工作区目录。
        directory: 升级工作目录。
    Returns:
        是否存在需安装的更新。
    Raises:
        RuntimeError: 配置在升级期间被外部改动。
        OSError: 读取或写入失败。
    """
    updates = directory / _CONFIG_UPDATES
    changed = False
    for update in sorted(updates.rglob("*.json")) if updates.exists() else ():
        relative = update.relative_to(updates)
        target = base_dir / "config" / relative
        before = (directory / _CONFIG_BACKUPS / relative).read_text(encoding="utf-8")
        after = update.read_text(encoding="utf-8")
        current = target.read_text(encoding="utf-8")
        if current == after:
            continue
        if current != before:
            raise RuntimeError(f"配置在升级期间发生冲突，保留备份等待处理: {target}")
        _write_text_atomic(target, after)
        changed = True
    return changed


def _prepare_database(source: Path, target: Path) -> None:
    """以 SQLite 一致性备份建立新数据库并转换恢复路径。

    Args:
        source: 旧数据库。
        target: 准备目录中的新数据库。
    Returns:
        无。
    Raises:
        sqlite3.Error: 备份或更新失败。
        ValueError: 恢复快照不是有效 JSON。
        RuntimeError: 数据库完整性检查失败。
    """
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(target) as copied:
            original.backup(copied)
    with sqlite3.connect(target) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise RuntimeError("旧 Host 数据库完整性检查失败，原始数据未修改")
        table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pending_conversation_turns'").fetchone()
        if table is None:
            return
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(pending_conversation_turns)")}
        if "resume_source_json" not in columns:
            return
        for identity, raw in conn.execute("SELECT pending_turn_id, resume_source_json FROM pending_conversation_turns").fetchall():
            if not raw:
                continue
            payload = cast(JsonValue, json.loads(str(raw)))
            rewritten = _rewrite_runtime_value(payload)
            if payload != rewritten:
                conn.execute("UPDATE pending_conversation_turns SET resume_source_json=? WHERE pending_turn_id=?",
                    (json.dumps(rewritten, ensure_ascii=False), str(identity)))


def _migrate_configuration_only(base_dir: Path, directory: Path) -> bool:
    """转换没有旧状态目录的配置，并退役已安装的更新计划。

    Args:
        base_dir: 工作区目录。
        directory: 升级工作目录。
    Returns:
        是否实际更新配置。
    Raises:
        OSError: 文件写入或计划清理失败。
        ValueError: 配置内容非法。
        RuntimeError: 配置发生并发冲突。
    """
    _prepare_configuration_updates(base_dir, directory)
    changed = _install_configuration_updates(base_dir, directory)
    updates = directory / _CONFIG_UPDATES
    if updates.exists():
        shutil.rmtree(updates)
    return changed


def _prepare_namespace(old_root: Path, prepared: Path) -> None:
    """准备新目录并保留旧状态为可恢复来源。

    Args:
        old_root: 原始旧目录。
        prepared: 准备目录。
    Returns:
        无。
    Raises:
        OSError: 复制或移动失败。
        RuntimeError: 旧目录使用符号链接或数据库损坏。
    """
    if old_root.is_symlink():
        raise RuntimeError("旧状态目录是符号链接，请先明确真实工作区再迁移")
    if prepared.exists():
        shutil.rmtree(prepared)
    shutil.copytree(old_root, prepared, symlinks=True)
    source = old_root / "host" / _LEGACY_DATABASE
    if source.exists():
        target = prepared / "host" / _CURRENT_DATABASE
        _prepare_database(source, target)
        # 一致性备份已包含已提交 WAL；不能把旧文件名的 sidecar 带给新库。
        for suffix in ("", "-wal", "-shm"):
            (prepared / "host" / (_LEGACY_DATABASE + suffix)).unlink(missing_ok=True)


def migrate_alpha_namespace(base_dir: Path) -> bool:
    """执行可恢复、保留原件的 alpha 一次性命名升级。

    Args:
        base_dir: 已由 init 获取当前初始化锁的工作区目录。
    Returns:
        是否安装或恢复了升级。
    Raises:
        RuntimeError: 仍有旧进程、锁竞争、目录冲突或中断状态不一致。
        ValueError: 日志、配置或恢复快照损坏。
        OSError: 文件处理失败，保留原件和阶段日志供下次恢复。
        sqlite3.Error: 数据库备份或读取失败。
    """
    base_dir = base_dir.resolve()
    old_root = base_dir / _LEGACY_ROOT
    current = base_dir / _CURRENT_ROOT
    directory = base_dir / _MIGRATION_DIRECTORY
    phase = _read_phase(directory)
    if phase == _PHASE_COMPLETED:
        if old_root.exists():
            raise RuntimeError("升级完成后再次出现旧目录，存在冲突，请先检查原件")
        return False
    if not old_root.exists() and phase is None and not (base_dir / _LEGACY_INIT_LOCK).exists():
        return _migrate_configuration_only(base_dir, directory)
    legacy_lock = StateDirSingleInstanceLock(
        state_dir=base_dir, lock_file_name=_LEGACY_INIT_LOCK, lock_name="旧工作区初始化"
    )
    legacy_lock.acquire()
    try:
        if not old_root.exists() and phase is None:
            return _migrate_configuration_only(base_dir, directory)
        if phase is None:
            if current.exists():
                raise RuntimeError("新旧命名目录冲突，请保留两套数据并检查后再执行")
            _ensure_legacy_idle(old_root)
            _prepare_configuration_updates(base_dir, directory)
            _prepare_namespace(old_root, directory / _PREPARED)
            _write_phase(directory, _PHASE_PREPARED)
            phase = _PHASE_PREPARED
        if phase == _PHASE_PREPARED:
            original = directory / _ORIGINAL
            if old_root.exists() and not original.exists():
                old_root.rename(original)
            elif old_root.exists() or not original.exists():
                raise RuntimeError("旧状态备份目录冲突，未覆盖任何数据")
            _write_phase(directory, _PHASE_SAVED)
            phase = _PHASE_SAVED
        if phase == _PHASE_SAVED:
            prepared = directory / _PREPARED
            if prepared.exists() and not current.exists():
                prepared.rename(current)
            elif prepared.exists() or not current.exists():
                raise RuntimeError("准备目录与目标目录冲突，请检查升级日志")
            _write_phase(directory, _PHASE_INSTALLED)
        _install_configuration_updates(base_dir, directory)
        _write_phase(directory, _PHASE_COMPLETED)
        return True
    finally:
        legacy_lock.release()
