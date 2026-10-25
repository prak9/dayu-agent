"""持久受理执行者的完整身份校验与死亡租约清理。"""

import sqlite3

from alpha.process_liveness import OwnerIdentity, is_owner_identity_alive


def is_admission_executor_alive(row: sqlite3.Row) -> bool:
    """检查完整执行者身份。参数：受理数据行。返回：是否存活。异常：进程查询错误。"""
    if row["executor_pid"] is None:
        return False
    return is_owner_identity_alive(OwnerIdentity(
        pid=int(row["executor_pid"]),
        process_start_time=float(row["executor_start_time"]) if row["executor_start_time"] is not None else None,
        boot_id=str(row["executor_boot_id"]) if row["executor_boot_id"] is not None else None,
    ))


def release_dead_execution_leases(conn: sqlite3.Connection, session_id: str) -> None:
    """事务内释放死亡执行者租约。参数：连接、Session。返回：无。异常：SQLite/进程查询错误。"""
    rows = conn.execute("SELECT * FROM agent_admissions WHERE session_id=? AND executor_lease_id IS NOT NULL", (session_id,)).fetchall()
    for row in rows:
        if not is_admission_executor_alive(row):
            conn.execute("UPDATE agent_admissions SET executor_lease_id=NULL,executor_pid=NULL,"
                         "executor_start_time=NULL,executor_boot_id=NULL WHERE run_id=?", (row["run_id"],))
    operations = conn.execute("SELECT o.* FROM operation_admissions o JOIN runs r ON r.run_id=o.run_id "
                              "WHERE r.session_id=? AND o.executor_lease_id IS NOT NULL", (session_id,)).fetchall()
    for row in operations:
        if not is_admission_executor_alive(row):
            conn.execute("UPDATE operation_admissions SET executor_lease_id=NULL,executor_pid=NULL,"
                         "executor_start_time=NULL,executor_boot_id=NULL WHERE run_id=?", (row["run_id"],))
