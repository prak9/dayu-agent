"""无 Session 独立操作的原子受理、执行租约与原规格恢复。"""

import hashlib
import re
import sqlite3
from uuid import uuid4

from alpha.contracts.host_execution import HostedRunSpec
from alpha.contracts.host_execution_serialization import deserialize_hosted_operation, serialize_hosted_operation
from alpha.contracts.operation_admission import OperationAdmission, OperationAdmissionConflictError, OperationAdmissionRecoveryRequiredError
from alpha.contracts.run import RunState, TERMINAL_STATES
from alpha.host.admission_leases import is_admission_executor_alive
from alpha.host.admission_store import _epoch, _require_active_session, require_idle_session
from alpha.contracts.host_admission import AgentAdmissionStaleError
from alpha.host.host_store import HostStore, write_transaction
from alpha.host.run_persistence import build_created_run, insert_created_run
from alpha.process_liveness import current_owner_identity

_INPUT_HASH = re.compile(r"[a-f0-9]{64}\Z")


def _require(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    """要求持久操作存在。参数：连接、Run。返回：行。异常：缺失。"""
    row: sqlite3.Row | None = conn.execute("SELECT * FROM operation_admissions WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(f"独立操作受理不存在：{run_id}")
    return row


class SQLiteOperationAdmissionStore:
    """请求键绑定执行规格和输入摘要，受理不等于执行开始。"""

    def __init__(self, store: HostStore) -> None:
        """注入宿主库。参数：Host 存储。返回：无。异常：无。"""
        self._store = store

    def admit(self, request_key: str, spec: HostedRunSpec, input_hash: str, *, expected_epoch: int | None = None) -> OperationAdmission:
        """返回前持久受理。参数：稳定键、已接受规格、业务输入摘要。返回：原或新 Run。异常：冲突或非法规格。"""
        if not request_key.strip() or not spec.operation_name.strip() or not _INPUT_HASH.fullmatch(input_hash):
            raise ValueError("持久操作需要非空请求键、操作名和 SHA256 输入摘要")
        if (spec.session_id is None) != (expected_epoch is None):
            raise ValueError("Session 操作必须显式携带停止代际，独立操作不得携带代际")
        encoded = serialize_hosted_operation(spec)
        fingerprint = hashlib.sha256((encoded + "\n" + input_hash).encode()).hexdigest()
        conn = self._store.get_connection()
        with write_transaction(conn):
            existing = conn.execute("SELECT * FROM operation_admissions WHERE request_key=?", (request_key,)).fetchone()
            if existing is not None:
                if str(existing["fingerprint"]) != fingerprint:
                    raise OperationAdmissionConflictError("独立操作请求键对应的输入或规格改变")
                return OperationAdmission(str(existing["run_id"]), request_key)
            if spec.session_id is not None:
                _require_active_session(conn, spec.session_id)
                if _epoch(conn, spec.session_id) != expected_epoch:
                    raise AgentAdmissionStaleError("外部操作属于停止前的派发")
                require_idle_session(conn, spec.session_id)
            run = build_created_run(session_id=spec.session_id, service_type=spec.operation_name, scene_name=spec.scene_name, metadata=spec.metadata)
            insert_created_run(conn, run)
            conn.execute("INSERT INTO operation_admissions(run_id,request_key,fingerprint,input_hash,spec_json) VALUES (?,?,?,?,?)",
                         (run.run_id, request_key, fingerprint, input_hash, encoded))
            return OperationAdmission(run.run_id, request_key)

    def load_spec(self, run_id: str) -> HostedRunSpec:
        """读取原规格。参数：Run。返回：快照。异常：不存在或损坏。"""
        row = _require(self._store.get_connection(), run_id)
        encoded = str(row["spec_json"])
        actual = hashlib.sha256((encoded + "\n" + str(row["input_hash"])).encode()).hexdigest()
        if actual != str(row["fingerprint"]):
            raise OperationAdmissionConflictError("独立操作已接受规格完整性损坏")
        return deserialize_hosted_operation(encoded)

    def find(self, request_key: str) -> OperationAdmission | None:
        """查询已受理身份。参数：稳定请求键。返回：原 Run 或空。异常：数据库错误。"""
        row = self._store.get_connection().execute("SELECT run_id FROM operation_admissions WHERE request_key=?", (request_key,)).fetchone()
        return OperationAdmission(str(row[0]), request_key) if row is not None else None

    def claim(self, run_id: str) -> str | None:
        """领取从未执行的操作。参数：Run。返回：租约或空。异常：已开始的孤立操作需调和。"""
        conn = self._store.get_connection()
        with write_transaction(conn):
            row = _require(conn, run_id)
            run = conn.execute("SELECT state FROM runs WHERE run_id=?", (run_id,)).fetchone()
            state = RunState(str(run["state"]))
            if state in TERMINAL_STATES or is_admission_executor_alive(row):
                return None
            if state != RunState.CREATED:
                raise OperationAdmissionRecoveryRequiredError("独立操作曾开始执行，请先调和业务副作用")
            owner = current_owner_identity()
            lease = uuid4().hex
            conn.execute("UPDATE operation_admissions SET executor_lease_id=?,executor_pid=?,executor_start_time=?,executor_boot_id=? WHERE run_id=?",
                         (lease, owner.pid, owner.process_start_time, owner.boot_id, run_id))
            conn.execute("UPDATE runs SET owner_pid=?,owner_process_start_time=?,owner_boot_id=? WHERE run_id=?",
                         (owner.pid, owner.process_start_time, owner.boot_id, run_id))
            return lease

    def release(self, run_id: str, lease_id: str) -> None:
        """释放当前执行者。参数：Run、租约。返回：无。异常：数据库错误。"""
        conn = self._store.get_connection()
        with write_transaction(conn):
            conn.execute("UPDATE operation_admissions SET executor_lease_id=NULL,executor_pid=NULL,executor_start_time=NULL,executor_boot_id=NULL "
                         "WHERE run_id=? AND executor_lease_id=?", (run_id, lease_id))
