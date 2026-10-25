"""Notion 远端页面、Markdown 和异步任务的最小类型。"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from alpha.contracts.cancellation import CancellationToken


@dataclass(frozen=True)
class NotionPage:
    """远端页面身份与直接父页。"""

    page_id: str
    parent_id: str | None
    url: str
    title: str
    archived: bool


@dataclass(frozen=True)
class NotionMarkdown:
    """回读内容，不将截断或未知块视作完整报告。"""

    markdown: str
    truncated: bool
    unknown_block_ids: tuple[str, ...]


class NotionTaskState(str, Enum):
    """官方异步任务状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class NotionTask:
    """可持久保存并在重启后轮询的远端任务。"""

    task_id: str
    state: NotionTaskState
    poll_after_seconds: float
    page: NotionPage | None
    error_status: int | None
    error_code: str | None


class NotionGateway(Protocol):
    """发布操作使用的最小外部能力。"""

    def retrieve_page(self, identifier: str, token: CancellationToken) -> NotionPage:
        """读取页面。参数：ID、令牌。返回：页面。异常：API 错误。"""
        ...

    def create_page(self, parent_id: str, title: str, markdown: str, token: CancellationToken) -> NotionPage | NotionTask:
        """创建正文页。参数：父页、标题、正文、令牌。返回：页面或任务。异常：已分类 API 错误。"""
        ...

    def retrieve_markdown(self, identifier: str, token: CancellationToken) -> NotionMarkdown:
        """回读正文。参数：ID、令牌。返回：完整性标记及正文。异常：读取错误。"""
        ...

    def retrieve_task(self, task_id: str, token: CancellationToken) -> NotionTask:
        """轮询任务。参数：ID、令牌。返回：任务。异常：读取错误。"""
        ...

    def replace_marker(self, identifier: str, old_marker: str, replacement: str, token: CancellationToken) -> NotionMarkdown | NotionTask:
        """按唯一哨兵插入下一分段。参数：页、旧标记、替换内容、令牌。返回：正文或异步任务。异常：API 错误。"""
        ...

    def child_pages(self, parent_id: str, token: CancellationToken) -> tuple[str, ...]:
        """枚举候选。参数：父页、令牌。返回：直接子页 ID。异常：读取错误。"""
        ...
