"""在 Host 生命周期内执行固定正文发布、异步轮询和只读未知结果调和。"""

from dataclasses import dataclass

from alpha.contracts.host_execution import HostedRunContext
from alpha.contracts.publication import PublicationClaim, PublicationState
from alpha.contracts.notion_topics import ResearchTopicResolver
from alpha.integrations.notion.client import NotionApiError
from alpha.integrations.notion.contracts import NotionGateway, NotionPage, NotionTask, NotionTaskState
from alpha.research.publication_identity import publication_marker
from alpha.research.publication_rendering import verify_publication_markdown
from alpha.research.publication_segments import segment_marker, segment_progress
from alpha.research.storage.publication_protocols import PublicationRecords

_RECONCILE_DELAY_SECONDS = 60.0
_TRANSIENT_DELAY_SECONDS = 5.0


class PublicationPreflightError(ValueError):
    """创建前已明确拒绝，尚无远端副作用。"""


@dataclass(frozen=True)
class NotionPublicationOperation:
    """仅操作明确授权的父页与本版本页面，不对已发布页覆盖写。"""

    records: PublicationRecords
    gateway: NotionGateway
    claim: PublicationClaim
    allow_create: bool
    topics: ResearchTopicResolver

    def __call__(self, context: HostedRunContext) -> None:
        """执行一个发布尝试。参数：Host 上下文。返回：无。异常：取消；持久状态异常向 Host 传播。"""
        try:
            self._perform(context)
        except PublicationPreflightError as exc:
            self.records.defer(self.claim, PublicationState.FAILED_TERMINAL, str(exc))
        except NotionApiError as exc:
            current = self.records.get(self.claim.publication.publication_id, self.claim.payload.owner_id)
            if exc.unknown or current.remote_task_id is not None or current.page_id is not None:
                state = PublicationState.RECONCILING
            elif exc.status == 429 or exc.status >= 500 or exc.status == 0:
                state = PublicationState.FAILED_RETRYABLE
            else:
                state = PublicationState.FAILED_TERMINAL
            self.records.defer(self.claim, state, str(exc), retry_after=exc.retry_after if exc.retry_after is not None else _TRANSIENT_DELAY_SECONDS)
        except ValueError as exc:
            self.records.defer(self.claim, PublicationState.RECONCILING, str(exc), retry_after=_RECONCILE_DELAY_SECONDS)

    def _perform(self, context: HostedRunContext) -> None:
        """根据已知远端身份推进。参数：上下文。返回：无。异常：取消、API 或核验错误。"""
        current = self.records.get(self.claim.publication.publication_id, self.claim.payload.owner_id)
        parent = self.gateway.retrieve_page(current.target_id, context.cancellation_token)
        if parent.archived or parent.page_id != current.target_id:
            raise PublicationPreflightError("配置的 Invest 父页不可用")
        parent_id = self.topics.resolve(self.claim.payload.research_id, current.target_id, context)
        if current.remote_task_id is not None:
            try:
                task = self.gateway.retrieve_task(current.remote_task_id, context.cancellation_token)
            except NotionApiError as exc:
                if exc.status != 404:
                    raise
                # 任务保留期已过；只有已知页或唯一只读候选可以继续，绝不再次创建。
                if current.page_id is not None:
                    self.records.save_page(self.claim, current.page_id, current.page_url or "")
                    self._verify(self.gateway.retrieve_page(current.page_id, context.cancellation_token), context, parent_id)
                else:
                    self._reconcile(context, parent_id)
                return
            self._finish_task(task, context, parent_id)
            return
        if current.page_id is not None:
            self._verify(self.gateway.retrieve_page(current.page_id, context.cancellation_token), context, parent_id)
            return
        if not self.allow_create:
            self._reconcile(context, parent_id)
            return
        context.cancellation_token.raise_if_cancelled()
        self.records.mark_creation_started(self.claim)
        try:
            markdown = self.claim.segments[0]
            if len(self.claim.segments) > 1:
                markdown += "\n\n" + segment_marker(current.publication_id, 0, markdown)
            result = self.gateway.create_page(parent_id, self.claim.payload.title, markdown, context.cancellation_token)
        except NotionApiError as exc:
            if exc.committed_resource_id is not None:
                self.records.save_page(self.claim, exc.committed_resource_id, "")
            elif not exc.unknown and 400 <= exc.status < 500:
                self.records.mark_creation_rejected(self.claim)
            raise
        if isinstance(result, NotionTask):
            self.records.save_task(self.claim, result.task_id)
            self._finish_task(result, context, parent_id)
        else:
            self.records.save_page(self.claim, result.page_id, result.url)
            self._verify(result, context, parent_id)

    def _finish_task(self, task: NotionTask, context: HostedRunContext, parent_id: str) -> None:
        """轮询持久异步任务。参数：已知任务、上下文。返回：无。异常：取消或远端读取错误。"""
        while task.state in (NotionTaskState.QUEUED, NotionTaskState.RUNNING, NotionTaskState.RETRYING):
            context.cancellation_token.wait(task.poll_after_seconds)
            context.cancellation_token.raise_if_cancelled()
            task = self.gateway.retrieve_task(task.task_id, context.cancellation_token)
        if task.state == NotionTaskState.FAILED:
            state = PublicationState.FAILED_TERMINAL if task.error_status is not None and task.error_status < 500 else PublicationState.RECONCILING
            self.records.defer(self.claim, state, f"Notion 异步任务失败：{task.error_code}", retry_after=_RECONCILE_DELAY_SECONDS)
            return
        if task.page is None:
            current = self.records.get(self.claim.publication.publication_id, self.claim.payload.owner_id)
            if current.page_id is None:
                raise ValueError("Notion 创建任务成功但缺少页面身份，需要调和")
            page = self.gateway.retrieve_page(current.page_id, context.cancellation_token)
        else:
            page = task.page
        self.records.save_page(self.claim, page.page_id, page.url)
        self._verify(page, context, parent_id)

    def _verify(self, page: NotionPage, context: HostedRunContext, parent_id: str) -> None:
        """核对直接父页、完整正文和版本标记。参数：页面、上下文。返回：无。异常：不完整或不匹配。"""
        if page.archived or page.parent_id != parent_id:
            raise ValueError("Notion 页面不在固定研究主题下或已被归档")
        while True:
            readback = self.gateway.retrieve_markdown(page.page_id, context.cancellation_token)
            if readback.truncated or readback.unknown_block_ids:
                raise ValueError("Notion 正文回读被截断或存在未知块，不能确认发布")
            identifier = self.claim.publication.publication_id
            if len(self.claim.segments) == 1:
                written, body = 1, readback.markdown
            else:
                written, body = segment_progress(readback.markdown, identifier, self.claim.segments)
            verify_publication_markdown("".join(self.claim.segments[:written]), body, identifier)
            self.records.record_progress(self.claim, written)
            if written == len(self.claim.segments):
                self.records.mark_published(self.claim)
                return
            context.cancellation_token.raise_if_cancelled()
            previous = segment_marker(identifier, written - 1, self.claim.segments[written - 1])
            replacement = self.claim.segments[written] + "\n\n" + segment_marker(identifier, written, self.claim.segments[written])
            result = self.gateway.replace_marker(page.page_id, previous, replacement, context.cancellation_token)
            if isinstance(result, NotionTask):
                self.records.save_task(self.claim, result.task_id)
                self._finish_task(result, context, parent_id)
                return

    def _reconcile(self, context: HostedRunContext, parent_id: str) -> None:
        """未知创建只读核对唯一标记，不以未找到证明未创建。参数：上下文。返回：无。异常：API 或候选冲突。"""
        matches: list[NotionPage] = []
        identifier = self.claim.publication.publication_id
        for candidate in self.gateway.child_pages(parent_id, context.cancellation_token):
            page = self.gateway.retrieve_page(candidate, context.cancellation_token)
            if page.archived or page.parent_id != parent_id:
                continue
            markdown = self.gateway.retrieve_markdown(candidate, context.cancellation_token)
            if publication_marker(identifier) in markdown.markdown:
                matches.append(page)
        if not matches:
            self.records.defer(self.claim, PublicationState.RECONCILING, "未找到可确认页面；不自动重复创建，请稍后核对", retry_after=_RECONCILE_DELAY_SECONDS)
            return
        if len(matches) != 1:
            raise ValueError("同一发布发现多个远端页面，需要人工核对")
        self.records.save_page(self.claim, matches[0].page_id, matches[0].url)
        self._verify(matches[0], context, parent_id)
