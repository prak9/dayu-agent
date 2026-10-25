"""宿主独立操作执行：原规格、同一 Run、互斥领取和资源收尾。"""

from collections.abc import Callable
from typing import Protocol, TypeVar

from alpha.contracts.host_execution import HostedRunContext, HostedRunSpec
from alpha.contracts.operation_admission import OperationAdmissionBusyError, OperationAdmissionRecoveryRequiredError
from alpha.contracts.run import RunState
from alpha.host.operation_admission_store import SQLiteOperationAdmissionStore
from alpha.host.protocols import RunRegistryProtocol

TResult = TypeVar("TResult")


class AdmittedOperationExecutor(Protocol):
    """既有同步执行治理对持久 Run 的内部能力。"""

    def run_operation_sync(
        self, *, spec: HostedRunSpec, operation: Callable[[HostedRunContext], TResult], admitted_run_id: str | None = None,
    ) -> TResult:
        """运行固定操作。参数：规格、处理函数、已受理 Run。返回：处理结果。异常：取消或执行错误。"""
        ...


class HostOperationAdmissionRuntime:
    """未开始可恢复领取，已完成不重复执行，副作用调和交由业务服务。"""

    def __init__(self, store: SQLiteOperationAdmissionStore, executor: AdmittedOperationExecutor, runs: RunRegistryProtocol) -> None:
        """注入宿主内部依赖。参数：仓储、执行器、Run 端口。返回：无。异常：无。"""
        self.store = store
        self._executor = executor
        self._runs = runs

    def run_sync(self, run_id: str, operation: Callable[[HostedRunContext], TResult]) -> TResult | None:
        """执行一次已接受操作。参数：Run、业务处理函数。返回：本次结果，已成功执行则空。异常：繁忙、需调和或执行错误。"""
        lease = self.store.claim(run_id)
        if lease is None:
            run = self._runs.get_run(run_id)
            if run is None:
                raise KeyError(f"Run 不存在：{run_id}")
            if run.state == RunState.SUCCEEDED:
                return None
            if run.state in (RunState.CREATED, RunState.QUEUED, RunState.RUNNING):
                raise OperationAdmissionBusyError("独立操作正由另一执行者处理")
            raise OperationAdmissionRecoveryRequiredError("独立操作未成功，请先核对业务副作用，再接受新的执行尝试")
        try:
            return self._executor.run_operation_sync(spec=self.store.load_spec(run_id), operation=operation, admitted_run_id=run_id)
        except Exception as exc:
            run = self._runs.get_run(run_id)
            if run is not None and run.state in (RunState.CREATED, RunState.QUEUED, RunState.RUNNING):
                self._runs.fail_run(run_id, error_summary=type(exc).__name__)
            raise
        finally:
            self.store.release(run_id, lease)
