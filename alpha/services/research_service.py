"""问题驱动研究服务：持久输入、宿主派发与不可变报告业务提交。"""

from __future__ import annotations

from contextlib import aclosing
from dataclasses import dataclass, replace
from typing import AsyncGenerator

from alpha.contracts.events import AppEvent
from alpha.contracts.agent_execution import ExecutionContract
from alpha.contracts.host_admission import AgentAdmissionStaleError
from alpha.contracts.research import (
    CommitResearchRevisionRequest, CreateResearchRequest, ResearchConflictError, ResearchExecutionMode, ResearchRecord,
    ResearchRevision, ResearchStopFence, ResearchTurn, ResearchTurnPreparation, ResearchTurnState, ResumeResearchTurnRequest, SubmitResearchTurnRequest,
)
from alpha.contracts.research_execution import ResearchExecutionHost, ResearchOverview
from alpha.contracts.run import RunCancelReason, RunState, TERMINAL_STATES
from alpha.contracts.session import SessionSource
from alpha.contracts.research_financials import FinancialRequirement, encode_financial_requirements
from alpha.contracts.host_execution import HostedRunSpec
from alpha.contracts.publication import PublishResearchRequest, ResearchCompletionPublisher
from alpha.contracts.research import ResearchPublicationPolicy
from alpha.research.methods.resources import read_packaged_method_files
from alpha.research.storage.encoding import canonical_json
from alpha.research.storage.protocols import ResearchCatalog, ResearchMethods, ResearchRevisions, ResearchTurnQueue, ResearchWorkingRecords
from alpha.services.contract_preparation import prepare_execution_contract
from alpha.services.scene_execution_acceptance import SceneExecutionAcceptancePreparer

RESEARCH_SCENE = "research"
_SERVICE_NAME = "research_turn"
_PREVIOUS_REPORT_CHARS = 16000
_RESUME_KEY_PREFIX = "research-resume:"
_EXTERNAL_OPERATION = "external_research"
_EXTERNAL_TIMEOUT_MS = 30 * 60 * 1000


class ResearchReportMissingError(RuntimeError):
    """Host 成功但未提交报告；不能把普通最终文本冒充正式版本。"""


@dataclass
class ResearchService:
    """组织研究业务，Host 独占执行状态和取消资源治理。"""

    host: ResearchExecutionHost
    acceptance: SceneExecutionAcceptancePreparer
    _catalog: ResearchCatalog
    _turns: ResearchTurnQueue
    _revisions: ResearchRevisions
    _working: ResearchWorkingRecords
    _methods: ResearchMethods
    publisher: ResearchCompletionPublisher | None = None

    def create(self, request: CreateResearchRequest) -> ResearchRecord:
        """创建并确保固定会话。参数：创建请求。返回：研究。异常：输入冲突或宿主错误。"""
        research = self._catalog.create(request)
        self.host.ensure_session(research.session_id, SessionSource.API, scene_name=RESEARCH_SCENE)
        return research

    def submit(self, request: SubmitResearchTurnRequest) -> ResearchTurn:
        """在返回前保存输入、方法与执行规格。参数：显式请求。返回：原始受理。异常：越权、冲突或配置错误。"""
        research = self._catalog.get(request.research_id, request.owner_id)
        # subjects 是明确的证券代码；一般研究不声明 subjects，不靠用户措辞猜测模式。
        if research.subjects and not request.financial_requirements:
            request = replace(request, financial_requirements=tuple(FinancialRequirement(ticker) for ticker in research.subjects))
        if request.publication_policy == ResearchPublicationPolicy.ON_COMPLETE:
            if self.publisher is None:
                raise ValueError("完成后发布需要已配置的 Invest 目标")
            if request.publication_target_id is not None and request.publication_target_id != self.publisher.target_id:
                raise ValueError("完成后发布目标必须来自可信配置")
            request = replace(request, publication_target_id=self.publisher.target_id)
        existing = self._turns.find(request)
        if existing is not None:
            return existing
        self.host.ensure_session(research.session_id, SessionSource.API, scene_name=RESEARCH_SCENE)
        accepted = self.acceptance.prepare(RESEARCH_SCENE, request.execution_options)
        bundle = self._methods.pin(read_packaged_method_files())
        return self._turns.enqueue(request, ResearchTurnPreparation(bundle.method_hash, accepted.accepted_execution_spec))

    def overview(self, research_id: str, owner_id: str) -> ResearchOverview:
        """聚合研究和实时执行状态。参数：研究、用户。返回：详情。异常：不存在或越权。"""
        research = self._catalog.get(research_id, owner_id)
        turn = self._turns.active(research_id, owner_id)
        latest = self._turns.latest(research_id, owner_id)
        source = turn if turn is not None and turn.run_id is not None else self._turns.latest_executed(research_id, owner_id)
        run = self.host.get_run(source.run_id) if source is not None and source.run_id is not None else None
        return ResearchOverview(research, turn, run, tuple(self._revisions.list_revisions(research_id, owner_id)),
                                self._turns.queued_count(research_id, owner_id), latest, source)

    def list_research(self, owner_id: str) -> list[ResearchRecord]:
        """列出用户可访问的研究。参数：用户。返回：目录。异常：存储错误。"""
        return self._catalog.list_research(owner_id)

    def archive(self, research_id: str, owner_id: str) -> ResearchRecord:
        """调和终态后归档研究。参数：研究、用户。返回：目录记录。异常：繁忙、越权或成果提交失败。"""
        turn = self._turns.active(research_id, owner_id)
        if turn is not None and turn.run_id is not None:
            self.finalize(turn.turn_id, owner_id)
        return self._catalog.archive(research_id, owner_id)

    def reopen(self, research_id: str, owner_id: str) -> ResearchRecord:
        """打开原研究并确保会话。参数：研究、用户。返回：目录记录。异常：越权或宿主错误。"""
        research = self._catalog.reopen(research_id, owner_id)
        self.host.ensure_session(research.session_id, SessionSource.API, scene_name=RESEARCH_SCENE)
        return research

    def read_report(self, revision_id: str, owner_id: str) -> str:
        """按指定版本校验并读取正式报告。参数：版本、用户。返回：Markdown 正文。异常：越权、缺失或完整性失败。"""
        return self._revisions.read_report(revision_id, owner_id)

    def revision_details(self, revision_id: str, owner_id: str) -> ResearchRevision:
        """校验用户后读取指定版本来源。参数：版本、用户。返回：不可变版本。异常：越权或缺失。"""
        return self._revisions.get(revision_id, owner_id)

    def stop(self, research_id: str, owner_id: str, request_key: str, *, expected_version: int | None = None) -> ResearchStopFence:
        """持久停止序号边界并请求 Host 协作取消。参数：研究、用户、稳定键。返回：边界。异常：越权或宿主错误。"""
        research = self._catalog.get(research_id, owner_id)
        self.host.ensure_session(research.session_id, SessionSource.API, scene_name=RESEARCH_SCENE)
        stop = self._turns.begin_stop(research_id, owner_id, request_key, expected_version=expected_version)
        if stop.completed_epoch is not None:
            return stop
        epoch = self.host.stop_session_admissions(research.session_id, stop.stop_id)
        return self._turns.complete_stop(stop.stop_id, owner_id, host_epoch=epoch)

    def dispatch(self, research_id: str, owner_id: str) -> ResearchTurn | None:
        """调和跨库受理并领取最早输入。参数：研究、用户。返回：已关联 Run 的输入或空。异常：繁忙、冲突或需恢复。"""
        research = self._catalog.get(research_id, owner_id)
        self.host.ensure_session(research.session_id, SessionSource.API, scene_name=RESEARCH_SCENE)
        turn = self._turns.active(research_id, owner_id)
        if turn is None:
            epoch = self.host.get_session_admission_epoch(research.session_id)
            previous = self._turns.latest_executed(research_id, owner_id)
            previous_run = self.host.get_run(previous.run_id) if previous is not None and previous.run_id is not None else None
            if previous is not None and previous.host_epoch == epoch and previous_run is not None and (
                previous_run.state in (RunState.FAILED, RunState.UNSETTLED) or (
                    previous_run.state == RunState.CANCELLED and previous_run.cancel_reason == RunCancelReason.TIMEOUT)):
                raise ResearchConflictError(f"原输入需要显式恢复：{previous.turn_id}；放弃可先停止，再提交新输入")
            turn = self._turns.claim_next(research_id, owner_id, host_epoch=epoch)
        if turn is None or turn.state != ResearchTurnState.DISPATCHING:
            return turn
        if turn.execution_mode == ResearchExecutionMode.EXTERNAL:
            raise ResearchConflictError("该输入由外部 coding agent 驱动，请通过 alpha MCP 接入")
        # 先查稳定受理键；受理后进程退出也不会重新读取配置或生成第二个 Run。
        request_key = _resume_key(turn.turn_id, turn.resume_request_key) if turn.resume_request_key is not None else turn.turn_id
        admission = self.host.find_agent_admission(research.session_id, request_key)
        if admission is None:
            try:
                if turn.resume_request_key is not None and turn.run_id is not None:
                    admission = self.host.admit_agent_resume(turn.run_id, request_key, expected_epoch=turn.host_epoch or 0)
                else:
                    admission = self.host.admit_agent_turn(request_key, self._contract(research, turn, owner_id), expected_epoch=turn.host_epoch or 0)
            except AgentAdmissionStaleError:
                return None
        return self._turns.mark_submitted(turn.turn_id, admission.run_id)

    def resume(self, request: ResumeResearchTurnRequest) -> ResearchTurn:
        """显式接受原输入恢复。参数：用户和稳定恢复请求。返回：已派发原输入。异常：越权、繁忙或不可恢复。"""
        turn = self._turns.get(request.turn_id, request.owner_id)
        research = self._catalog.get(turn.research_id, request.owner_id)
        if turn.execution_mode == ResearchExecutionMode.EXTERNAL:
            existing_operation = self.host.find_operation_admission(_resume_key(turn.turn_id, request.request_key))
            if existing_operation is not None and (turn.state != ResearchTurnState.DISPATCHING or turn.resume_request_key != request.request_key):
                return turn
            run = self.host.get_run(turn.run_id) if turn.run_id is not None else None
            if run is None or (run.state not in (RunState.FAILED, RunState.UNSETTLED) and not (
                    run.state == RunState.CANCELLED and run.cancel_reason == RunCancelReason.TIMEOUT)):
                raise ResearchConflictError("外部执行仅能显式恢复失败、孤立或超时输入")
            if turn.state == ResearchTurnState.SUBMITTED:
                self.finalize(turn.turn_id, request.owner_id)
            self._turns.request_resume(turn.turn_id, request.owner_id, request.request_key,
                                       host_epoch=self.host.get_session_admission_epoch(research.session_id))
            return self.dispatch_external(turn.research_id, request.owner_id)
        # 旧按钮只确认原恢复结果，不会再次恢复当前更晚的 Run。
        existing = self.host.find_agent_admission(research.session_id, _resume_key(turn.turn_id, request.request_key))
        if existing is not None and (turn.state != ResearchTurnState.DISPATCHING or turn.resume_request_key != request.request_key):
            return turn
        if existing is None:
            run = self.host.get_run(turn.run_id) if turn.run_id is not None else None
            if run is None or (run.state not in (RunState.FAILED, RunState.UNSETTLED) and not (
                run.state == RunState.CANCELLED and run.cancel_reason == RunCancelReason.TIMEOUT
            )):
                raise ResearchConflictError("原 Run 尚未收敛、已成功或被用户停止，不允许恢复")
        if turn.state == ResearchTurnState.SUBMITTED:
            self.finalize(turn.turn_id, request.owner_id)
        self._turns.request_resume(turn.turn_id, request.owner_id, request.request_key,
                                   host_epoch=self.host.get_session_admission_epoch(research.session_id))
        resumed = self.dispatch(turn.research_id, request.owner_id)
        if resumed is None:
            raise ResearchConflictError("恢复派发被停止边界拒绝")
        return resumed

    def dispatch_external(self, research_id: str, owner_id: str) -> ResearchTurn:
        """把外部输入关联到 Host 会话操作。参数：研究、用户。返回：固定 Run 的输入。异常：排队、模式或停止冲突。"""
        research = self._catalog.get(research_id, owner_id)
        epoch = self.host.get_session_admission_epoch(research.session_id)
        turn = self._turns.active(research_id, owner_id) or self._turns.claim_next(research_id, owner_id, host_epoch=epoch)
        if turn is None or turn.execution_mode != ResearchExecutionMode.EXTERNAL:
            raise ResearchConflictError("当前最早输入不是外部研究，请先完成或停止前序输入")
        if turn.state == ResearchTurnState.SUBMITTED:
            return turn
        spec = HostedRunSpec(_EXTERNAL_OPERATION, session_id=research.session_id, timeout_ms=_EXTERNAL_TIMEOUT_MS)
        request_key = _resume_key(turn.turn_id, turn.resume_request_key) if turn.resume_request_key is not None else "external:" + turn.turn_id
        admission = self.host.admit_session_operation(request_key, spec, turn.input_hash, expected_epoch=turn.host_epoch or 0)
        return self._turns.mark_submitted(turn.turn_id, admission.run_id)

    def turn_details(self, turn_id: str, owner_id: str) -> ResearchTurn:
        """读取固定输入来源。参数：输入、用户。返回：输入。异常：缺失或越权。"""
        return self._turns.get(turn_id, owner_id)

    def _contract(self, research: ResearchRecord, turn: ResearchTurn, owner_id: str) -> ExecutionContract:
        """装配已固定业务输入。参数：研究、输入、用户。返回：执行契约。异常：资源损坏。"""
        bundle = self._methods.load(turn.preparation.method_hash)
        previous = self._revisions.list_revisions(research.research_id, owner_id)
        previous_text = self._revisions.read_report(previous[-1].revision_id, owner_id)[:_PREVIOUS_REPORT_CHARS] if previous else "无"
        context = canonical_json({"question": research.question, "subjects": list(research.subjects), "depth": research.depth.value,
                                  "as_of": turn.as_of.isoformat(), "historical": turn.historical,
                                  "financial_requirements": encode_financial_requirements(turn.financial_requirements),
                                  "attachment_refs": list(turn.attachment_refs), "previous_report_excerpt": previous_text})
        return prepare_execution_contract(
            service_name=_SERVICE_NAME, scene_name=RESEARCH_SCENE, accepted_execution_spec=turn.preparation.accepted_spec,
            prompt_contributions={"research_method": bundle.entrypoint_text, "research_context": context},
            selected_toolsets=("research", "web", "fins"), user_message=turn.user_text or "请分析所附材料并更新研究。",
            session_key=research.session_id, business_concurrency_lane=None, execution_options=turn.execution_options, resumable=True,
        )

    def finalize(self, turn_id: str, owner_id: str) -> ResearchRevision | None:
        """仅在 Host 成功且已持久保存结果后提交报告。参数：输入、用户。返回：正式版本或空。异常：缺稿、损坏或状态冲突。"""
        turn = self._turns.get(turn_id, owner_id)
        if turn.run_id is None:
            raise ResearchConflictError("输入尚未由 Host 受理")
        run = self.host.get_run(turn.run_id)
        if run is None or run.state not in TERMINAL_STATES:
            return None
        if run.state != RunState.SUCCEEDED:
            self._turns.settle(turn_id, turn.run_id)
            return None
        if turn.execution_mode == ResearchExecutionMode.INTERNAL and self.host.get_admitted_agent_result(turn.run_id) is None:
            raise ResearchConflictError("Host 成功结果尚未保存，需要调和后提交")
        report = self._working.latest_report(self._working.scope_for_run(turn.run_id))
        if report is None:
            self._turns.settle(turn_id, turn.run_id)
            raise ResearchReportMissingError("模型未调用 research_submit_report；请补充研究输入要求提交报告")
        revision = self._revisions.commit(CommitResearchRevisionRequest(
            turn.research_id, owner_id, turn.turn_id, turn.run_id, report.report_markdown,
            turn.preparation.method_hash, report.evidence, report.data_contract_json,
        ))
        if turn.publication_policy == ResearchPublicationPolicy.ON_COMPLETE:
            if self.publisher is None:
                raise ResearchConflictError("正式版本已保存；Notion 连接不可用，恢复连接后重试完成步骤")
            if turn.publication_target_id != self.publisher.target_id:
                raise ResearchConflictError("归档目标与本轮固定目标不符；正式版本已保留，请恢复原目标后重试归档")
            self.publisher.request_publish(PublishResearchRequest(revision.revision_id, owner_id, "on-complete:" + turn.turn_id))
        self._turns.settle(turn_id, turn.run_id)
        return revision

    async def run_next(self, research_id: str, owner_id: str) -> AsyncGenerator[AppEvent, None]:
        """执行或调和当前输入。参数：研究、用户。返回：Host 原始事件流。异常：执行、恢复或报告提交错误。"""
        turn = self.dispatch(research_id, owner_id)
        if turn is None or turn.run_id is None:
            return
        if turn.execution_mode == ResearchExecutionMode.EXTERNAL:
            return
        try:
            async with aclosing(self.host.run_admitted_turn_stream(turn.run_id)) as stream:
                async for event in stream:
                    yield event
        finally:
            self.finalize(turn.turn_id, owner_id)


def _resume_key(turn_id: str, request_key: str) -> str:
    """隔离恢复请求命名空间。参数：输入、渠道稳定键。返回：Host 请求键。异常：无。"""
    return _RESUME_KEY_PREFIX + canonical_json([turn_id, request_key])
