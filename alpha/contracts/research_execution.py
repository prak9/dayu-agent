"""研究服务消费的 Host 窄能力及聚合视图。"""

from dataclasses import dataclass
from typing import AsyncGenerator, Protocol
from collections.abc import Callable

from alpha.contracts.agent_execution import ExecutionContract
from alpha.contracts.events import AppEvent, AppResult
from alpha.contracts.host_admission import AgentTurnAdmission
from alpha.contracts.research import ResearchRecord, ResearchRevision, ResearchTurn
from alpha.contracts.run import RunRecord
from alpha.contracts.session import SessionRecord, SessionSource
from alpha.contracts.host_execution import HostedRunContext, HostedRunSpec
from alpha.contracts.operation_admission import OperationAdmission


@dataclass(frozen=True)
class ResearchOverview:
    """研究详情，执行状态按需从 Host 读取。"""

    research: ResearchRecord
    active_turn: ResearchTurn | None
    run: RunRecord | None
    revisions: tuple[ResearchRevision, ...]
    queued_count: int
    latest_turn: ResearchTurn | None
    execution_turn: ResearchTurn | None


class ResearchExecutionHost(Protocol):
    """仅声明研究业务需要的宿主能力，不引用 UI 或业务实现。"""

    def ensure_session(self, session_id: str, source: SessionSource, *, scene_name: str | None = None) -> SessionRecord:
        """确保会话。参数：固定身份、来源、场景。返回：会话。异常：会话冲突。"""
        ...

    def get_session_admission_epoch(self, session_id: str) -> int:
        """读取代际。参数：会话。返回：代际。异常：不存在。"""
        ...

    def admit_agent_turn(self, request_key: str, execution_contract: ExecutionContract, *, expected_epoch: int) -> AgentTurnAdmission:
        """持久受理。参数：稳定键、契约、代际。返回：受理。异常：冲突、繁忙或过期。"""
        ...

    def find_agent_admission(self, session_id: str, request_key: str) -> AgentTurnAdmission | None:
        """查找受理。参数：会话、键。返回：受理或空。异常：存储错误。"""
        ...

    def admit_agent_resume(self, source_run_id: str, request_key: str, *, expected_epoch: int) -> AgentTurnAdmission:
        """持久接受显式恢复。参数：原 Run、稳定键、代际。返回：受理。异常：冲突或不可恢复。"""
        ...

    def get_admitted_agent_result(self, run_id: str) -> AppResult | None:
        """读取持久结果。参数：Run。返回：结果或空。异常：不存在。"""
        ...

    def stop_session_admissions(self, session_id: str, request_key: str) -> int:
        """停止当前边界。参数：会话、稳定键。返回：代际。异常：不存在。"""
        ...

    def run_admitted_turn_stream(self, run_id: str) -> AsyncGenerator[AppEvent, None]:
        """执行已受理输入。参数：Run。返回：事件流。异常：繁忙或需显式恢复。"""
        ...

    def get_run(self, run_id: str) -> RunRecord | None:
        """读取状态真源。参数：Run。返回：记录或空。异常：存储错误。"""
        ...

    def admit_session_operation(self, request_key: str, spec: HostedRunSpec, input_hash: str, *, expected_epoch: int) -> OperationAdmission:
        """受理外部驱动执行。参数：请求、规格、摘要、代际。返回：Run。异常：繁忙或过期。"""
        ...

    def find_operation_admission(self, request_key: str) -> OperationAdmission | None:
        """查询原外部操作。参数：稳定键。返回：受理或空。异常：数据库错误。"""
        ...

    def run_admitted_operation_sync(self, run_id: str, operation: Callable[[HostedRunContext], None]) -> None:
        """执行外部驱动的受理。参数：Run、操作。返回：无。异常：取消或执行失败。"""
        ...
