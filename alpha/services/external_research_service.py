"""外部 coding agent 的研究入口，复用同一研究服务和 Host 生命周期。"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import uuid4
from typing import cast

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research import ResearchExecutionMode, ResearchRevision, ResearchTurn, ResearchTurnState, ResumeResearchTurnRequest, SubmitResearchTurnRequest
from alpha.contracts.run import RunState, TERMINAL_STATES
from alpha.contracts.research_financials import encode_financial_requirements
from alpha.contracts.protocols import ToolExecutor
from alpha.services.external_execution import ExternalExecution
from alpha.services.research_service import ResearchService

_MAX_OPEN_SESSIONS = 8


@dataclass(frozen=True)
class _Connection:
    """一次 stdio 连接内的不可猜测执行句柄。"""

    research_id: str
    turn_id: str
    owner_id: str
    execution: ExternalExecution


@dataclass
class ExternalResearchService:
    """每个研究持有一个工具序列；断线请求 Host 取消并等待资源收尾。"""

    research: ResearchService
    registry_factory: Callable[[], ToolExecutor]
    _connections: dict[str, _Connection] = field(default_factory=dict)
    _submitted: dict[str, tuple[str, str]] = field(default_factory=dict)

    async def begin(self, request: SubmitResearchTurnRequest) -> dict[str, JsonValue]:
        """接受外部研究，稳定请求重放复用当前句柄。参数：外部请求。返回：句柄和固定来源。异常：模式、所有权或繁忙。"""
        if request.execution_mode != ResearchExecutionMode.EXTERNAL:
            raise ValueError("外部入口必须显式选择 external 模式")
        turn = self.research.submit(request)
        run = self.research.host.get_run(turn.run_id) if turn.run_id is not None else None
        if turn.state == ResearchTurnState.SETTLED or (run is not None and run.state in TERMINAL_STATES):
            return self._settled(turn, request.owner_id)
        for handle, connection in self._connections.items():
            if connection.turn_id == turn.turn_id and not connection.execution.completed.done():
                return self._describe(handle, connection)
        return await self.attach(turn.research_id, request.owner_id)

    async def resume(self, request: ResumeResearchTurnRequest) -> dict[str, JsonValue]:
        """显式恢复原外部研究。参数：原输入、用户、恢复键。返回：新执行句柄。异常：不可恢复。"""
        original = self.research.turn_details(request.turn_id, request.owner_id)
        if original.execution_mode != ResearchExecutionMode.EXTERNAL:
            raise ValueError("原输入不是外部执行")
        turn = self.research.resume(request)
        if turn.state == ResearchTurnState.SETTLED:
            return self._settled(turn, request.owner_id)
        return await self.attach(turn.research_id, request.owner_id)

    def _settled(self, turn: ResearchTurn, owner_id: str) -> dict[str, JsonValue]:
        """重复控制请求返回原结果，不重新占用执行。参数：输入、用户。返回：原状态及可选版本。异常：版本调和失败。"""
        revision = self.research.finalize(turn.turn_id, owner_id)
        run = self.research.host.get_run(turn.run_id) if turn.run_id is not None else None
        return {"turn_id": turn.turn_id, "run_id": turn.run_id, "state": run.state.value if run is not None else None,
                "completed": revision is not None, "revision_id": revision.revision_id if revision is not None else None}

    async def attach(self, research_id: str, owner_id: str) -> dict[str, JsonValue]:
        """领取已经受理的外部输入。参数：研究、用户。返回：执行句柄。异常：繁忙、停止或执行失败。"""
        if sum(not item.execution.completed.done() for item in self._connections.values()) >= _MAX_OPEN_SESSIONS:
            raise ValueError("当前连接的活跃研究达到上限")
        turn = self.research.dispatch_external(research_id, owner_id)
        assert turn.run_id is not None
        execution = ExternalExecution(self.research.host, turn.run_id, self.registry_factory())
        handle = "external_" + uuid4().hex
        connection = _Connection(research_id, turn.turn_id, owner_id, execution)
        self._connections[handle] = connection
        execution.start()
        try:
            await asyncio.shield(asyncio.wrap_future(execution.ready))
        except asyncio.CancelledError:
            self.research.stop(research_id, owner_id, "external-open-failed:" + handle)
            await asyncio.shield(asyncio.gather(asyncio.wrap_future(execution.completed), return_exceptions=True))
            self.research.finalize(turn.turn_id, owner_id)
            raise
        except Exception:
            await asyncio.gather(asyncio.wrap_future(execution.completed), return_exceptions=True)
            self._connections.pop(handle)
            raise
        return self._describe(handle, connection)

    def _describe(self, handle: str, connection: _Connection) -> dict[str, JsonValue]:
        """返回外部控制面来源。参数：句柄、连接。返回：固定身份与工具目录。异常：无。"""
        turn = self.research.turn_details(connection.turn_id, connection.owner_id)
        overview = self.research.overview(connection.research_id, connection.owner_id)
        return {"handle": handle, "research_id": connection.research_id, "turn_id": connection.turn_id,
                "run_id": connection.execution.run_id,
                "question": overview.research.question, "as_of": turn.as_of.isoformat(), "method_hash": turn.preparation.method_hash,
                "financial_requirements": encode_financial_requirements(turn.financial_requirements), "publication_policy": turn.publication_policy.value,
                "publication_target_id": turn.publication_target_id,
                "tools": cast(list[JsonValue], connection.execution.registry.get_schemas())}

    async def call(self, handle: str, name: str, arguments: dict[str, JsonValue], call_id: str) -> dict[str, JsonValue]:
        """在 Host 工作线程调用工具。参数：句柄、工具、参数、稳定调用 ID。返回：工具结果。异常：取消、断线或冲突。"""
        connection = self._connections[handle]
        pending = asyncio.wrap_future(connection.execution.call(name, arguments, call_id))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            await asyncio.shield(self.abort(handle))
            await asyncio.gather(pending, return_exceptions=True)
            raise

    async def finish(self, handle: str, candidate_id: str, expected_hash: str, call_id: str) -> ResearchRevision | dict[str, JsonValue]:
        """提交指定候选并等待 Host 成功后形成版本。参数：句柄、候选、hash、调用键。返回：版本或字段错误。异常：取消或结束冲突。"""
        connection = self._connections[handle]
        submitted = self._submitted.get(handle)
        if submitted is not None and submitted != (candidate_id, expected_hash):
            raise ValueError("本执行已经提交另一个固定候选稿")
        if connection.execution.completed.done():
            run = self.research.host.get_run(connection.execution.run_id)
            if run is not None and run.state == RunState.SUCCEEDED:
                revision = self.research.finalize(connection.turn_id, connection.owner_id)
                assert revision is not None
                return revision
            raise RuntimeError("外部执行已终止；请显式恢复或开启下一轮")
        try:
            future = connection.execution.call("research_commit_candidate", {"candidate_id": candidate_id, "content_hash": expected_hash}, call_id, finish_after_submission=True)
            result = await asyncio.shield(asyncio.wrap_future(future))
        except asyncio.CancelledError:
            await asyncio.shield(self.abort(handle))
            raise
        value = result.get("value")
        if result.get("ok") is not True or not isinstance(value, dict) or value.get("submitted") is not True:
            return result
        self._submitted[handle] = candidate_id, expected_hash
        try:
            await asyncio.shield(asyncio.wrap_future(connection.execution.completed))
        except asyncio.CancelledError:
            await asyncio.shield(self.abort(handle))
            raise
        revision = self.research.finalize(connection.turn_id, connection.owner_id)
        assert revision is not None
        return revision

    async def abort(self, handle: str) -> None:
        """停止当前连接拥有的执行并保留检查点。参数：句柄。返回：无。异常：存储或收尾错误。"""
        connection = self._connections[handle]
        if not connection.execution.completed.done():
            self.research.stop(connection.research_id, connection.owner_id, "external-disconnect:" + handle)
        await asyncio.shield(asyncio.gather(asyncio.wrap_future(connection.execution.completed), return_exceptions=True))
        self.research.finalize(connection.turn_id, connection.owner_id)

    async def close(self) -> None:
        """断开时收敛所有本连接的执行。参数：无。返回：无。异常：存储错误传播。"""
        await asyncio.gather(*(self.abort(handle) for handle in self._connections))
