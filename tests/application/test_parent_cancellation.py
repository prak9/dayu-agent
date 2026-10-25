"""Host 外层取消和晚注册子执行之间的确定竞争回归。"""

from pathlib import Path

from alpha.contracts.host_execution import HostedRunContext, HostedRunSpec
from alpha.contracts.run import RunState
from alpha.host.host import Host


def test_late_child_after_parent_cancel_never_enters_business_body(tmp_path: Path) -> None:
    """外层取消后登记的子执行不得继续工作。参数：目录。返回：无。异常：断言失败。"""
    host = Host(host_store_path=tmp_path / "host.db")
    entered: list[str] = []

    def child(context: HostedRunContext) -> int:
        """记录副作用。参数：上下文。返回：值。异常：无。"""
        entered.append(context.run_id)
        return 1

    def parent(context: HostedRunContext) -> int:
        """模拟 preflight 后外层收到取消。参数：上下文。返回：子取消结果。异常：无。"""
        context.cancellation_token.cancel()
        return host.run_operation_sync(spec=HostedRunSpec("child"), operation=child, on_cancel=lambda: 130)

    assert host.run_operation_sync(spec=HostedRunSpec("parent"), operation=parent, on_cancel=lambda: 130) == 130
    assert entered == []
    assert not host.list_active_runs()


def test_running_child_observes_parent_token_without_snapshot_poll(tmp_path: Path) -> None:
    """已执行子任务同样级联且保持独立取消终态。参数：目录。返回：无。异常：断言失败。"""
    host = Host(host_store_path=tmp_path / "host.db")
    child_ids: list[str] = []

    def parent(context: HostedRunContext) -> int:
        """持有父令牌进入子任务。参数：上下文。返回：取消结果。异常：无。"""
        def child(child_context: HostedRunContext) -> int:
            """在执行中触发外层停止。参数：子上下文。返回：不可达值。异常：取消。"""
            child_ids.append(child_context.run_id)
            context.cancellation_token.cancel()
            child_context.cancellation_token.raise_if_cancelled()
            raise AssertionError("子执行没有收到父取消")
        return host.run_operation_sync(spec=HostedRunSpec("child"), operation=child, on_cancel=lambda: 130)

    assert host.run_operation_sync(spec=HostedRunSpec("parent"), operation=parent, on_cancel=lambda: 130) == 130
    child_run = host.get_run(child_ids[0])
    assert child_run is not None and child_run.state == RunState.CANCELLED
