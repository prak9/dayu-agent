"""在 Host 发布执行内创建或只读找回研究主题页。"""

from dataclasses import dataclass

from alpha.contracts.host_execution import HostedRunContext
from alpha.contracts.notion_topics import ResearchTopicClaim, ResearchTopicRecords
from alpha.integrations.notion.client import NotionApiError
from alpha.integrations.notion.contracts import NotionGateway, NotionPage, NotionTask, NotionTaskState

_MARKER_PREFIX = "alpha-research-topic:"


def topic_marker(research_id: str) -> str:
    """生成只与稳定研究身份相关的标记。参数：研究 ID。返回：标记。异常：无。"""
    return _MARKER_PREFIX + research_id


@dataclass(frozen=True)
class NotionTopicService:
    """同一研究多版本共用主题，标题不参与身份匹配。"""

    records: ResearchTopicRecords
    gateway: NotionGateway | None

    def reserve(self, research_id: str, owner_id: str, root_id: str, title: str) -> None:
        """持久固定本地主题意图。参数：研究、用户、根、标题。返回：无。异常：越权或存储失败。"""
        self.records.reserve(research_id, owner_id, root_id, title)

    def resolve(self, research_id: str, root_id: str, context: HostedRunContext) -> str:
        """取得当前主题页。参数：研究、固定根、宿主上下文。返回：页 ID。异常：未知结果、取消或 API 错误。"""
        if self.gateway is None:
            raise ValueError("创建或核对研究主题需要 Notion 连接")
        claim = self.records.claim(research_id, root_id)
        try:
            if claim.page_id is not None:
                return self._verify(self.gateway.retrieve_page(claim.page_id, context.cancellation_token), claim, context)
            if claim.remote_task_id is not None:
                try:
                    return self._finish_task(self.gateway.retrieve_task(claim.remote_task_id, context.cancellation_token), claim, context)
                except NotionApiError as exc:
                    if exc.status != 404:
                        raise
                    return self._reconcile(claim, context)
            if claim.creation_started:
                return self._reconcile(claim, context)
            context.cancellation_token.raise_if_cancelled()
            self.records.mark_started(claim)
            try:
                result = self.gateway.create_page(root_id, claim.title,
                    "研究主题：" + claim.title + "\n\n" + topic_marker(research_id) + "\n\n各次研究结果作为不可变子页面保存在此主题下。", context.cancellation_token)
            except NotionApiError as exc:
                if exc.committed_resource_id is not None:
                    self.records.save_page(claim, exc.committed_resource_id)
                elif not exc.unknown and 400 <= exc.status < 500:
                    self.records.mark_rejected(claim)
                raise
            if isinstance(result, NotionTask):
                self.records.save_task(claim, result.task_id)
                return self._finish_task(result, claim, context)
            self.records.save_page(claim, result.page_id)
            return self._verify(result, claim, context)
        finally:
            self.records.release(claim)

    def _finish_task(self, task: NotionTask, claim: ResearchTopicClaim, context: HostedRunContext) -> str:
        """等待已知任务，不重复创建。参数：任务、租约、上下文。返回：页 ID。异常：失败或缺身份。"""
        assert self.gateway is not None
        while task.state in (NotionTaskState.QUEUED, NotionTaskState.RUNNING, NotionTaskState.RETRYING):
            context.cancellation_token.wait(task.poll_after_seconds)
            context.cancellation_token.raise_if_cancelled()
            task = self.gateway.retrieve_task(task.task_id, context.cancellation_token)
        if task.state != NotionTaskState.SUCCEEDED or task.page is None:
            raise ValueError("研究主题异步结果尚不能确认，请核对已有任务")
        self.records.save_page(claim, task.page.page_id)
        return self._verify(task.page, claim, context)

    def _verify(self, page: NotionPage, claim: ResearchTopicClaim, context: HostedRunContext) -> str:
        """确认直接父页和稳定标记，允许改标题。参数：页面、租约、上下文。返回：ID。异常：移动、归档或内容冲突。"""
        assert self.gateway is not None
        if page.archived or page.parent_id != claim.root_id:
            raise ValueError("研究主题已移动或归档，拒绝隐式重建")
        body = self.gateway.retrieve_markdown(page.page_id, context.cancellation_token)
        if body.truncated or body.unknown_block_ids or topic_marker(claim.research_id) not in body.markdown:
            raise ValueError("研究主题标记无法完整确认")
        return page.page_id

    def _reconcile(self, claim: ResearchTopicClaim, context: HostedRunContext) -> str:
        """只读查找唯一主题。参数：租约、上下文。返回：页 ID。异常：未找到或多个候选。"""
        assert self.gateway is not None
        matches: list[NotionPage] = []
        for page_id in self.gateway.child_pages(claim.root_id, context.cancellation_token):
            page = self.gateway.retrieve_page(page_id, context.cancellation_token)
            if page.archived or page.parent_id != claim.root_id:
                continue
            body = self.gateway.retrieve_markdown(page_id, context.cancellation_token)
            if not body.truncated and not body.unknown_block_ids and topic_marker(claim.research_id) in body.markdown:
                matches.append(page)
        if len(matches) != 1:
            raise ValueError("无法确认唯一研究主题；保留未知结果，不重复创建")
        self.records.save_page(claim, matches[0].page_id)
        return self._verify(matches[0], claim, context)
