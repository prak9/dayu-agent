"""为旧工作区 Host 库显式新增持久受理表，不改写历史 Run。"""

import sqlite3
from pathlib import Path

from alpha.host.admission_schema import initialize_agent_admission_schema
from alpha.workspace_paths import build_host_store_default_path

_ADMISSION_TABLES = ("agent_admissions", "session_admission_fences", "session_admission_stops", "operation_admissions")


def migrate_host_admission_init(base_dir: Path) -> bool:
    """初始化受理 schema。参数：base_dir 工作区。返回：是否首次新增。异常：SQLite/I/O 错误。"""
    path = build_host_store_default_path(base_dir)
    if not path.exists():
        return False
    with sqlite3.connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        placeholders = ",".join("?" for _ in _ADMISSION_TABLES)
        existing = conn.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({placeholders})", _ADMISSION_TABLES).fetchall()
        initialize_agent_admission_schema(conn)
        return len(existing) != len(_ADMISSION_TABLES)
