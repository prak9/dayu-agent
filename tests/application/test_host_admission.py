"""Host 返回前持久受理、会话互斥与停止边界的行为测试。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from multiprocessing import get_context
from typing import AsyncGenerator
import sqlite3

import pytest
from pytest_mock import MockerFixture

from alpha.contracts.agent_execution import (
    AcceptedExecutionSpec, AcceptedModelSpec, ExecutionContract, ExecutionHostPolicy,
    ExecutionMessageInputs, ScenePreparationSpec,
    AgentInput,
)
from alpha.contracts.host_admission import (
    AgentAdmissionConflictError, AgentAdmissionBusyError, AgentAdmissionStaleError,
    AgentAdmissionRecoveryRequiredError, AgentTurnAdmission,
)
from alpha.contracts.events import AppEvent, AppEventType, AppResult
from alpha.contracts.run import RunState
from alpha.contracts.session import SessionSource
from alpha.host.admission_store import SQLiteAgentAdmissionStore
from alpha.host.admission_execution import HostAgentAdmissionRuntime
from alpha.host.executor import DefaultHostExecutor
from alpha.host.host import Host
from alpha.host.host_store import HostStore
from alpha.host.pending_turn_store import SQLitePendingConversationTurnStore
from alpha.host.run_registry import SQLiteRunRegistry
from alpha.host.session_registry import SQLiteSessionRegistry
from alpha.host.protocols import SessionWriteBlockedError
from alpha.host.scene_preparer import PreparedAgentExecution
from alpha.host.prepared_turn import PreparedAgentTurnSnapshot, PreparedConversationSessionSnapshot
from alpha.host.host_execution import HostedRunContext
from alpha.host.conversation_store import ConversationTranscript
from alpha.contracts.execution_options import ConversationMemorySettings

_DEAD_OWNER_PID = 99_999_999


def _contract(session: str, text: str = "研究") -> ExecutionContract:
    """构造契约。参数：会话、文本。返回：契约。异常：无。"""
    return ExecutionContract("research", "research", ExecutionHostPolicy(session_key=session, resumable=True),
                             ScenePreparationSpec(), ExecutionMessageInputs(user_message=text),
                             AcceptedExecutionSpec(model=AcceptedModelSpec("test")))


def _store(tmp_path: Path) -> HostStore:
    """准备存储和会话。参数：目录。返回：Host 存储。异常：SQLite 错误。"""
    store = HostStore(tmp_path / "host.db")
    store.initialize_schema()
    SQLiteSessionRegistry(store).ensure_session("session", SessionSource.API)
    return store


def test_admission_is_durable_before_execution_and_idempotent(tmp_path: Path) -> None:
    """受理返回时 Run 与 accepted 快照均存在。参数：目录。返回：无。异常：断言失败。"""
    store = _store(tmp_path)
    admissions = SQLiteAgentAdmissionStore(store)
    first = admissions.admit("request", _contract("session"), expected_epoch=0)
    run = SQLiteRunRegistry(store).get_run(first.run_id)
    assert run is not None and run.state == RunState.CREATED
    pending = SQLitePendingConversationTurnStore(store).get_pending_turn(first.pending_turn_id)
    assert pending is not None and pending.source_run_id == first.run_id
    assert admissions.admit("request", _contract("session"), expected_epoch=0) == first
    other_store = HostStore(tmp_path / "host.db")
    other_store.initialize_schema()
    other = SQLiteAgentAdmissionStore(other_store)
    assert other.admit("request", _contract("session"), expected_epoch=0) == first
    with pytest.raises(AgentAdmissionConflictError):
        other.admit("request", _contract("session", "不同问题"), expected_epoch=0)
    with pytest.raises(AgentAdmissionBusyError):
        other.admit("request2", _contract("session", "下一轮"), expected_epoch=0)
    assert other.load_contract(first.run_id) == _contract("session")


def test_stop_fences_late_admission_but_keeps_session_open(tmp_path: Path) -> None:
    """停止使旧 epoch 失效但不关闭 Session。参数：目录。返回：无。异常：断言失败。"""
    store = _store(tmp_path)
    admissions = SQLiteAgentAdmissionStore(store)
    first = admissions.admit("request", _contract("session"), expected_epoch=0)
    assert admissions.stop_session("session", "stop1") == 1
    run = SQLiteRunRegistry(store).get_run(first.run_id)
    assert run is not None and run.cancel_requested_at is not None
    with pytest.raises(AgentAdmissionStaleError):
        admissions.admit("late", _contract("session", "停止前旧派发"), expected_epoch=0)
    # 重放旧请求只返回原 Run，不能把用户取消变成新的执行。
    assert admissions.admit("request", _contract("session"), expected_epoch=1) == first
    SQLiteRunRegistry(store).mark_cancelled(first.run_id)
    SQLitePendingConversationTurnStore(store).delete_pending_turn(first.pending_turn_id)
    second = admissions.admit("new", _contract("session", "停止后的输入"), expected_epoch=1)
    assert second.run_id != first.run_id
    assert admissions.session_epoch("session") == 1
    assert admissions.stop_session("session", "stop1") == 1
    new_run = SQLiteRunRegistry(store).get_run(second.run_id)
    assert new_run is not None and new_run.cancel_requested_at is None


def test_invalid_admission_does_not_leave_partial_run(tmp_path: Path) -> None:
    """非法受理不留下孤立 Run。参数：目录。返回：无。异常：断言失败。"""
    store = _store(tmp_path)
    admissions = SQLiteAgentAdmissionStore(store)
    with pytest.raises(ValueError):
        admissions.admit("", _contract("session"), expected_epoch=0)
    with pytest.raises(ValueError):
        admissions.admit("request", replace(_contract("session"), host_policy=ExecutionHostPolicy()), expected_epoch=0)
    assert SQLiteRunRegistry(store).list_runs() == []


def test_admission_transaction_rolls_back_all_rows(tmp_path: Path) -> None:
    """快照插入失败同步回滚 Run。参数：目录。返回：无。异常：断言失败。"""
    store = _store(tmp_path)
    store.get_connection().execute("CREATE TRIGGER fail_pending BEFORE INSERT ON pending_conversation_turns "
                                   "BEGIN SELECT RAISE(ABORT,'模拟写失败'); END")
    with pytest.raises(sqlite3.IntegrityError, match="模拟"):
        SQLiteAgentAdmissionStore(store).admit("request", _contract("session"), expected_epoch=0)
    assert SQLiteRunRegistry(store).list_runs() == []
    assert store.get_connection().execute("SELECT COUNT(*) FROM agent_admissions").fetchone()[0] == 0


def test_claim_lease_fencing_and_orphan_policy(tmp_path: Path) -> None:
    """活执行不被接管，孤立已启动执行不盲重跑。参数：目录。返回：无。异常：断言失败。"""
    store = _store(tmp_path)
    admissions = SQLiteAgentAdmissionStore(store)
    first = admissions.admit("request", _contract("session"), expected_epoch=0)
    assert admissions.find("session", "missing") is None
    assert admissions.find("session", "request") == first
    assert admissions.read_result(first.run_id) is None
    lease = admissions.claim_execution(first.run_id)
    assert lease is not None
    assert admissions.claim_execution(first.run_id) is None
    admissions.release_execution(first.run_id, "wrong-lease")
    assert admissions.claim_execution(first.run_id) is None
    with pytest.raises(AgentAdmissionConflictError):
        admissions.record_result(first.run_id, "wrong-lease", AppResult("过期结果", [], []))
    result = AppResult("正式报告", [], ["缺口"])
    admissions.record_result(first.run_id, lease, result)
    assert admissions.read_result(first.run_id) == result
    SQLiteRunRegistry(store).start_run(first.run_id)
    store.get_connection().execute("UPDATE agent_admissions SET executor_pid=?,executor_start_time=NULL,executor_boot_id=NULL",
                                   (_DEAD_OWNER_PID,))
    with pytest.raises(AgentAdmissionRecoveryRequiredError):
        admissions.claim_execution(first.run_id)
    admissions.release_execution(first.run_id, lease)
    SQLiteRunRegistry(store).mark_cancelled(first.run_id)
    assert admissions.claim_execution(first.run_id) is None
    with pytest.raises(KeyError):
        admissions.get("missing")


def test_closed_session_and_legacy_writer_are_rejected(tmp_path: Path) -> None:
    """持久受理与旧 Run 写入互斥且服从关闭屏障。参数：目录。返回：无。异常：断言失败。"""
    store = _store(tmp_path)
    admissions = SQLiteAgentAdmissionStore(store)
    admissions.admit("request", _contract("session"), expected_epoch=0)
    with pytest.raises(AgentAdmissionBusyError):
        SQLiteRunRegistry(store).register_run(session_id="session", service_type="legacy")
    store.get_connection().execute("UPDATE sessions SET state='closed' WHERE session_id='session'")
    with pytest.raises(SessionWriteBlockedError):
        admissions.session_epoch("session")
    with pytest.raises(SessionWriteBlockedError):
        admissions.admit("new", _contract("session"), expected_epoch=0)
    with pytest.raises(KeyError):
        admissions.session_epoch("missing")


def _concurrent_admit(path: Path) -> AgentTurnAdmission:
    """在线程独立连接中受理。参数：库路径。返回：受理。异常：存储错误。"""
    store = HostStore(path)
    store.initialize_schema()
    try:
        return SQLiteAgentAdmissionStore(store).admit("concurrent", _contract("session"), expected_epoch=0)
    finally:
        store.close()


def test_concurrent_admission_creates_one_run(tmp_path: Path) -> None:
    """跨实例并发重试只能提交一个 Run。参数：目录。返回：无。异常：断言失败。"""
    store = _store(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as executor:
        admitted = list(executor.map(_concurrent_admit, [tmp_path / "host.db"] * 4))
    assert len({item.run_id for item in admitted}) == 1
    assert len(SQLiteRunRegistry(store).list_runs()) == 1


def test_accepted_turn_survives_acceptor_process_exit(tmp_path: Path) -> None:
    """受理进程退出后另一进程可领取未启动 Run。参数：目录。返回：无。异常：断言失败。"""
    store = _store(tmp_path)
    with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as executor:
        admitted = executor.submit(_concurrent_admit, tmp_path / "host.db").result(timeout=30)
    admissions = SQLiteAgentAdmissionStore(store)
    assert admissions.admit("concurrent", _contract("session"), expected_epoch=0) == admitted
    lease = admissions.claim_execution(admitted.run_id)
    assert lease is not None
    admissions.release_execution(admitted.run_id, lease)


class _CompletingExecutor:
    """确定性执行器，验证受理组件收尾而不调用模型。"""

    def __init__(self, runs: SQLiteRunRegistry, *, fail: bool = False) -> None:
        """设置执行行为。参数：Run 仓储、是否失败。返回：无。异常：无。"""
        self.runs = runs
        self.calls = 0
        self.released = False
        self.fail = fail

    async def run_admitted_agent_stream(
        self, execution_contract: ExecutionContract, *, run_id: str, pending_turn_id: str,
    ) -> AsyncGenerator[AppEvent, None]:
        """产出确定结果。参数：契约、Run、pending ID。返回：流。异常：按测试设置失败。"""
        del execution_contract, pending_turn_id
        self.calls += 1
        self.runs.start_run(run_id)
        try:
            if self.fail:
                raise RuntimeError("模拟执行失败")
            yield AppEvent(AppEventType.WARNING, {"message": "缺口"})
            yield AppEvent(AppEventType.FINAL_ANSWER, {"content": "报告"})
            self.runs.complete_run(run_id)
        finally:
            self.released = True


@pytest.mark.asyncio
async def test_result_replay_does_not_execute_twice(tmp_path: Path) -> None:
    """结果跨实例可读且不重跑 Agent。参数：目录。返回：无。异常：断言失败。"""
    store = _store(tmp_path)
    admissions = SQLiteAgentAdmissionStore(store)
    first = admissions.admit("request", _contract("session"), expected_epoch=0)
    executor = _CompletingExecutor(SQLiteRunRegistry(store))
    runtime = HostAgentAdmissionRuntime(admissions, executor, executor.runs)
    assert len([event async for event in runtime.run_stream(first.run_id)]) == 2
    assert executor.released and executor.calls == 1
    replay = [event async for event in runtime.run_stream(first.run_id)]
    assert replay[0].payload["content"] == "报告"
    assert executor.calls == 1
    assert admissions.read_result(first.run_id) == AppResult("报告", [], ["缺口"])


@pytest.mark.asyncio
async def test_closing_consumer_cancels_run_and_releases_lease(tmp_path: Path) -> None:
    """消费者断开不会留活跃 Run 或租约。参数：目录。返回：无。异常：断言失败。"""
    store = _store(tmp_path)
    admissions = SQLiteAgentAdmissionStore(store)
    first = admissions.admit("request", _contract("session"), expected_epoch=0)
    executor = _CompletingExecutor(SQLiteRunRegistry(store))
    runtime = HostAgentAdmissionRuntime(admissions, executor, executor.runs)
    stream = runtime.run_stream(first.run_id)
    await anext(stream)
    await stream.aclose()
    run = executor.runs.get_run(first.run_id)
    assert executor.released and run is not None and run.state == RunState.CANCELLED
    assert store.get_connection().execute("SELECT executor_lease_id FROM agent_admissions").fetchone()[0] is None
    assert [event.type async for event in runtime.run_stream(first.run_id)] == [AppEventType.CANCELLED]


@pytest.mark.asyncio
async def test_runtime_failure_settles_and_needs_explicit_recovery(tmp_path: Path) -> None:
    """执行异常不留下活跃 Run 或自动重跑。参数：目录。返回：无。异常：断言失败。"""
    store = _store(tmp_path)
    admissions = SQLiteAgentAdmissionStore(store)
    first = admissions.admit("request", _contract("session"), expected_epoch=0)
    executor = _CompletingExecutor(SQLiteRunRegistry(store), fail=True)
    runtime = HostAgentAdmissionRuntime(admissions, executor, executor.runs)
    with pytest.raises(RuntimeError, match="模拟执行失败"):
        _ = [event async for event in runtime.run_stream(first.run_id)]
    assert executor.released
    with pytest.raises(AgentAdmissionRecoveryRequiredError):
        _ = [event async for event in runtime.run_stream(first.run_id)]


async def _report_events() -> AsyncGenerator[AppEvent, None]:
    """提供无网络报告流。参数：无。返回：流。异常：无。"""
    yield AppEvent(AppEventType.FINAL_ANSWER, {"content": "正式报告"})


class _Scene:
    """只替换模型输入准备，保留真实 Host 治理边界。"""

    async def prepare(self, execution_contract: ExecutionContract, run_context: HostedRunContext) -> PreparedAgentExecution:
        """准备确定输入。参数：契约、上下文。返回：准备结果。异常：无。"""
        session_id = execution_contract.host_policy.session_key or "session"
        agent_input = AgentInput("sys", [], cancellation_handle=run_context.cancellation_token)
        snapshot = PreparedAgentTurnSnapshot(
            service_name=execution_contract.service_name, scene_name=execution_contract.scene_name,
            metadata=execution_contract.metadata, business_concurrency_lane=None, timeout_ms=None,
            resumable=True, system_prompt="sys", messages=[], agent_create_args=agent_input.agent_create_args,
            selected_toolsets=(), execution_permissions=execution_contract.preparation_spec.execution_permissions,
            toolset_configs=(), trace_settings=None, conversation_memory_settings=ConversationMemorySettings(),
            conversation_session=PreparedConversationSessionSnapshot(session_id, execution_contract.message_inputs.user_message or "",
                                                                     ConversationTranscript.create_empty(session_id)),
        )
        return PreparedAgentExecution(agent_input, snapshot)

    async def restore_prepared_execution(self, prepared_turn: PreparedAgentTurnSnapshot, run_context: HostedRunContext) -> AgentInput:
        """声明准备协议。参数：快照、上下文。返回：输入。异常：本测试不恢复，抛 NotImplementedError。"""
        raise NotImplementedError("此用例不恢复模型执行")


@pytest.mark.asyncio
async def test_host_public_durable_path_uses_existing_lifecycle(tmp_path: Path, mocker: MockerFixture) -> None:
    """公开受理路径复用现有执行治理。参数：目录、mock。返回：无。异常：断言失败。"""
    mocker.patch("alpha.host.host._build_default_scene_preparation", return_value=_Scene())
    host = Host(host_store_path=tmp_path / "host.db")
    host.ensure_session("session", SessionSource.API)
    first = host.admit_agent_turn("request", _contract("session"), expected_epoch=host.get_session_admission_epoch("session"))
    assert host.find_agent_admission("session", "request") == first
    # 本用例只隔离模型准备和模型流，实际 Run/取消桥/permit/持久受理不替换。
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", return_value=_report_events())
    events = [event async for event in host.run_admitted_turn_stream(first.run_id)]
    assert events[0].type == AppEventType.FINAL_ANSWER
    assert host.get_admitted_agent_result(first.run_id) == AppResult("正式报告", [], [])
    assert not host.list_active_runs()
    assert all(status.active == 0 for status in host.get_all_lane_statuses().values())
    assert [event async for event in host.run_admitted_turn_stream(first.run_id)][0].payload["content"] == "正式报告"
    second = host.admit_agent_turn("second", _contract("session", "下一轮"), expected_epoch=0)
    host.stop_session_admissions("session", "stop2")
    assert [event.type async for event in host.run_admitted_turn_stream(second.run_id)] == [AppEventType.CANCELLED]
    host.cleanup_stale_pending_turns(session_id="session")
    assert host.get_session_pending_turn(session_id="session", scene_name="research") is None


def test_dead_terminal_execution_lease_does_not_block_legacy_writer(tmp_path: Path) -> None:
    """已终态死亡执行者不永久占用 Session。参数：目录。返回：无。异常：断言失败。"""
    store = _store(tmp_path)
    admissions = SQLiteAgentAdmissionStore(store)
    first = admissions.admit("request", _contract("session"), expected_epoch=0)
    admissions.claim_execution(first.run_id)
    SQLiteRunRegistry(store).mark_cancelled(first.run_id)
    store.get_connection().execute("UPDATE agent_admissions SET executor_pid=?,executor_start_time=NULL,executor_boot_id=NULL",
                                   (_DEAD_OWNER_PID,))
    legacy = SQLiteRunRegistry(store).register_run(session_id="session", service_type="legacy")
    assert legacy.state == RunState.CREATED


def test_durable_resume_rebinds_pending_and_deduplicates_request(tmp_path: Path) -> None:
    """恢复受理原子登记新 Run 并保留原快照。参数：目录。返回：无。异常：断言失败。"""
    store = _store(tmp_path)
    admissions = SQLiteAgentAdmissionStore(store)
    original = admissions.admit("original", _contract("session"), expected_epoch=0)
    runs = SQLiteRunRegistry(store)
    runs.start_run(original.run_id)
    runs.fail_run(original.run_id, error_summary="断线")
    pending_store = SQLitePendingConversationTurnStore(store)
    before = pending_store.get_pending_turn(original.pending_turn_id)
    restored = admissions.admit_resume(original.run_id, "resume", expected_epoch=0, max_attempts=3)
    assert restored.run_id != original.run_id and restored.pending_turn_id == original.pending_turn_id
    assert admissions.admit_resume(original.run_id, "resume", expected_epoch=0, max_attempts=3) == restored
    after = pending_store.get_pending_turn(original.pending_turn_id)
    assert before is not None and after is not None
    assert after.resume_source_json == before.resume_source_json and after.source_run_id == restored.run_id
    assert after.resume_attempt_count == 1
    restored_run = runs.get_run(restored.run_id)
    assert restored_run is not None and restored_run.state == RunState.CREATED
    with pytest.raises(AgentAdmissionConflictError):
        admissions.admit_resume(restored.run_id, "resume", expected_epoch=0, max_attempts=3)
    with pytest.raises(AgentAdmissionConflictError):
        admissions.admit_resume(restored.run_id, "another", expected_epoch=0, max_attempts=3)


@pytest.mark.parametrize("failure", ["empty_key", "stale", "missing", "resuming", "limit", "invalid_snapshot", "resources_held"])
def test_durable_resume_rejects_unsafe_sources(tmp_path: Path, failure: str) -> None:
    """不安全恢复不会留下新 Run。参数：目录、故障类型。返回：无。异常：断言失败。"""
    store = _store(tmp_path)
    admissions = SQLiteAgentAdmissionStore(store)
    original = admissions.admit("original", _contract("session"), expected_epoch=0)
    runs = SQLiteRunRegistry(store)
    runs.start_run(original.run_id)
    runs.fail_run(original.run_id, error_summary="断线")
    conn = store.get_connection()
    request_key = "" if failure == "empty_key" else "resume"
    if failure == "missing":
        conn.execute("DELETE FROM pending_conversation_turns")
    elif failure == "resuming":
        conn.execute("UPDATE pending_conversation_turns SET state='resuming'")
    elif failure == "limit":
        conn.execute("UPDATE pending_conversation_turns SET resume_attempt_count=3")
    elif failure == "invalid_snapshot":
        conn.execute("UPDATE pending_conversation_turns SET resume_source_json='{}'")
    elif failure == "resources_held":
        # 用真实身份占有资源；失败 Run 的资源尚未释放时仍然拒绝新的写执行。
        from alpha.process_liveness import current_owner_identity

        owner = current_owner_identity()
        conn.execute("UPDATE agent_admissions SET executor_lease_id='held',executor_pid=?,executor_start_time=?,executor_boot_id=?",
                     (owner.pid, owner.process_start_time, owner.boot_id))
    error = {"empty_key": ValueError, "stale": AgentAdmissionStaleError, "missing": AgentAdmissionRecoveryRequiredError,
             "resuming": AgentAdmissionBusyError, "limit": AgentAdmissionRecoveryRequiredError,
             "invalid_snapshot": ValueError, "resources_held": AgentAdmissionBusyError}[failure]
    with pytest.raises(error):
        admissions.admit_resume(original.run_id, request_key, expected_epoch=1 if failure == "stale" else 0, max_attempts=3)
    assert len(runs.list_runs()) == 1


def test_unclaimed_admission_survives_aged_acceptor_exit(tmp_path: Path) -> None:
    """从未开始的持久输入不能被普通 owner 孤儿清理吸收。参数：目录。返回：无。异常：断言失败。"""
    from datetime import datetime, timedelta, timezone

    store = _store(tmp_path)
    admissions = SQLiteAgentAdmissionStore(store)
    admitted = admissions.admit("accepted", _contract("session"), expected_epoch=0)
    store.get_connection().execute("UPDATE runs SET owner_pid=?,owner_process_start_time=NULL,owner_boot_id=NULL,created_at=? WHERE run_id=?",
                                   (_DEAD_OWNER_PID, (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), admitted.run_id))
    assert SQLiteRunRegistry(store).cleanup_orphan_runs() == []
    assert admissions.claim_execution(admitted.run_id) is not None


def test_confirmed_dead_durable_executor_does_not_wait_ten_minutes(tmp_path: Path) -> None:
    """租约确认执行者死亡后应立即开放显式恢复。参数：目录。返回：无。异常：断言失败。"""
    store = _store(tmp_path)
    admissions = SQLiteAgentAdmissionStore(store)
    admitted = admissions.admit("accepted", _contract("session"), expected_epoch=0)
    assert admissions.claim_execution(admitted.run_id) is not None
    registry = SQLiteRunRegistry(store)
    registry.start_run(admitted.run_id)
    conn = store.get_connection()
    conn.execute("UPDATE runs SET owner_pid=?,owner_process_start_time=NULL,owner_boot_id=NULL WHERE run_id=?", (_DEAD_OWNER_PID, admitted.run_id))
    conn.execute("UPDATE agent_admissions SET executor_pid=?,executor_start_time=NULL,executor_boot_id=NULL WHERE run_id=?", (_DEAD_OWNER_PID, admitted.run_id))
    assert registry.cleanup_orphan_runs() == [admitted.run_id]
    resumed = admissions.admit_resume(admitted.run_id, "resume", expected_epoch=0, max_attempts=3)
    assert resumed.run_id != admitted.run_id
