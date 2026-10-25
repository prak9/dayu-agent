"""真实 Service/Host/场景装配，隔离模型流后的完整研究行为测试。"""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from alpha.contracts.events import AppEvent, AppEventType
from alpha.contracts.research import CreateResearchRequest, ResearchConflictError, ResearchTurnState, ResumeResearchTurnRequest, SubmitResearchTurnRequest
from alpha.contracts.research_working import ResearchReportContent
from alpha.contracts.run import RunState
from alpha.services.research_preparation import prepare_research_service
from alpha.services.research_service import ResearchReportMissingError, ResearchService
from alpha.services.startup_preparation import prepare_host_runtime_dependencies


def _service(tmp_path: Path) -> ResearchService:
    """装配默认服务。参数：目录。返回：服务。异常：配置或存储错误。"""
    dependencies = prepare_host_runtime_dependencies(workspace_root=tmp_path, config_root=None, execution_options=None,
                                                     runtime_label="test", log_module="TEST")
    return prepare_research_service(tmp_path, dependencies)


async def _report(service: ResearchService, research_id: str, text: str = "正式报告") -> AsyncGenerator[AppEvent, None]:
    """隔离模型并使用真实工作端口。参数：服务、研究、正文。返回：模型流。异常：断言失败。"""
    turn = service.overview(research_id, "owner").active_turn
    assert turn is not None and turn.run_id is not None
    service._working.append_report(service._working.scope_for_run(turn.run_id), "report", ResearchReportContent(text))
    yield AppEvent(AppEventType.FINAL_ANSWER, {"content": "摘要"})


@pytest.mark.asyncio
async def test_service_creates_two_revisions_without_duplicate_run(tmp_path: Path, mocker: MockerFixture) -> None:
    """研究续轮保留会话和不可变父版本。参数：目录、mock。返回：无。异常：断言失败。"""
    service = _service(tmp_path)
    research = service.create(CreateResearchRequest("owner", "new", "研究框架"))
    request = SubmitResearchTurnRequest(research.research_id, "owner", "input", "开始研究")
    turn = service.submit(request)
    assert service.submit(request) == turn
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", return_value=_report(service, research.research_id))
    events = [event async for event in service.run_next(research.research_id, "owner")]
    assert any(event.type == AppEventType.FINAL_ANSWER for event in events)
    first = service.overview(research.research_id, "owner")
    assert first.active_turn is None and len(first.revisions) == 1
    revision = first.revisions[0]
    assert service._revisions.read_report(revision.revision_id, "owner") == "正式报告"
    assert service.finalize(turn.turn_id, "owner") == revision
    assert service._turns.get(turn.turn_id, "owner").state == ResearchTurnState.SETTLED
    service.submit(SubmitResearchTurnRequest(research.research_id, "owner", "update", "核验增量信息"))
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", return_value=_report(service, research.research_id, "第二版"))
    _ = [event async for event in service.run_next(research.research_id, "owner")]
    versions = service.overview(research.research_id, "owner").revisions
    assert len(versions) == 2 and versions[1].parent_revision_id == revision.revision_id


@pytest.mark.asyncio
async def test_queued_followup_does_not_hide_or_block_failed_turn_recovery(tmp_path: Path, mocker: MockerFixture) -> None:
    """失败后排队输入不应占住恢复位置。参数：目录、mock。返回：无。异常：断言失败。"""
    service = _service(tmp_path)
    record = service.create(CreateResearchRequest("owner", "create", "研究"))
    first = service.submit(SubmitResearchTurnRequest(record.research_id, "owner", "first", "原输入"))

    async def failed() -> AsyncGenerator[AppEvent, None]:
        """模拟模型故障。参数：无。返回：错误事件。异常：无。"""
        raise RuntimeError("模拟模型失败")
        yield AppEvent(AppEventType.ERROR, {})

    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", return_value=failed())
    with pytest.raises(RuntimeError, match="模拟模型失败"):
        _ = [event async for event in service.run_next(record.research_id, "owner")]
    queued = service.submit(SubmitResearchTurnRequest(record.research_id, "owner", "next", "后续输入"))
    with pytest.raises(RuntimeError):
        service.dispatch(record.research_id, "owner")
    view = service.overview(record.research_id, "owner")
    assert view.latest_turn is not None and view.latest_turn.turn_id == queued.turn_id
    assert view.execution_turn is not None and view.execution_turn.turn_id == first.turn_id
    assert view.run is not None and view.run.state == RunState.FAILED and view.active_turn is None
    resumed = service.resume(ResumeResearchTurnRequest(first.turn_id, "owner", "retry"))
    assert resumed.turn_id == first.turn_id and resumed.run_id != first.run_id
    assert service.overview(record.research_id, "owner").queued_count == 1


def test_dispatch_recovers_after_host_acceptance_before_business_ack(tmp_path: Path, mocker: MockerFixture) -> None:
    """跨库受理中断通过稳定键调和。参数：目录、mock。返回：无。异常：断言失败。"""
    service = _service(tmp_path)
    research = service.create(CreateResearchRequest("owner", "new", "研究"))
    service.submit(SubmitResearchTurnRequest(research.research_id, "owner", "input", "开始"))
    original = service._turns.mark_submitted
    broken = mocker.patch.object(service._turns, "mark_submitted", side_effect=RuntimeError("受理后退出"))
    with pytest.raises(RuntimeError, match="受理后退出"):
        service.dispatch(research.research_id, "owner")
    broken.side_effect = original
    other = _service(tmp_path)
    dispatched = other.dispatch(research.research_id, "owner")
    assert dispatched is not None and dispatched.run_id is not None
    assert other.dispatch(research.research_id, "owner") == dispatched
    with pytest.raises(PermissionError):
        other.dispatch(research.research_id, "stranger")


@pytest.mark.asyncio
async def test_stop_preserves_later_inputs_and_never_restarts_cancelled(tmp_path: Path, mocker: MockerFixture) -> None:
    """稳定停止键不重复取消后续输入。参数：目录、mock。返回：无。异常：断言失败。"""
    service = _service(tmp_path)
    research = service.create(CreateResearchRequest("owner", "new", "研究"))
    first = service.submit(SubmitResearchTurnRequest(research.research_id, "owner", "old", "停止前"))
    submitted = service.dispatch(research.research_id, "owner")
    assert submitted is not None and submitted.run_id is not None
    stop = service.stop(research.research_id, "owner", "stop")
    second = service.submit(SubmitResearchTurnRequest(research.research_id, "owner", "new", "停止后"))
    assert service.stop(research.research_id, "owner", "stop") == stop
    _ = [event async for event in service.run_next(research.research_id, "owner")]
    run = service.host.get_run(submitted.run_id)
    assert run is not None and run.state == RunState.CANCELLED
    assert service._turns.get(first.turn_id, "owner").state == ResearchTurnState.SETTLED
    next_turn = service.dispatch(research.research_id, "owner")
    assert next_turn is not None and next_turn.turn_id == second.turn_id


@pytest.mark.asyncio
async def test_successful_text_without_report_is_not_published(tmp_path: Path, mocker: MockerFixture) -> None:
    """Host 最终文本不能替代正式草稿。参数：目录、mock。返回：无。异常：断言失败。"""
    service = _service(tmp_path)
    research = service.create(CreateResearchRequest("owner", "new", "研究"))
    service.submit(SubmitResearchTurnRequest(research.research_id, "owner", "input", "开始"))
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", return_value=_text_only())
    with pytest.raises(ResearchReportMissingError):
        _ = [event async for event in service.run_next(research.research_id, "owner")]
    assert not service.overview(research.research_id, "owner").revisions


async def _text_only() -> AsyncGenerator[AppEvent, None]:
    """模拟未提交草稿的最终回答。参数：无。返回：流。异常：无。"""
    yield AppEvent(AppEventType.FINAL_ANSWER, {"content": "口头结论"})


@pytest.mark.asyncio
async def test_explicit_resume_preserves_original_scope_and_is_durable(tmp_path: Path, mocker: MockerFixture) -> None:
    """失败恢复产生一个新 Run 并使用原快照。参数：目录、mock。返回：无。异常：断言失败。"""
    service = _service(tmp_path)
    research = service.create(CreateResearchRequest("owner", "new", "研究"))
    original = service.submit(SubmitResearchTurnRequest(research.research_id, "owner", "input", "开始"))
    model = mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", return_value=_failing_text())
    with pytest.raises(RuntimeError, match="模型断线"):
        _ = [event async for event in service.run_next(research.research_id, "owner")]
    failed = service._turns.get(original.turn_id, "owner")
    assert failed.run_id is not None and failed.state == ResearchTurnState.SETTLED
    request = ResumeResearchTurnRequest(original.turn_id, "owner", "resume")
    recovered = service.resume(request)
    assert recovered.run_id != failed.run_id and recovered.as_of == original.as_of
    assert recovered.preparation == original.preparation
    other = _service(tmp_path)
    assert other.resume(request) == recovered
    model.return_value = _report(other, research.research_id)
    _ = [event async for event in other.run_next(research.research_id, "owner")]
    view = other.overview(research.research_id, "owner")
    assert len(view.revisions) == 1 and view.revisions[0].source_run_id == recovered.run_id
    assert other.resume(request).run_id == recovered.run_id
    with pytest.raises(ResearchConflictError):
        other.resume(ResumeResearchTurnRequest(original.turn_id, "owner", "another"))


async def _failing_text() -> AsyncGenerator[AppEvent, None]:
    """模拟模型执行断线。参数：无。返回：流。异常：确定的 RuntimeError。"""
    yield AppEvent(AppEventType.CONTENT_DELTA, {"text": "部分分析"})
    raise RuntimeError("模型断线")


@pytest.mark.asyncio
async def test_stop_abandons_failed_pending_before_new_input(tmp_path: Path, mocker: MockerFixture) -> None:
    """停止也放弃失败输入的恢复等待，后续研究能继续。参数：目录、mock。返回：无。异常：断言失败。"""
    service = _service(tmp_path)
    research = service.create(CreateResearchRequest("owner", "new", "研究"))
    service.submit(SubmitResearchTurnRequest(research.research_id, "owner", "failed", "开始"))
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", return_value=_failing_text())
    with pytest.raises(RuntimeError):
        _ = [event async for event in service.run_next(research.research_id, "owner")]
    service.stop(research.research_id, "owner", "abandon")
    next_turn = service.submit(SubmitResearchTurnRequest(research.research_id, "owner", "next", "继续研究"))
    dispatched = service.dispatch(research.research_id, "owner")
    assert dispatched is not None and dispatched.turn_id == next_turn.turn_id
