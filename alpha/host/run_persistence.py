"""Host Run 创建记录及事务内落盘的共享实现。"""

from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

from alpha.contracts.execution_metadata import ExecutionDeliveryContext, normalize_execution_delivery_context
from alpha.contracts.run import RunRecord, RunState
from alpha.host._datetime_utils import now_utc
from alpha.process_liveness import current_owner_identity

_RUN_ID_RANDOM_CHARACTERS = 12


def build_created_run(
    *, session_id: str | None, service_type: str, scene_name: str | None,
    metadata: ExecutionDeliveryContext | None,
) -> RunRecord:
    """构造创建态记录。参数：会话、服务、场景、交付上下文。返回：Run。异常：上下文非法时 ValueError。"""
    owner = current_owner_identity()
    return RunRecord(
        run_id=f"run_{uuid4().hex[:_RUN_ID_RANDOM_CHARACTERS]}", session_id=session_id,
        service_type=service_type, scene_name=scene_name, state=RunState.CREATED, created_at=now_utc(),
        owner_pid=owner.pid, owner_process_start_time=owner.process_start_time, owner_boot_id=owner.boot_id,
        metadata=normalize_execution_delivery_context(metadata),
    )


def insert_created_run(conn: sqlite3.Connection, run: RunRecord) -> None:
    """在调用方事务内插入 Run。参数：连接、创建态记录。返回：无。异常：SQLite 错误。"""
    conn.execute(
        "INSERT INTO runs (run_id,session_id,service_type,scene_name,state,created_at,owner_pid,"
        "owner_process_start_time,owner_boot_id,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (run.run_id, run.session_id, run.service_type, run.scene_name, run.state.value, run.created_at.isoformat(),
         run.owner_pid, run.owner_process_start_time, run.owner_boot_id, json.dumps(run.metadata, ensure_ascii=False)),
    )
