"""发布服务消费的业务持久化端口，不含 HTTP 或 Host 生命周期。"""

from typing import Protocol

from alpha.contracts.publication import PublicationClaim, PublicationState, PublishResearchRequest, ResearchPublication


class PublicationRecords(Protocol):
    """固定正文、原版本和业务尝试的发布真源。"""

    def request(self, request: PublishResearchRequest, *, target_id: str, title: str, markdown: str) -> ResearchPublication:
        """接受意图。参数：授权、目标、首次渲染内容。返回：原或新意图。异常：越权或冲突。"""
        ...

    def get(self, publication_id: str, owner_id: str) -> ResearchPublication:
        """查询状态。参数：身份、所有者。返回：记录。异常：越权或缺失。"""
        ...

    def list_for_owner(self, owner_id: str) -> list[ResearchPublication]:
        """列出授权发布。参数：用户。返回：记录列表。异常：完整性损坏。"""
        ...

    def claim_next(self) -> PublicationClaim | None:
        """领取到期工作。参数：无。返回：租约或空。异常：持久状态损坏。"""
        ...

    def advance_attempt(self, claim: PublicationClaim) -> PublicationClaim:
        """登记下一执行尝试。参数：租约。返回：新尝试。异常：fencing 冲突。"""
        ...

    def link_run(self, claim: PublicationClaim, run_id: str) -> None:
        """关联宿主受理。参数：租约、Run。返回：无。异常：冲突。"""
        ...

    def mark_creation_started(self, claim: PublicationClaim) -> None:
        """在 POST 前固定外部创建边界。参数：租约。返回：无。异常：已经跨界或租约失效。"""
        ...

    def mark_creation_rejected(self, claim: PublicationClaim) -> None:
        """明确拒绝后恢复创建资格。参数：租约。返回：无。异常：已有远端身份。"""
        ...

    def save_page(self, claim: PublicationClaim, page_id: str, page_url: str) -> None:
        """保存已知页面。参数：租约、页面、URL。返回：无。异常：冲突。"""
        ...

    def save_task(self, claim: PublicationClaim, task_id: str) -> None:
        """保存异步任务。参数：租约、任务。返回：无。异常：冲突。"""
        ...

    def mark_published(self, claim: PublicationClaim) -> ResearchPublication:
        """回读通过后确认。参数：租约。返回：记录。异常：缺少页面或任务未完。"""
        ...

    def record_progress(self, claim: PublicationClaim, written: int) -> None:
        """核验后推进分段。参数：租约、已写段数。返回：无。异常：进度或租约冲突。"""
        ...

    def defer(self, claim: PublicationClaim, state: PublicationState, error: str, *, retry_after: float = 0) -> None:
        """失败或等待调和。参数：租约、状态、错误、延迟。返回：无。异常：冲突。"""
        ...

    def release(self, claim: PublicationClaim) -> None:
        """释放自身执行租约。参数：租约。返回：无。异常：数据库错误。"""
        ...
