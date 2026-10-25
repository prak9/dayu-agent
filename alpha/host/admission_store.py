"""Host 持久受理仓储：Run、accepted 快照与请求身份同事务提交。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import cast
from uuid import uuid4

from alpha.contracts.agent_execution import ExecutionContract, ExecutionContractSnapshot
from alpha.contracts.agent_execution_serialization import deserialize_execution_contract_snapshot, serialize_execution_contract_snapshot
from alpha.contracts.events import AppResult
from alpha.contracts.host_admission import (
    AgentAdmissionBusyError, AgentAdmissionConflictError, AgentAdmissionRecoveryRequiredError,
    AgentAdmissionStaleError, AgentTurnAdmission,
)
from alpha.contracts.run import RunCancelReason, RunState, TERMINAL_STATES
from alpha.contracts.session import SessionState
from alpha.host._datetime_utils import now_utc
from alpha.host.host_store import HostStore, write_transaction
from alpha.host.admission_leases import is_admission_executor_alive, release_dead_execution_leases
from alpha.host.pending_turn_store import PendingConversationTurnState
from alpha.host.prepared_turn import deserialize_prepared_agent_turn_snapshot, serialize_accepted_agent_turn_snapshot, snapshot_accepted_execution
from alpha.host.protocols import SessionWriteBlockedError
from alpha.host.run_persistence import build_created_run, insert_created_run
from alpha.process_liveness import current_owner_identity


def _admission(row: sqlite3.Row) -> AgentTurnAdmission:
    """映射身份。参数：数据行。返回：受理。异常：损坏数据导致 ValueError。"""
    return AgentTurnAdmission(str(row["run_id"]), str(row["session_id"]), str(row["request_key"]),
                              str(row["pending_turn_id"]), int(row["epoch"]))


def _require_active_session(conn: sqlite3.Connection, session_id: str) -> None:
    """事务内校验 Session。参数：连接、会话。返回：无。异常：不存在或非活动态。"""
    session = conn.execute("SELECT state FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    if session is None:
        raise KeyError(f"Session 不存在：{session_id}")
    if str(session["state"]) != SessionState.ACTIVE.value:
        raise SessionWriteBlockedError(session_id, "Session 已禁止写入")


def _epoch(conn: sqlite3.Connection, session_id: str) -> int:
    """读取停止代际。参数：连接、会话。返回：epoch。异常：SQLite 错误。"""
    row = conn.execute("SELECT epoch FROM session_admission_fences WHERE session_id=?", (session_id,)).fetchone()
    return int(row["epoch"]) if row is not None else 0


def _require_admission(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    """读取受理行。参数：连接、Run。返回：行。异常：不存在时 KeyError。"""
    row: sqlite3.Row | None = conn.execute("SELECT * FROM agent_admissions WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(f"持久受理不存在：{run_id}")
    return row


def require_idle_session(conn: sqlite3.Connection, session_id: str, *, ignored_pending_id: str | None = None) -> None:
    """共享 Agent 与外部操作的写互斥。参数：连接、会话、忽略的恢复项。返回：无。异常：活跃或未释放执行。"""
    runs = conn.execute("SELECT state FROM runs WHERE session_id=?", (session_id,)).fetchall()
    if any(RunState(row["state"]) not in TERMINAL_STATES for row in runs):
        raise AgentAdmissionBusyError("Session 仍有活跃执行")
    release_dead_execution_leases(conn, session_id)
    held = conn.execute("SELECT run_id FROM agent_admissions WHERE session_id=? AND executor_lease_id IS NOT NULL "
                        "UNION ALL SELECT o.run_id FROM operation_admissions o JOIN runs r ON r.run_id=o.run_id "
                        "WHERE r.session_id=? AND o.executor_lease_id IS NOT NULL", (session_id, session_id)).fetchall()
    if held:
        raise AgentAdmissionBusyError("执行正在释放资源，请等待收敛")
    pending = conn.execute("SELECT p.pending_turn_id,r.state FROM pending_conversation_turns p LEFT JOIN runs r ON r.run_id=p.source_run_id "
                           "WHERE p.session_id=?", (session_id,)).fetchall()
    for row in pending:
        if str(row["pending_turn_id"]) == ignored_pending_id:
            continue
        if row["state"] not in (RunState.SUCCEEDED.value, RunState.CANCELLED.value):
            raise AgentAdmissionBusyError("Session 有待恢复的输入，请显式恢复或取消")
        conn.execute("DELETE FROM pending_conversation_turns WHERE pending_turn_id=?", (row["pending_turn_id"],))


class SQLiteAgentAdmissionStore:
    """停止 fencing、幂等受理和执行领取的 Host 内部真源。"""

    def __init__(self, store: HostStore) -> None:
        """注入 Host 库。参数：store 存储。返回：无。异常：无。"""
        self._store = store

    def session_epoch(self, session_id: str) -> int:
        """读取当前代际。参数：会话。返回：epoch。异常：不存在或已禁止写入。"""
        conn = self._store.get_connection()
        _require_active_session(conn, session_id)
        return _epoch(conn, session_id)

    def admit(self, request_key: str, contract: ExecutionContract, *, expected_epoch: int) -> AgentTurnAdmission:
        """持久受理。参数：请求键、契约、预期代际。返回：受理。异常：繁忙、冲突、停止或非法输入。"""
        session_id = contract.host_policy.session_key
        user_text = contract.message_inputs.user_message
        if not request_key.strip() or not session_id or user_text is None or not user_text.strip():
            raise ValueError("持久受理需要非空请求键、Session 和用户输入")
        if not contract.host_policy.resumable or contract.message_inputs.replay_from is not None:
            raise ValueError("持久受理必须允许恢复，且不能保存进程内 replay 句柄")
        snapshot_json = json.dumps(serialize_execution_contract_snapshot(contract), ensure_ascii=False, sort_keys=True)
        fingerprint = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        conn = self._store.get_connection()
        with write_transaction(conn):
            existing = conn.execute("SELECT * FROM agent_admissions WHERE session_id=? AND request_key=?",
                                    (session_id, request_key)).fetchone()
            if existing is not None:
                if str(existing["input_hash"]) != fingerprint:
                    raise AgentAdmissionConflictError("同一受理键的执行输入发生变化")
                return _admission(existing)
            _require_active_session(conn, session_id)
            if _epoch(conn, session_id) != expected_epoch:
                raise AgentAdmissionStaleError("输入属于停止前的旧派发")
            require_idle_session(conn, session_id)
            run = build_created_run(session_id=session_id, service_type=contract.service_name,
                                    scene_name=contract.scene_name, metadata=contract.metadata)
            insert_created_run(conn, run)
            pending_id = f"pending_{uuid4().hex}"
            now = run.created_at.isoformat()
            conn.execute(
                "INSERT INTO pending_conversation_turns (pending_turn_id,session_id,scene_name,user_text,source_run_id,"
                "created_at,updated_at,resumable,state,resume_source_json,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (pending_id, session_id, contract.scene_name, user_text, run.run_id,
                 now, now, 1, PendingConversationTurnState.ACCEPTED_BY_HOST.value,
                 json.dumps(serialize_accepted_agent_turn_snapshot(snapshot_accepted_execution(contract)),
                            ensure_ascii=False, sort_keys=True), json.dumps(contract.metadata, ensure_ascii=False)),
            )
            conn.execute(
                "INSERT INTO agent_admissions (run_id,session_id,request_key,input_hash,pending_turn_id,epoch,contract_json) "
                "VALUES (?,?,?,?,?,?,?)",
                (run.run_id, session_id, request_key, fingerprint, pending_id, expected_epoch, snapshot_json),
            )
            return _admission(_require_admission(conn, run.run_id))

    def admit_resume(self, source_run_id: str, request_key: str, *, expected_epoch: int, max_attempts: int) -> AgentTurnAdmission:
        """持久受理显式恢复。参数：原 Run、稳定恢复键、停止代际、恢复上限。返回：新或原受理。异常：冲突、繁忙、取消或缺失快照。"""
        if not request_key.strip():
            raise ValueError("恢复请求键不能为空")
        conn = self._store.get_connection()
        with write_transaction(conn):
            source = _require_admission(conn, source_run_id)
            session_id = str(source["session_id"])
            existing = conn.execute("SELECT * FROM agent_admissions WHERE session_id=? AND request_key=?", (session_id, request_key)).fetchone()
            if existing is not None:
                if str(existing["source_run_id"]) != source_run_id:
                    raise AgentAdmissionConflictError("恢复键已关联其他来源 Run")
                return _admission(existing)
            _require_active_session(conn, session_id)
            if _epoch(conn, session_id) != expected_epoch:
                raise AgentAdmissionStaleError("恢复属于停止前的派发")
            run_row = conn.execute("SELECT * FROM runs WHERE run_id=?", (source_run_id,)).fetchone()
            state = RunState(str(run_row["state"]))
            if state not in (RunState.FAILED, RunState.UNSETTLED) and not (
                state == RunState.CANCELLED and run_row["cancel_reason"] == RunCancelReason.TIMEOUT.value
            ):
                raise AgentAdmissionConflictError("只允许显式恢复失败、孤立或超时 Run")
            pending = conn.execute("SELECT * FROM pending_conversation_turns WHERE pending_turn_id=? AND source_run_id=?",
                                   (source["pending_turn_id"], source_run_id)).fetchone()
            if pending is None or not bool(pending["resumable"]):
                raise AgentAdmissionRecoveryRequiredError("原输入没有可恢复快照")
            if str(pending["state"]) == PendingConversationTurnState.RESUMING.value:
                raise AgentAdmissionBusyError("原输入正由其他恢复者处理")
            if int(pending["resume_attempt_count"]) >= max_attempts:
                raise AgentAdmissionRecoveryRequiredError("原输入已达到恢复次数上限")
            # 在新 Run 落盘前校验原快照，不能将损坏 prepared 静默降级为重新准备。
            payload = cast(ExecutionContractSnapshot, json.loads(str(pending["resume_source_json"])))
            if str(pending["state"]) == PendingConversationTurnState.ACCEPTED_BY_HOST.value:
                deserialize_execution_contract_snapshot(payload)
            else:
                deserialize_prepared_agent_turn_snapshot(payload)
            require_idle_session(conn, session_id, ignored_pending_id=str(pending["pending_turn_id"]))
            contract = deserialize_execution_contract_snapshot(cast(ExecutionContractSnapshot, json.loads(str(source["contract_json"]))))
            run = build_created_run(session_id=session_id, service_type=contract.service_name, scene_name=contract.scene_name, metadata=contract.metadata)
            insert_created_run(conn, run)
            conn.execute("UPDATE pending_conversation_turns SET source_run_id=?,resume_attempt_count=resume_attempt_count+1,updated_at=? "
                         "WHERE pending_turn_id=?", (run.run_id, run.created_at.isoformat(), pending["pending_turn_id"]))
            conn.execute("INSERT INTO agent_admissions (run_id,session_id,request_key,input_hash,pending_turn_id,epoch,contract_json,source_run_id) "
                         "VALUES (?,?,?,?,?,?,?,?)", (run.run_id, session_id, request_key, source["input_hash"], pending["pending_turn_id"],
                                                   expected_epoch, source["contract_json"], source_run_id))
            return _admission(_require_admission(conn, run.run_id))

    def get(self, run_id: str) -> AgentTurnAdmission:
        """读取受理。参数：Run。返回：受理。异常：不存在。"""
        return _admission(_require_admission(self._store.get_connection(), run_id))

    def find(self, session_id: str, request_key: str) -> AgentTurnAdmission | None:
        """查询既有受理。参数：会话、请求键。返回：受理或空。异常：SQLite 错误。"""
        row = self._store.get_connection().execute(
            "SELECT * FROM agent_admissions WHERE session_id=? AND request_key=?", (session_id, request_key),
        ).fetchone()
        return _admission(row) if row is not None else None

    def load_contract(self, run_id: str) -> ExecutionContract:
        """恢复原接受契约。参数：Run。返回：契约。异常：不存在或快照损坏。"""
        row = _require_admission(self._store.get_connection(), run_id)
        return deserialize_execution_contract_snapshot(cast(ExecutionContractSnapshot, json.loads(str(row["contract_json"]))))

    def stop_session(self, session_id: str, request_key: str) -> int:
        """幂等推进停止边界。参数：Session、稳定请求键。返回：原/新 epoch。异常：空键或写入禁止。"""
        if not request_key.strip():
            raise ValueError("Host 停止请求键不能为空")
        conn = self._store.get_connection()
        with write_transaction(conn):
            existing = conn.execute("SELECT epoch FROM session_admission_stops WHERE session_id=? AND request_key=?",
                                    (session_id, request_key)).fetchone()
            if existing is not None:
                return int(existing["epoch"])
            _require_active_session(conn, session_id)
            epoch = _epoch(conn, session_id) + 1
            conn.execute(
                "INSERT INTO session_admission_fences VALUES (?,?) ON CONFLICT(session_id) DO UPDATE SET epoch=excluded.epoch",
                (session_id, epoch),
            )
            conn.execute("INSERT INTO session_admission_stops VALUES (?,?,?)", (session_id, request_key, epoch))
            conn.execute(
                "UPDATE runs SET cancel_requested_at=COALESCE(cancel_requested_at,?),"
                "cancel_requested_reason=COALESCE(cancel_requested_reason,?) "
                "WHERE session_id=? AND state IN ('created','queued','running')",
                (now_utc().isoformat(), RunCancelReason.USER_CANCELLED.value, session_id),
            )
            # 未领取的 CREATED Run 没有模型/工具资源，可以立即取消；已领取者仍协作收尾。
            conn.execute(
                "UPDATE runs SET state=?,completed_at=?,cancel_reason=? WHERE session_id=? AND state=? "
                "AND run_id IN (SELECT run_id FROM agent_admissions WHERE executor_lease_id IS NULL "
                "UNION ALL SELECT run_id FROM operation_admissions WHERE executor_lease_id IS NULL)",
                (RunState.CANCELLED.value, now_utc().isoformat(), RunCancelReason.USER_CANCELLED.value,
                 session_id, RunState.CREATED.value),
            )
            # 明确停止同时放弃终态输入的恢复等待；否则 FAILED pending 会永久阻塞新输入。
            conn.execute(
                "DELETE FROM pending_conversation_turns WHERE session_id=? AND source_run_id IN "
                "(SELECT run_id FROM runs WHERE session_id=? AND state IN ('succeeded','failed','cancelled','unsettled'))",
                (session_id, session_id),
            )
            return epoch

    def claim_execution(self, run_id: str) -> str | None:
        """领取尚未启动的执行。参数：Run。返回：租约或空。异常：已开始的孤立执行需要显式恢复。"""
        conn = self._store.get_connection()
        with write_transaction(conn):
            row = _require_admission(conn, run_id)
            run = conn.execute("SELECT state FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if RunState(run["state"]) in TERMINAL_STATES or is_admission_executor_alive(row):
                return None
            if str(run["state"]) != RunState.CREATED.value:
                raise AgentAdmissionRecoveryRequiredError("孤立执行已开始，请通过 Host pending turn 显式恢复")
            owner = current_owner_identity()
            lease = uuid4().hex
            conn.execute("UPDATE agent_admissions SET executor_lease_id=?,executor_pid=?,executor_start_time=?,executor_boot_id=? "
                         "WHERE run_id=?", (lease, owner.pid, owner.process_start_time, owner.boot_id, run_id))
            conn.execute("UPDATE runs SET owner_pid=?,owner_process_start_time=?,owner_boot_id=? WHERE run_id=?",
                         (owner.pid, owner.process_start_time, owner.boot_id, run_id))
            return lease

    def record_result(self, run_id: str, lease_id: str, result: AppResult) -> None:
        """保存正式模型结果以供业务提交重放。参数：Run、租约、结果。返回：无。异常：过期租约。"""
        payload = json.dumps({"content": result.content, "errors": result.errors, "warnings": result.warnings,
                              "degraded": result.degraded, "filtered": result.filtered}, ensure_ascii=False)
        conn = self._store.get_connection()
        with write_transaction(conn):
            changed = conn.execute("UPDATE agent_admissions SET result_json=? WHERE run_id=? AND executor_lease_id=?",
                                   (payload, run_id, lease_id)).rowcount
            if not changed:
                raise AgentAdmissionConflictError("执行租约已过期，拒绝迟到结果")

    def read_result(self, run_id: str) -> AppResult | None:
        """读取已记录结果。参数：Run。返回：结果或空。异常：不存在或损坏。"""
        row = _require_admission(self._store.get_connection(), run_id)
        if row["result_json"] is None:
            return None
        payload = cast(dict[str, str | bool | list[str]], json.loads(str(row["result_json"])))
        return AppResult(content=cast(str, payload["content"]), errors=cast(list[str], payload["errors"]),
                         warnings=cast(list[str], payload["warnings"]), degraded=cast(bool, payload["degraded"]),
                         filtered=cast(bool, payload["filtered"]))

    def release_execution(self, run_id: str, lease_id: str) -> None:
        """释放自己的执行租约。参数：Run、租约。返回：无。异常：SQLite 错误。"""
        conn = self._store.get_connection()
        with write_transaction(conn):
            conn.execute("UPDATE agent_admissions SET executor_lease_id=NULL,executor_pid=NULL,"
                         "executor_start_time=NULL,executor_boot_id=NULL WHERE run_id=? AND executor_lease_id=?",
                         (run_id, lease_id))
