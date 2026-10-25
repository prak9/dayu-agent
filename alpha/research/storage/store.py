"""研究业务 SQLite 基础设施；不保存或解释 Host Run 状态。"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_LOCK_TIMEOUT_SECONDS = 30.0
_WAL_RETRY_SECONDS = 0.01
_SCHEMA_VERSION = 4
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS research_catalog (
    research_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    title TEXT NOT NULL,
    question TEXT NOT NULL,
    subjects_json TEXT NOT NULL,
    session_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK(state IN ('active', 'archived')),
    version INTEGER NOT NULL,
    as_of TEXT,
    depth TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(owner_id, request_key)
);
CREATE TABLE IF NOT EXISTS research_turns (
    turn_id TEXT PRIMARY KEY,
    research_id TEXT NOT NULL REFERENCES research_catalog(research_id),
    request_key TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    user_text TEXT NOT NULL,
    attachment_refs_json TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    as_of TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('queued','dispatching','submitted','settled','cancelled')),
    run_id TEXT,
    created_at TEXT NOT NULL,
    host_epoch INTEGER,
    method_hash TEXT NOT NULL,
    accepted_spec_json TEXT NOT NULL,
    execution_options_json TEXT,
    historical INTEGER NOT NULL CHECK(historical IN (0,1)),
    resume_request_key TEXT,
    financial_requirements_json TEXT NOT NULL,
    execution_mode TEXT NOT NULL CHECK(execution_mode IN ('internal','external')),
    publication_policy TEXT NOT NULL CHECK(publication_policy IN ('manual','on_complete')),
    publication_target_id TEXT,
    UNIQUE(research_id, request_key),
    UNIQUE(research_id, sequence)
);
CREATE UNIQUE INDEX IF NOT EXISTS research_single_dispatch
    ON research_turns(research_id) WHERE state IN ('dispatching','submitted');
CREATE UNIQUE INDEX IF NOT EXISTS research_unique_source_run
    ON research_turns(run_id) WHERE run_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS research_publications (
    publication_id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL REFERENCES research_revisions(revision_id),
    target_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    title TEXT NOT NULL,
    markdown TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    state TEXT NOT NULL,
    run_id TEXT,
    page_id TEXT,
    page_url TEXT,
    remote_task_id TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    creation_started INTEGER NOT NULL DEFAULT 0 CHECK(creation_started IN (0,1)),
    written_segments INTEGER NOT NULL DEFAULT 0,
    lease_id TEXT,
    owner_pid INTEGER,
    owner_start_time REAL,
    owner_boot_id TEXT,
    error TEXT,
    retry_at REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(revision_id,target_id)
);
CREATE TABLE IF NOT EXISTS publication_requests (
    owner_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    publication_id TEXT NOT NULL REFERENCES research_publications(publication_id),
    PRIMARY KEY(owner_id,request_key)
);
CREATE TABLE IF NOT EXISTS publication_segments (
    publication_id TEXT NOT NULL REFERENCES research_publications(publication_id),
    position INTEGER NOT NULL,
    markdown TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY(publication_id,position)
);
CREATE TABLE IF NOT EXISTS research_stop_fences (
    stop_id TEXT PRIMARY KEY,
    research_id TEXT NOT NULL REFERENCES research_catalog(research_id),
    request_key TEXT NOT NULL,
    through_sequence INTEGER NOT NULL,
    completed_epoch INTEGER,
    UNIQUE(research_id,request_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS research_single_pending_stop
    ON research_stop_fences(research_id) WHERE completed_epoch IS NULL;
CREATE TABLE IF NOT EXISTS research_revisions (
    revision_id TEXT PRIMARY KEY,
    research_id TEXT NOT NULL REFERENCES research_catalog(research_id),
    number INTEGER NOT NULL,
    parent_revision_id TEXT REFERENCES research_revisions(revision_id),
    source_turn_id TEXT NOT NULL REFERENCES research_turns(turn_id),
    source_run_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    skill_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(research_id, number),
    UNIQUE(research_id, source_turn_id)
);
CREATE TABLE IF NOT EXISTS research_channel_bindings (
    binding_id TEXT PRIMARY KEY,
    research_id TEXT NOT NULL REFERENCES research_catalog(research_id),
    channel TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    UNIQUE(channel,instance_id,conversation_id,topic_id),
    UNIQUE(research_id,channel,instance_id)
);
CREATE TABLE IF NOT EXISTS research_working_records (
    record_id TEXT PRIMARY KEY,
    research_id TEXT NOT NULL REFERENCES research_catalog(research_id),
    turn_id TEXT NOT NULL REFERENCES research_turns(turn_id),
    source_run_id TEXT NOT NULL,
    tool_call_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('note','calculation','report')),
    body_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_run_id,tool_call_id),
    UNIQUE(turn_id,sequence)
);
CREATE TABLE IF NOT EXISTS research_materials (
    material_id TEXT PRIMARY KEY,
    research_id TEXT NOT NULL REFERENCES research_catalog(research_id),
    name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    received_at TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    ticker TEXT,
    form_type TEXT,
    body BLOB
);
CREATE TABLE IF NOT EXISTS material_requests (
    research_id TEXT NOT NULL REFERENCES research_catalog(research_id),
    request_key TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    material_id TEXT NOT NULL REFERENCES research_materials(material_id),
    PRIMARY KEY(research_id,request_key)
);
CREATE TABLE IF NOT EXISTS research_candidates (
    candidate_id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL REFERENCES research_turns(turn_id),
    source_run_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    body_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_run_id,call_id)
);
CREATE TABLE IF NOT EXISTS research_financial_reads (
    receipt_id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL REFERENCES research_turns(turn_id),
    source_run_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    body_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_run_id,call_id)
);
CREATE TABLE IF NOT EXISTS research_notion_topics (
    research_id TEXT NOT NULL REFERENCES research_catalog(research_id),
    root_id TEXT NOT NULL,
    title TEXT NOT NULL,
    creation_started INTEGER NOT NULL DEFAULT 0,
    page_id TEXT,
    remote_task_id TEXT,
    lease_id TEXT,
    owner_pid INTEGER,
    owner_start_time REAL,
    owner_boot_id TEXT,
    PRIMARY KEY(research_id,root_id)
);
CREATE TABLE IF NOT EXISTS research_candidate_validations (
    source_run_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    turn_id TEXT NOT NULL REFERENCES research_turns(turn_id),
    candidate_id TEXT NOT NULL REFERENCES research_candidates(candidate_id),
    content_hash TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(source_run_id,call_id)
);
"""


def _ensure_wal(conn: sqlite3.Connection) -> None:
    """设置 WAL 并处理首次打开的锁升级竞争。参数：连接。返回：无。异常：非忙错误或超时原样传播。"""
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    while True:
        try:
            if str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() != "wal":
                conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            # journal_mode 在锁升级冲突时会直接 SQLITE_BUSY，不执行连接 busy handler。
            if exc.sqlite_errorcode & 0xFF != sqlite3.SQLITE_BUSY or time.monotonic() >= deadline:
                raise
            time.sleep(_WAL_RETRY_SECONDS)


class ResearchStore:
    """按操作持有连接，BEGIN IMMEDIATE 串行化跨实例研究写入。"""

    def __init__(self, db_path: Path) -> None:
        """初始化当前 schema。参数：db_path 数据库路径。返回：无。异常：SQLite/I/O 错误或旧 schema 冲突。"""
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection(write=True) as conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if version != _SCHEMA_VERSION and (version != 0 or tables):
                raise RuntimeError("研究 schema 不匹配，请先运行 alpha init 工作区迁移")
            # 不使用会隐式提交的 executescript，避免两个首次启动进程观察到半建表状态。
            for statement in _SCHEMA_SQL.split(";"):
                if statement.strip():
                    conn.execute(statement)
            conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    @contextmanager
    def connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        """提供独立连接。参数：write 是否获取写事务。返回：连接迭代器。异常：事务失败回滚并传播。"""
        conn = sqlite3.connect(self._db_path, timeout=_LOCK_TIMEOUT_SECONDS, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            _ensure_wal(conn)
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA foreign_keys=ON")
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
