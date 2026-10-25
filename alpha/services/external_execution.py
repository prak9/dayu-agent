"""外部 Agent 的工具工作线程：Host 持有整个执行及取消资源。"""

import queue
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import cast

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.host_execution import HostedRunContext
from alpha.contracts.protocols import ToolExecutionContext, ToolExecutor
from alpha.contracts.research_execution import ResearchExecutionHost
from alpha.research.storage.encoding import canonical_json

_CANCEL_POLL_SECONDS = 0.1
_MAX_CALLS = 2000


@dataclass(frozen=True)
class _Command:
    """单个明确工具调用，可在候选稿提交成功后收尾。"""

    name: str
    arguments: dict[str, JsonValue]
    call_id: str
    result: Future[dict[str, JsonValue]]
    finish_after_submission: bool


@dataclass
class ExternalExecution:
    """仅驱动工具，不调用模型；外部 IDE 的思考生命周期仍属于 IDE。"""

    host: ResearchExecutionHost
    run_id: str
    registry: ToolExecutor
    ready: Future[None] = field(default_factory=Future[None])
    completed: Future[None] = field(default_factory=Future[None])
    _commands: queue.Queue[_Command] = field(default_factory=queue.Queue[_Command])
    _calls: dict[str, tuple[str, Future[dict[str, JsonValue]]]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _finishing: bool = False

    def start(self) -> None:
        """启动宿主工作者。参数：无。返回：无。异常：线程启动错误。"""
        threading.Thread(target=self._run, name="alpha-external-" + self.run_id, daemon=True).start()

    def _run(self) -> None:
        """从原受理进入 Host 并收敛所有等待者。参数：无。返回：无。异常：通过 Future 传播。"""
        try:
            self.host.run_admitted_operation_sync(self.run_id, self._operate)
        except BaseException as exc:
            if not self.ready.done():
                self.ready.set_exception(exc)
            self.completed.set_exception(exc)
        else:
            if not self.ready.done():
                self.ready.set_exception(RuntimeError("原外部执行已结束；请查询版本或显式恢复"))
            self.completed.set_result(None)
        finally:
            with self._lock:
                for _, future in self._calls.values():
                    if not future.done():
                        future.set_exception(RuntimeError("外部执行已结束，拒绝迟到工具请求"))

    def _operate(self, context: HostedRunContext) -> None:
        """串行处理工具并观察 Host 取消。参数：宿主上下文。返回：无。异常：取消或工具基础设施失败。"""
        self.ready.set_result(None)
        while True:
            context.cancellation_token.raise_if_cancelled()
            try:
                command = self._commands.get(timeout=_CANCEL_POLL_SECONDS)
            except queue.Empty:
                continue
            try:
                context.cancellation_token.raise_if_cancelled()
                result = self.registry.execute(command.name, command.arguments, ToolExecutionContext(
                    run_id=context.run_id, tool_call_id=command.call_id, cancellation_token=context.cancellation_token))
                context.cancellation_token.raise_if_cancelled()
                submitted = False
                if command.finish_after_submission:
                    value = result.get("value")
                    submitted = result.get("ok") is True and isinstance(value, dict) and value.get("submitted") is True
                    if not submitted:
                        with self._lock:
                            self._finishing = False
                command.result.set_result(cast(dict[str, JsonValue], result))
                if submitted:
                    return
            except Exception as exc:
                if command.finish_after_submission:
                    with self._lock:
                        self._finishing = False
                command.result.set_exception(exc)

    def call(self, name: str, arguments: dict[str, JsonValue], call_id: str, *, finish_after_submission: bool = False) -> Future[dict[str, JsonValue]]:
        """接受一次工具调用，重放返回原 Future。参数：工具、显式参数、调用 ID、成功提交后是否收尾。返回：结果 Future。异常：冲突、已收尾或超限。"""
        if not name or not call_id.strip():
            raise ValueError("工具名和调用 ID 不能为空")
        fingerprint = canonical_json({"name": name, "arguments": arguments, "finish_after_submission": finish_after_submission})
        with self._lock:
            existing = self._calls.get(call_id)
            if existing is not None:
                if existing[0] != fingerprint:
                    raise ValueError("同一外部调用 ID 的参数发生变化")
                return existing[1]
            if self._finishing or self.completed.done():
                raise RuntimeError("外部执行已结束或正在收尾")
            if len(self._calls) >= _MAX_CALLS:
                raise ValueError("本轮工具调用达到上限，请保存检查点后开启下一轮")
            future: Future[dict[str, JsonValue]] = Future()
            self._calls[call_id] = fingerprint, future
            self._finishing = finish_after_submission
            self._commands.put(_Command(name, arguments, call_id, future, finish_after_submission))
            return future
