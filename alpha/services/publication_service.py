"""明确版本发布服务：权限、固定正文、Host 持久受理与尝试调和。"""

from dataclasses import dataclass
from collections.abc import Callable
from functools import partial

from alpha.contracts.cancellation import CancellationToken, CancelledError
from alpha.contracts.host_execution import HostedRunSpec
from alpha.contracts.operation_admission import OperationAdmissionBusyError, OperationAdmissionRecoveryRequiredError
from alpha.contracts.publication import PublicationState, PublishResearchRequest, ResearchPublication
from alpha.contracts.publication_execution import PublicationHost
from alpha.contracts.research import ResearchConflictError
from alpha.contracts.notion_topics import ResearchTopicResolver
from alpha.contracts.run import RunCancelReason, RunState, TERMINAL_STATES
from alpha.integrations.notion.contracts import NotionGateway
from alpha.research.publication_rendering import render_publication
from alpha.research.storage.protocols import ResearchCatalog, ResearchRevisions
from alpha.research.storage.publication_protocols import PublicationRecords
from alpha.services.concurrency_lanes import LANE_PUBLICATION
from alpha.services.publication_operation import NotionPublicationOperation

_OPERATION_NAME = "notion_publication"
_OPERATION_TIMEOUT_MS = 300000
_RETRY_DELAY_SECONDS = 5.0


@dataclass(frozen=True)
class PublicationService:
    """Agent 不持有此服务；只有明确用户动作能建立发布意图。"""

    host: PublicationHost
    _records: PublicationRecords
    _catalog: ResearchCatalog
    _revisions: ResearchRevisions
    gateway: NotionGateway | None
    target_id: str
    topics: ResearchTopicResolver

    def request_publish(self, request: PublishResearchRequest) -> ResearchPublication:
        """校验已提交版本并持久接受发布。参数：用户、指定版本、稳定键。返回：原或新意图。异常：越权、缺失或内容损坏。"""
        revision = self._revisions.get(request.revision_id, request.owner_id)
        content = self._revisions.read_content(request.revision_id, request.owner_id)
        research = self._catalog.get(revision.research_id, request.owner_id)
        self.topics.reserve(research.research_id, request.owner_id, self.target_id, research.title)
        title, markdown = render_publication(research, revision, content, self.target_id)
        return self._records.request(request, target_id=self.target_id, title=title, markdown=markdown)

    def get(self, publication_id: str, owner_id: str) -> ResearchPublication:
        """查询授权发布结果。参数：发布、所有者。返回：状态和 URL。异常：越权或缺失。"""
        return self._records.get(publication_id, owner_id)

    def list_for_owner(self, owner_id: str) -> list[ResearchPublication]:
        """为交付渠道查询已有明确发布意图。参数：用户。返回：记录。异常：完整性损坏。"""
        return self._records.list_for_owner(owner_id)

    def process_next(self, cancellation_token: CancellationToken | None = None) -> ResearchPublication | None:
        """在 Host 内执行一次到期发布。参数：可选工作者取消令牌。返回：最新业务结果或空。异常：持久化错误，不掩盖未知副作用。"""
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        if self.gateway is None:
            raise ValueError("发布意图已保存，消费队列需要配置 Notion 连接")
        claim = self._records.claim_next()
        if claim is None:
            return None
        run_id: str | None = None
        unregister: Callable[[], None] | None = None
        try:
            spec = HostedRunSpec(_OPERATION_NAME, business_concurrency_lane=LANE_PUBLICATION, timeout_ms=_OPERATION_TIMEOUT_MS)
            admission = self.host.admit_operation(_attempt_key(claim.publication.publication_id, claim.attempt), spec, claim.payload.payload_hash)
            run_id = admission.run_id
            run = self.host.get_run(run_id)
            if run is None:
                raise ResearchConflictError("发布 Host 受理缺少 Run 真源")
            # 外部请求边界由业务事务先落盘，不从 Run 成败推测页面是否已经创建。
            allow_create = not claim.creation_started
            if run.state in TERMINAL_STATES:
                claim = self._records.advance_attempt(claim)
                admission = self.host.admit_operation(_attempt_key(claim.publication.publication_id, claim.attempt), spec, claim.payload.payload_hash)
                run_id = admission.run_id
            self._records.link_run(claim, run_id)
            if cancellation_token is not None:
                unregister = cancellation_token.on_cancel(partial(_cancel_publication_run, self.host, run_id))
            self.host.run_admitted_operation_sync(run_id, NotionPublicationOperation(self._records, self.gateway, claim, allow_create, self.topics))
        except CancelledError:
            current = self._records.get(claim.publication.publication_id, claim.payload.owner_id)
            run = self.host.get_run(run_id) if run_id is not None else None
            if current.state != PublicationState.PUBLISHED:
                interrupted = cancellation_token is not None and cancellation_token.is_cancelled()
                state = PublicationState.RECONCILING if interrupted or (run is not None and run.cancel_reason == RunCancelReason.TIMEOUT) else PublicationState.FAILED_TERMINAL
                error = "应用退出，保留远端身份待核对" if interrupted else "发布执行超时，保留远端身份待核对" if state == PublicationState.RECONCILING else "用户已取消发布执行"
                self._records.defer(claim, state, error, retry_after=_RETRY_DELAY_SECONDS)
        except (OperationAdmissionBusyError, OperationAdmissionRecoveryRequiredError) as exc:
            self._records.defer(claim, PublicationState.RECONCILING, str(exc), retry_after=_RETRY_DELAY_SECONDS)
        except Exception as exc:
            self._records.defer(claim, PublicationState.RECONCILING, type(exc).__name__, retry_after=_RETRY_DELAY_SECONDS)
            raise
        finally:
            if unregister is not None:
                unregister()
            self._records.release(claim)
        return self._records.get(claim.publication.publication_id, claim.payload.owner_id)


def _attempt_key(publication_id: str, attempt: int) -> str:
    """固定业务尝试的 Host 请求身份。参数：发布、序号。返回：键。异常：无。"""
    return f"publication:{publication_id}:attempt:{attempt}"


def _cancel_publication_run(host: PublicationHost, run_id: str) -> None:
    """把工作者退出映射为 Host 取消意图。参数：宿主、当前尝试。返回：无。异常：宿主错误。"""
    host.cancel_run(run_id)
