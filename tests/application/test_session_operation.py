"""外部 coding agent 操作共享 Session 写互斥和停止边界。"""

from pathlib import Path

import pytest

from alpha.contracts.host_admission import AgentAdmissionBusyError, AgentAdmissionStaleError
from alpha.contracts.host_execution import HostedRunContext, HostedRunSpec
from alpha.contracts.run import RunState
from alpha.contracts.session import SessionSource
from alpha.host.host import Host

_INPUT_HASH = "a" * 64


def _complete(context: HostedRunContext) -> str:
    """消费宿主取消真源。参数：上下文。返回：结果。异常：取消。"""
    context.cancellation_token.raise_if_cancelled()
    return "done"


def test_session_operations_are_exclusive_and_fenced(tmp_path: Path) -> None:
    """另一实例不得占用相同研究，停止后的旧代际不得受理。参数：目录。返回：无。异常：断言失败。"""
    path = tmp_path / "host.db"
    host = Host(host_store_path=path)
    host.ensure_session("research", SessionSource.API)
    spec = HostedRunSpec("external_research", session_id="research")
    admission = host.admit_session_operation("first", spec, _INPUT_HASH, expected_epoch=0)
    assert host.admit_session_operation("first", spec, _INPUT_HASH, expected_epoch=0) == admission
    other = Host(host_store_path=path)
    with pytest.raises(AgentAdmissionBusyError):
        other.admit_session_operation("second", spec, _INPUT_HASH, expected_epoch=0)
    assert other.run_admitted_operation_sync(admission.run_id, _complete) == "done"
    host.stop_session_admissions("research", "stop")
    with pytest.raises(AgentAdmissionStaleError):
        host.admit_session_operation("stale", spec, _INPUT_HASH, expected_epoch=0)
    next_admission = host.admit_session_operation("next", spec, _INPUT_HASH, expected_epoch=1)
    host.stop_session_admissions("research", "stop-again")
    run = host.get_run(next_admission.run_id)
    assert run is not None and run.state == RunState.CANCELLED
