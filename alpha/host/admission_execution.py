"""执行已受理 Agent 输入；领取、结果保存和资源收尾均留在 Host。"""

from __future__ import annotations

import asyncio
from contextlib import aclosing
from typing import AsyncGenerator, Protocol, cast

from alpha.contracts.agent_execution import ExecutionContract
from alpha.contracts.agent_types import JsonValue
from alpha.contracts.events import AppEvent, AppEventType, AppResult
from alpha.contracts.host_admission import AgentAdmissionBusyError, AgentAdmissionRecoveryRequiredError
from alpha.contracts.run import RunState, TERMINAL_STATES
from alpha.host.admission_store import SQLiteAgentAdmissionStore
from alpha.host.protocols import RunRegistryProtocol


class AdmittedAgentExecutor(Protocol):
    """Host 内部执行已登记 Run 的窄能力。"""

    def run_admitted_agent_stream(
        self, execution_contract: ExecutionContract, *, run_id: str, pending_turn_id: str,
    ) -> AsyncGenerator[AppEvent, None]:
        """执行已受理输入。参数：契约及持久身份。返回：事件流。异常：执行失败。"""
        ...


def _event_message(payload: JsonValue) -> str:
    """提取事件提示。参数：JSON 负载。返回：文本。异常：无。"""
    if isinstance(payload, dict):
        return str(payload.get("message") or "")
    return payload if isinstance(payload, str) else ""


class HostAgentAdmissionRuntime:
    """在执行流外保留受理和模型结果，支持业务提交前中断后的读取。"""

    def __init__(self, store: SQLiteAgentAdmissionStore, executor: AdmittedAgentExecutor, runs: RunRegistryProtocol) -> None:
        """注入 Host 内部组件。参数：受理仓储、执行器、Run 注册表。返回：无。异常：无。"""
        self.store = store
        self._executor = executor
        self._runs = runs

    async def run_stream(self, run_id: str) -> AsyncGenerator[AppEvent, None]:
        """执行或读取正式结果。参数：Run。返回：事件流。异常：繁忙、需要恢复或执行失败。"""
        admission = self.store.get(run_id)
        lease = self.store.claim_execution(run_id)
        if lease is None:
            run = self._runs.get_run(run_id)
            if run is None:
                raise KeyError(f"Run 不存在：{run_id}")
            if run.state not in TERMINAL_STATES:
                raise AgentAdmissionBusyError("另一个执行者正在处理本受理，可订阅 Host 进度")
            if run.state == RunState.CANCELLED:
                yield AppEvent(AppEventType.CANCELLED, {"cancel_reason": run.cancel_reason.value if run.cancel_reason else ""})
                return
            result = self.store.read_result(run_id)
            if run.state != RunState.SUCCEEDED or result is None:
                raise AgentAdmissionRecoveryRequiredError("执行未成功完成，请显式恢复 pending turn")
            yield AppEvent(AppEventType.FINAL_ANSWER, {"content": result.content, "degraded": result.degraded, "filtered": result.filtered})
            yield AppEvent(AppEventType.DONE, {})
            return
        result = AppResult(content="", errors=[], warnings=[])
        try:
            stream = self._executor.run_admitted_agent_stream(
                self.store.load_contract(run_id), run_id=run_id, pending_turn_id=admission.pending_turn_id,
            )
            async with aclosing(stream):
                async for event in stream:
                    payload = cast(JsonValue, event.payload)
                    if event.type == AppEventType.FINAL_ANSWER:
                        if not isinstance(payload, dict) or not isinstance(payload.get("content"), str):
                            raise ValueError("正式结果缺少文本 content")
                        result.content = cast(str, payload["content"])
                        result.degraded = payload.get("degraded") is True
                        result.filtered = payload.get("filtered") is True
                        # 先存结果再向外 yield；业务层断开不会导致已完成报告丢失。
                        self.store.record_result(run_id, lease, result)
                    elif event.type == AppEventType.WARNING:
                        result.warnings.append(_event_message(payload))
                    elif event.type == AppEventType.ERROR:
                        result.errors.append(_event_message(payload))
                    yield event
            self.store.record_result(run_id, lease, result)
        except (asyncio.CancelledError, GeneratorExit):
            # 内层 aclosing 已先释放执行资源，再把外层断开收敛为主动取消。
            run = self._runs.get_run(run_id)
            if run is not None and run.state not in TERMINAL_STATES:
                self._runs.request_cancel(run_id)
                self._runs.mark_cancelled(run_id)
            raise
        except Exception as exc:
            run = self._runs.get_run(run_id)
            if run is not None and run.state not in TERMINAL_STATES:
                self._runs.fail_run(run_id, error_summary=str(exc))
            raise
        finally:
            self.store.release_execution(run_id, lease)
