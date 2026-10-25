"""固定 Invest 根目录下的研究主题绑定与解析端口。"""

from dataclasses import dataclass
from typing import Protocol

from alpha.contracts.host_execution import HostedRunContext


@dataclass(frozen=True)
class ResearchTopicClaim:
    """一项稳定研究主题的创建/调和租约。"""

    research_id: str
    root_id: str
    title: str
    lease_id: str
    creation_started: bool
    page_id: str | None
    remote_task_id: str | None


class ResearchTopicRecords(Protocol):
    """保存主题绑定和未知创建边界，不调用 Notion。"""

    def reserve(self, research_id: str, owner_id: str, root_id: str, title: str) -> None:
        """固定主题目标。参数：研究、用户、根目录、标题。返回：无。异常：越权。"""
        ...

    def claim(self, research_id: str, root_id: str) -> ResearchTopicClaim:
        """领取主题。参数：研究、根目录。返回：租约。异常：繁忙或缺失。"""
        ...

    def mark_started(self, claim: ResearchTopicClaim) -> None:
        """固定外部边界。参数：租约。返回：无。异常：过期。"""
        ...

    def mark_rejected(self, claim: ResearchTopicClaim) -> None:
        """明确拒绝后恢复资格。参数：租约。返回：无。异常：过期。"""
        ...

    def save_page(self, claim: ResearchTopicClaim, page_id: str) -> None:
        """保存远端主题身份。参数：租约、页 ID。返回：无。异常：冲突。"""
        ...

    def save_task(self, claim: ResearchTopicClaim, task_id: str) -> None:
        """保存异步任务。参数：租约、任务。返回：无。异常：冲突。"""
        ...

    def release(self, claim: ResearchTopicClaim) -> None:
        """释放当前租约。参数：租约。返回：无。异常：数据库错误。"""
        ...


class ResearchTopicResolver(Protocol):
    """发布操作在 Host 作用域内获取稳定主题页。"""

    def reserve(self, research_id: str, owner_id: str, root_id: str, title: str) -> None:
        """固定授权的本地主题目标。参数：研究、用户、根目录、标题。返回：无。异常：越权。"""
        ...

    def resolve(self, research_id: str, root_id: str, context: HostedRunContext) -> str:
        """创建或只读调和主题页。参数：研究、根目录、Host 上下文。返回：主题 ID。异常：取消、API 或未知结果。"""
        ...
