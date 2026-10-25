"""外部入口实际 Service/Host/工具闭环，模型调用属于外部 coding agent。"""

from pathlib import Path
from functools import partial
from dataclasses import dataclass, replace
from collections.abc import Callable
from typing import ClassVar
from threading import Event
import asyncio

import pytest
from pytest_mock import MockerFixture

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.host_execution import HostedRunContext, HostedRunSpec
from alpha.contracts.host_admission import AgentAdmissionBusyError
from alpha.contracts.operation_admission import OperationAdmissionBusyError
from alpha.contracts.research import CreateResearchRequest, ResearchExecutionMode, ResearchRevision, SubmitResearchTurnRequest
from alpha.contracts.research import ResumeResearchTurnRequest
from alpha.contracts.research import ResearchConflictError, ResearchPublicationPolicy
from alpha.contracts.protocols import ToolExecutionContext, ToolExecutor
from alpha.engine.tool_registry import ToolRegistry
from alpha.contracts.cancellation import CancellationToken
from alpha.engine.tools.base import ToolExtra
from alpha.research.tools import _extra, _schema
from alpha.contracts.run import RunState
from alpha.startup.external_research import prepare_external_research
from alpha.services.external_research_service import ExternalResearchService
from alpha.services.research_preparation import prepare_research_service
from alpha.services.startup_preparation import prepare_host_runtime_dependencies
from alpha.services.publication_service import PublicationService


def _external(path: Path) -> ExternalResearchService:
    """装配真实外部入口。参数：工作区。返回：服务。异常：装配错误。"""
    dependencies = prepare_host_runtime_dependencies(workspace_root=path, config_root=None, execution_options=None, runtime_label="test-external", log_module="TEST")
    return prepare_external_research(path, prepare_research_service(path, dependencies))


def _value(result: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """收窄公开工具结果。参数：结果。返回：对象。异常：断言失败。"""
    value = result.get("value")
    assert result.get("ok") is True and isinstance(value, dict), result
    return value


@pytest.mark.asyncio
async def test_direct_agent_uses_tools_and_commits_without_starting_a_model(tmp_path: Path, mocker: MockerFixture) -> None:
    """从公开外部服务产生真实不可变版本，重复完成不重跑。参数：目录、mock。返回：无。异常：断言失败。"""
    external = _external(tmp_path)
    forbidden = mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", side_effect=AssertionError("外部入口不得启动模型"))
    research = external.research.create(CreateResearchRequest("local", "create", "研究方法"))
    request = SubmitResearchTurnRequest(research.research_id, "local", "begin", "直接分析", execution_mode=ResearchExecutionMode.EXTERNAL)
    opened = await external.begin(request)
    handle = str(opened["handle"])
    assert await external.begin(request) == opened
    note = await external.call(handle, "research_save_note", {"title": "阶段", "content": "待核验"}, "note")
    assert await external.call(handle, "research_save_note", {"title": "阶段", "content": "待核验"}, "note") == note
    with pytest.raises(ValueError, match="发生变化"):
        await external.call(handle, "research_save_note", {"title": "阶段", "content": "变化"}, "note")
    draft = _value(await external.call(handle, "research_draft_report", {"report_markdown": "# 已核验结论"}, "draft"))
    result = await external.finish(handle, str(draft["candidate_id"]), str(draft["content_hash"]), "finish")
    assert isinstance(result, ResearchRevision)
    assert external.research.read_report(result.revision_id, "local") == "# 已核验结论"
    assert await external.finish(handle, str(draft["candidate_id"]), str(draft["content_hash"]), "finish") == result
    assert (await external.begin(request))["revision_id"] == result.revision_id
    with pytest.raises(ValueError, match="固定候选稿"):
        await external.finish(handle, "another-candidate", "another-hash", "changed-finish")
    assert forbidden.call_count == 0
    with pytest.raises(RuntimeError, match="结束"):
        await external.call(handle, "research_save_note", {"title": "迟到", "content": "不能写入"}, "late")
    await external.close()


def _save_then_fail(registry: ToolExecutor, context: HostedRunContext) -> None:
    """在原执行保存阶段稿后模拟进程内失败。参数：工具目录、宿主上下文。返回：无。异常：模拟失败。"""
    result = registry.execute("research_draft_report", {"report_markdown": "原执行阶段稿"}, ToolExecutionContext(run_id=context.run_id, tool_call_id="draft", cancellation_token=context.cancellation_token))
    assert result["ok"] is True
    raise RuntimeError("模拟工具基础设施失败")


@pytest.mark.asyncio
async def test_failed_external_run_resumes_original_cutoff_and_method(tmp_path: Path) -> None:
    """显式恢复使用原输入与方法，旧按钮不生成第二次执行。参数：目录。返回：无。异常：断言失败。"""
    external = _external(tmp_path)
    record = external.research.create(CreateResearchRequest("local", "create", "研究"))
    request = SubmitResearchTurnRequest(record.research_id, "local", "begin", "开始", execution_mode=ResearchExecutionMode.EXTERNAL)
    original = external.research.submit(request)
    accepted = external.research.dispatch_external(record.research_id, "local")
    assert accepted.run_id is not None
    with pytest.raises(RuntimeError, match="基础设施"):
        external.research.host.run_admitted_operation_sync(accepted.run_id, partial(_save_then_fail, external.registry_factory()))
    reopened = await external.resume(ResumeResearchTurnRequest(original.turn_id, "local", "retry"))
    restored = external.research.turn_details(original.turn_id, "local")
    assert restored.as_of == original.as_of and restored.preparation == original.preparation and restored.run_id != accepted.run_id
    handle = str(reopened["handle"])
    checkpoints = _value(await external.call(handle, "research_checkpoints", {}, "restore"))["checkpoints"]
    assert isinstance(checkpoints, list) and checkpoints
    previous = checkpoints[0]
    assert isinstance(previous, dict)
    result = await external.finish(handle, str(previous["candidate_id"]), str(previous["content_hash"]), "finish")
    assert isinstance(result, ResearchRevision)
    replay = await external.resume(ResumeResearchTurnRequest(original.turn_id, "local", "retry"))
    assert replay["completed"] is True and replay["revision_id"] == result.revision_id
    await external.close()


@pytest.mark.asyncio
async def test_disconnect_preserves_checkpoints_and_rejects_late_work(tmp_path: Path) -> None:
    """断开 stdio 后 Host 取消，下一轮仍能恢复原稿。参数：目录。返回：无。异常：断言失败。"""
    external = _external(tmp_path)
    research = external.research.create(CreateResearchRequest("local", "create", "研究"))
    opened = await external.begin(SubmitResearchTurnRequest(research.research_id, "local", "first", "开始", execution_mode=ResearchExecutionMode.EXTERNAL))
    handle = str(opened["handle"])
    draft = _value(await external.call(handle, "research_draft_report", {"report_markdown": "阶段稿"}, "draft"))
    await external.close()
    run = external.research.host.get_run(str(opened["run_id"]))
    assert run is not None and run.state == RunState.CANCELLED
    assert external.research.overview(research.research_id, "local").revisions == ()
    next_external = _external(tmp_path)
    next_open = await next_external.begin(SubmitResearchTurnRequest(research.research_id, "local", "next", "从检查点继续", execution_mode=ResearchExecutionMode.EXTERNAL))
    checkpoints = _value(await next_external.call(str(next_open["handle"]), "research_checkpoints", {}, "restore"))["checkpoints"]
    assert isinstance(checkpoints, list) and any(isinstance(item, dict) and item["candidate_id"] == draft["candidate_id"] for item in checkpoints)
    await next_external.close()


@pytest.mark.asyncio
async def test_competing_connection_cannot_cancel_the_original_owner(tmp_path: Path) -> None:
    """同一受理在另一连接被拒绝后，原执行仍可用。参数：目录。返回：无。异常：断言失败。"""
    first, second = _external(tmp_path), _external(tmp_path)
    research = first.research.create(CreateResearchRequest("local", "create", "研究"))
    request = SubmitResearchTurnRequest(research.research_id, "local", "begin", "开始", execution_mode=ResearchExecutionMode.EXTERNAL)
    opened = await first.begin(request)
    with pytest.raises(OperationAdmissionBusyError):
        await second.begin(request)
    assert _value(await first.call(str(opened["handle"]), "research_checkpoints", {}, "still-alive"))
    with pytest.raises(AgentAdmissionBusyError):
        # 直接 Host 入口同样受跨实例 Session 写互斥约束。
        second.research.host.admit_session_operation("another", HostedRunSpec("external_research", session_id=research.session_id), "b" * 64, expected_epoch=0)
    await second.close()
    await first.close()


@pytest.mark.asyncio
async def test_validation_failure_keeps_external_research_open(tmp_path: Path) -> None:
    """报告字段错误是可修复结果，不能结束 Host。参数：目录。返回：无。异常：断言失败。"""
    external = _external(tmp_path)
    research = external.research.create(CreateResearchRequest("local", "create", "研究"))
    opened = await external.begin(SubmitResearchTurnRequest(research.research_id, "local", "begin", "开始", execution_mode=ResearchExecutionMode.EXTERNAL))
    handle = str(opened["handle"])
    draft = _value(await external.call(handle, "research_draft_report", {"report_markdown": ""}, "draft"))
    result = await external.finish(handle, str(draft["candidate_id"]), str(draft["content_hash"]), "finish")
    assert isinstance(result, dict) and _value(result)["valid"] is False
    run = external.research.host.get_run(str(opened["run_id"]))
    assert run is not None and run.state == RunState.RUNNING
    await external.close()


@dataclass(frozen=True)
class _WaitForCancel:
    """可观察父 Host 取消的同步工具。"""

    entered: Event
    __tool_extra__: ClassVar[ToolExtra] = _extra("等待父取消")
    __tool_tags__: ClassVar[set[str]] = {"research"}

    def __call__(self, _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """等待取消并拒绝写入。参数：Host 上下文。返回：不可达对象。异常：取消或测试超时。"""
        assert _context is not None and _context.cancellation_token is not None
        self.entered.set()
        assert _context.cancellation_token.wait(5)
        _context.cancellation_token.raise_if_cancelled()
        return {}


@dataclass(frozen=True)
class _WaitingRegistry:
    """在实际工具装配后加一个可阻塞的领域桩。"""

    original: Callable[[], ToolExecutor]
    entered: Event

    def __call__(self) -> ToolRegistry:
        """构建工具目录。参数：无。返回：目录。异常：注册失败。"""
        registry = self.original()
        assert isinstance(registry, ToolRegistry)
        registry.register("wait_for_cancel", _WaitForCancel(self.entered), _schema("wait_for_cancel", "等待父取消", {"type": "object", "properties": {}, "required": []}))
        return registry


@pytest.mark.asyncio
async def test_cancelled_inflight_call_waits_for_host_tool_cleanup(tmp_path: Path) -> None:
    """请求取消穿透到同步工具，收尾后不留活跃执行。参数：目录。返回：无。异常：断言失败。"""
    external = _external(tmp_path)
    entered = Event()
    external.registry_factory = _WaitingRegistry(external.registry_factory, entered)
    record = external.research.create(CreateResearchRequest("local", "create", "研究"))
    opened = await external.begin(SubmitResearchTurnRequest(record.research_id, "local", "begin", "开始", execution_mode=ResearchExecutionMode.EXTERNAL))
    pending = asyncio.create_task(external.call(str(opened["handle"]), "wait_for_cancel", {}, "wait"))
    assert await asyncio.to_thread(entered.wait, 3)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    run = external.research.host.get_run(str(opened["run_id"]))
    assert run is not None and run.state == RunState.CANCELLED
    assert external.research.overview(record.research_id, "local").active_turn is None
    await external.close()


@pytest.mark.asyncio
async def test_completion_target_cannot_change_during_research(tmp_path: Path) -> None:
    """配置变化不能把已授权研究静默发往别处。参数：目录。返回：无。异常：断言失败。"""
    external = _external(tmp_path)
    original = external.research.publisher
    assert isinstance(original, PublicationService)
    record = external.research.create(CreateResearchRequest("local", "create", "研究"))
    opened = await external.begin(SubmitResearchTurnRequest(record.research_id, "local", "begin", "完成后归档", execution_mode=ResearchExecutionMode.EXTERNAL,
                                  publication_policy=ResearchPublicationPolicy.ON_COMPLETE))
    handle = str(opened["handle"])
    assert opened["publication_target_id"] == original.target_id
    draft = _value(await external.call(handle, "research_draft_report", {"report_markdown": "正式结论"}, "draft"))
    external.research.publisher = replace(original, target_id="00000000-0000-0000-0000-000000000099")
    with pytest.raises(ResearchConflictError, match="固定目标"):
        await external.finish(handle, str(draft["candidate_id"]), str(draft["content_hash"]), "finish")
    assert original.list_for_owner("local") == []
    assert len(external.research.overview(record.research_id, "local").revisions) == 1
    external.research.publisher = original
    completed = await external.finish(handle, str(draft["candidate_id"]), str(draft["content_hash"]), "finish")
    assert isinstance(completed, ResearchRevision)
    intents = original.list_for_owner("local")
    assert len(intents) == 1 and intents[0].target_id == original.target_id
    await external.close()
