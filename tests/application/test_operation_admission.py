"""独立操作受理、线程领取、原规格和生命周期的行为测试。"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from alpha.contracts.host_execution import ConcurrencyAcquirePolicy, HostedRunContext, HostedRunSpec
from alpha.contracts.host_execution_serialization import deserialize_hosted_operation, serialize_hosted_operation
from alpha.contracts.operation_admission import OperationAdmissionBusyError, OperationAdmissionConflictError, OperationAdmissionRecoveryRequiredError
from alpha.contracts.run import RunState
from alpha.host.host import Host
from alpha.host.host_store import HostStore
from alpha.host.operation_admission_store import SQLiteOperationAdmissionStore
from alpha.host.run_registry import SQLiteRunRegistry

_INPUT_HASH = "0" * 64
_DEAD_PID = 99_999_999


@dataclass
class _Operation:
    """记录真正执行次数，不用返回值冒充远端副作用确认。"""

    fail: bool = False
    runs: list[str] = field(default_factory=list)

    def __call__(self, context: HostedRunContext) -> str:
        """处理一次操作。参数：宿主上下文。返回：结果。异常：指定故障。"""
        context.cancellation_token.raise_if_cancelled()
        self.runs.append(context.run_id)
        if self.fail:
            raise RuntimeError("模拟外部操作失败")
        return "saved"


def test_operation_is_durable_and_success_is_not_executed_twice(tmp_path: Path) -> None:
    """相同接受规格复用 Run，成功重放不重复调用。参数：目录。返回：无。异常：断言失败。"""
    host = Host(host_store_path=tmp_path / "host.db", lane_config={"publication": 1})
    spec = HostedRunSpec("publication", business_concurrency_lane="publication", timeout_ms=10000)
    first = host.admit_operation("publication:attempt:1", spec, _INPUT_HASH)
    assert host.admit_operation("publication:attempt:1", spec, _INPUT_HASH) == first
    run = host.get_run(first.run_id)
    assert run is not None and run.state == RunState.CREATED and run.session_id is None
    other = Host(host_store_path=tmp_path / "host.db", lane_config={"publication": 1})
    operation = _Operation()
    assert other.run_admitted_operation_sync(first.run_id, operation) == "saved"
    assert host.run_admitted_operation_sync(first.run_id, operation) is None
    assert operation.runs == [first.run_id]
    assert not host.list_active_runs() and all(status.active == 0 for status in host.get_all_lane_statuses().values())
    with pytest.raises(OperationAdmissionConflictError):
        host.admit_operation("publication:attempt:1", replace(spec, timeout_ms=20000), _INPUT_HASH)
    with pytest.raises(ValueError):
        host.admit_operation("bad", replace(spec, session_id="session"), _INPUT_HASH)


def test_live_lease_and_failed_run_require_distinct_resolution(tmp_path: Path) -> None:
    """资源持有时繁忙，执行失败后不能用同键盲目再执行。参数：目录。返回：无。异常：断言失败。"""
    path = tmp_path / "host.db"
    host = Host(host_store_path=path)
    first = host.admit_operation("first", HostedRunSpec("publication"), _INPUT_HASH)
    store = SQLiteOperationAdmissionStore(HostStore(path))
    lease = store.claim(first.run_id)
    assert lease is not None
    with pytest.raises(OperationAdmissionBusyError):
        host.run_admitted_operation_sync(first.run_id, _Operation())
    store.release(first.run_id, "wrong-lease")
    assert store.claim(first.run_id) is None
    store.release(first.run_id, lease)
    operation = _Operation(fail=True)
    with pytest.raises(RuntimeError, match="外部操作失败"):
        host.run_admitted_operation_sync(first.run_id, operation)
    with pytest.raises(OperationAdmissionRecoveryRequiredError):
        host.run_admitted_operation_sync(first.run_id, operation)
    assert len(operation.runs) == 1 and not host.list_active_runs()


def test_aged_acceptance_survives_exit_but_started_orphan_needs_reconciliation(tmp_path: Path) -> None:
    """长期未领取仍是原 Run，已开始的死亡执行者不自动重跑。参数：目录。返回：无。异常：断言失败。"""
    path = tmp_path / "host.db"
    host = Host(host_store_path=path)
    first = host.admit_operation("first", HostedRunSpec("publication"), _INPUT_HASH)
    store = HostStore(path)
    conn = store.get_connection()
    conn.execute("UPDATE runs SET owner_pid=?,owner_process_start_time=NULL,owner_boot_id=NULL,created_at=? WHERE run_id=?",
                 (_DEAD_PID, (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), first.run_id))
    registry = SQLiteRunRegistry(store)
    assert registry.cleanup_orphan_runs() == []
    admissions = SQLiteOperationAdmissionStore(store)
    registry.start_run(first.run_id)
    with pytest.raises(OperationAdmissionRecoveryRequiredError):
        admissions.claim(first.run_id)


def test_corrupt_spec_fails_before_handler_and_releases_lease(tmp_path: Path) -> None:
    """快照损坏不降级当前配置，也不留 CREATED 僵尸。参数：目录。返回：无。异常：断言失败。"""
    path = tmp_path / "host.db"
    host = Host(host_store_path=path)
    first = host.admit_operation("first", HostedRunSpec("publication"), _INPUT_HASH)
    HostStore(path).get_connection().execute("UPDATE operation_admissions SET spec_json='{}'")
    operation = _Operation()
    with pytest.raises(OperationAdmissionConflictError, match="完整性"):
        host.run_admitted_operation_sync(first.run_id, operation)
    assert not operation.runs and not host.list_active_runs()
    run = host.get_run(first.run_id)
    assert run is not None and run.state == RunState.FAILED and run.started_at is None


def test_hosted_operation_snapshot_roundtrip_and_strict_boundaries() -> None:
    """并发策略和交付配置固定，非法类型不能被强制转换。参数：无。返回：无。异常：断言失败。"""
    spec = HostedRunSpec("publication", business_concurrency_lane="publication", timeout_ms=5000,
                         concurrency_acquire_policy=ConcurrencyAcquirePolicy.with_timeout(2), metadata={"delivery_channel": "telegram"})
    assert deserialize_hosted_operation(serialize_hosted_operation(spec)) == spec
    for encoded in ("[]", "{}", serialize_hosted_operation(spec).replace('"timeout_ms":5000', '"timeout_ms":true'),
                    serialize_hosted_operation(spec).replace('"mode":"timeout"', '"mode":"invalid"')):
        with pytest.raises(ValueError):
            deserialize_hosted_operation(encoded)
