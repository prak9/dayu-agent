"""Host 持久受理 schema 的初始化真源，供新库与显式 init 迁移共用。"""

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_admissions (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    request_key TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    pending_turn_id TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    contract_json TEXT NOT NULL,
    executor_lease_id TEXT,
    executor_pid INTEGER,
    executor_start_time REAL,
    executor_boot_id TEXT,
    result_json TEXT,
    source_run_id TEXT REFERENCES runs(run_id),
    UNIQUE(session_id,request_key)
);
CREATE TABLE IF NOT EXISTS session_admission_fences (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id),
    epoch INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS session_admission_stops (
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    request_key TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    PRIMARY KEY(session_id,request_key)
);
CREATE TABLE IF NOT EXISTS operation_admissions (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    request_key TEXT NOT NULL UNIQUE,
    fingerprint TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    executor_lease_id TEXT,
    executor_pid INTEGER,
    executor_start_time REAL,
    executor_boot_id TEXT
);
"""


def initialize_agent_admission_schema(conn: sqlite3.Connection) -> None:
    """在调用方事务中建表。参数：conn 连接。返回：无。异常：SQLite 错误。"""
    for statement in _SCHEMA.split(";"):
        if statement.strip():
            conn.execute(statement)
