"""研究仓储的窄接口；调用者无需知道 SQLite 或文件布局。"""

from __future__ import annotations

from typing import Protocol, Mapping

from alpha.contracts.research import (
    CommitResearchRevisionRequest, CreateResearchRequest, ResearchRecord, ResearchRevision,
    ResearchState, ResearchStopFence, ResearchTurn, ResearchTurnPreparation, SubmitResearchTurnRequest,
)
from alpha.contracts.research_channels import BindResearchChannelRequest, ResearchChannelBinding
from alpha.contracts.research_methods import ResearchMethodBundle
from alpha.contracts.research_working import ResearchReportContent, ResearchWorkScope, ResearchWorkingRecord
from alpha.contracts.agent_types import JsonValue


class ResearchCatalog(Protocol):
    """研究目录及业务生命周期端口。"""

    def create(self, request: CreateResearchRequest) -> ResearchRecord:
        """创建研究。参数：request 输入。返回：研究。异常：输入冲突。"""
        ...

    def get(self, research_id: str, owner_id: str) -> ResearchRecord:
        """读取研究。参数：研究、用户。返回：研究。异常：不存在或越权。"""
        ...

    def list_research(self, owner_id: str, *, state: ResearchState | None = None) -> list[ResearchRecord]:
        """列出研究。参数：用户、状态。返回：列表。异常：存储错误。"""
        ...

    def archive(self, research_id: str, owner_id: str) -> ResearchRecord:
        """归档。参数：研究、用户。返回：研究。异常：繁忙或越权。"""
        ...

    def reopen(self, research_id: str, owner_id: str) -> ResearchRecord:
        """打开。参数：研究、用户。返回：研究。异常：越权。"""
        ...


class ResearchTurnQueue(Protocol):
    """持久输入排队与 Host 受理关联端口。"""

    def enqueue(self, request: SubmitResearchTurnRequest, preparation: ResearchTurnPreparation) -> ResearchTurn:
        """接受输入及规格。参数：请求、已准备规格。返回：输入。异常：冲突或越权。"""
        ...

    def find(self, request: SubmitResearchTurnRequest) -> ResearchTurn | None:
        """查询原始受理。参数：原请求。返回：原输入或空。异常：冲突或越权。"""
        ...

    def get(self, turn_id: str, owner_id: str) -> ResearchTurn:
        """查询输入。参数：输入、用户。返回：输入。异常：不存在或越权。"""
        ...

    def claim_next(self, research_id: str, owner_id: str, *, host_epoch: int = 0) -> ResearchTurn | None:
        """领取输入。参数：研究、用户、Host 代际。返回：输入或空。异常：越权。"""
        ...

    def active(self, research_id: str, owner_id: str) -> ResearchTurn | None:
        """恢复派发输入。参数：研究、用户。返回：输入或空。异常：越权。"""
        ...

    def latest(self, research_id: str, owner_id: str) -> ResearchTurn | None:
        """读取最新输入。参数：研究、用户。返回：输入或空。异常：越权。"""
        ...

    def latest_executed(self, research_id: str, owner_id: str) -> ResearchTurn | None:
        """读取最近已受理执行的输入。参数：研究、用户。返回：输入或空。异常：越权。"""
        ...

    def queued_count(self, research_id: str, owner_id: str) -> int:
        """读取排队数量。参数：研究、用户。返回：数量。异常：越权。"""
        ...

    def mark_submitted(self, turn_id: str, run_id: str) -> ResearchTurn:
        """关联受理。参数：输入、Run。返回：输入。异常：状态冲突。"""
        ...

    def request_resume(self, turn_id: str, owner_id: str, request_key: str, *, host_epoch: int) -> ResearchTurn:
        """预留恢复派发。参数：输入、用户、稳定键、代际。返回：原输入。异常：越权或繁忙。"""
        ...

    def settle(self, turn_id: str, run_id: str) -> ResearchTurn:
        """结束派发。参数：输入、Run。返回：输入。异常：状态冲突。"""
        ...

    def cancel_queued(self, research_id: str, owner_id: str, *, through_sequence: int | None = None) -> int:
        """取消排队。参数：研究、用户、序号上界。返回：取消数。异常：越权。"""
        ...

    def begin_stop(self, research_id: str, owner_id: str, request_key: str, *, expected_version: int | None = None) -> ResearchStopFence:
        """建立边界。参数：研究、用户、停止键。返回：边界。异常：越权。"""
        ...

    def complete_stop(self, stop_id: str, owner_id: str, *, host_epoch: int) -> ResearchStopFence:
        """确认 fencing。参数：停止 ID、用户、Host 代际。返回：边界。异常：冲突或越权。"""
        ...


class ResearchArtifactStore(Protocol):
    """不可变研究快照文件端口。"""

    def commit_snapshot(
        self, research_id: str, revision_id: str, *, report_markdown: str,
        evidence_json: str, metadata_json: str, data_contract_json: str | None,
    ) -> str:
        """提交快照。参数：研究、版本与显式内容。返回：摘要。异常：冲突或存储错误。"""
        ...

    def read_report(self, research_id: str, revision_id: str, expected_hash: str) -> str:
        """读取报告。参数：研究、版本、摘要。返回：正文。异常：完整性错误。"""
        ...

    def read_content(self, research_id: str, revision_id: str, expected_hash: str) -> ResearchReportContent:
        """读取完整快照。参数：研究、版本、摘要。返回：正文、证据、契约。异常：完整性失败。"""
        ...


class ResearchRevisions(Protocol):
    """正式报告版本端口。"""

    def commit(self, request: CommitResearchRevisionRequest) -> ResearchRevision:
        """提交报告。参数：输入。返回：版本。异常：来源或内容冲突。"""
        ...

    def get(self, revision_id: str, owner_id: str) -> ResearchRevision:
        """读取版本。参数：版本、用户。返回：版本。异常：不存在或越权。"""
        ...

    def list_revisions(self, research_id: str, owner_id: str) -> list[ResearchRevision]:
        """列出版本。参数：研究、用户。返回：列表。异常：越权。"""
        ...

    def read_report(self, revision_id: str, owner_id: str) -> str:
        """读取报告。参数：版本、用户。返回：正文。异常：越权或完整性错误。"""
        ...

    def read_content(self, revision_id: str, owner_id: str) -> ResearchReportContent:
        """按所有权读取完整快照。参数：版本、用户。返回：正文、证据、契约。异常：越权或损坏。"""
        ...


class ResearchBindings(Protocol):
    """研究与渠道话题的唯一绑定端口。"""

    def bind(self, request: BindResearchChannelRequest) -> ResearchChannelBinding:
        """显式绑定。参数：请求。返回：绑定。异常：冲突或越权。"""
        ...

    def resolve(
        self, *, owner_id: str, channel: str, instance_id: str, conversation_id: str, topic_id: str,
    ) -> ResearchChannelBinding | None:
        """定位话题。参数：用户与完整渠道定位。返回：绑定或空。异常：越权。"""
        ...

    def for_research(self, research_id: str, owner_id: str, *, channel: str, instance_id: str) -> ResearchChannelBinding | None:
        """查找研究话题。参数：研究、用户、渠道及实例。返回：绑定或空。异常：越权。"""
        ...


class ResearchMethods(Protocol):
    """不可变方法资源端口。"""

    def pin(self, files: Mapping[str, bytes]) -> ResearchMethodBundle:
        """固定方法。参数：资源映射。返回：方法包。异常：资源冲突或路径非法。"""
        ...

    def load(self, method_hash: str) -> ResearchMethodBundle:
        """读取原方法。参数：哈希。返回：方法包。异常：缺失或完整性失败。"""
        ...

    def read_reference(self, method_hash: str, path: str) -> str:
        """读取原方法参考。参数：哈希、包内相对路径。返回：正文。异常：越界、缺失或完整性失败。"""
        ...


class ResearchWorkingRecords(Protocol):
    """输入作用域内的工作日志端口，不管理执行生命周期。"""

    def scope_for_run(self, run_id: str) -> ResearchWorkScope:
        """解析作用域。参数：Run。返回：受理作用域。异常：不存在。"""
        ...

    def append_note(self, scope: ResearchWorkScope, tool_call_id: str, *, title: str, content: str) -> ResearchWorkingRecord:
        """保存笔记。参数：作用域、调用、标题、正文。返回：记录。异常：输入或状态冲突。"""
        ...

    def list_named_notes(self, scope: ResearchWorkScope, title: str) -> list[ResearchWorkingRecord]:
        """读取同研究指定类别的历史笔记。参数：作用域、标题。返回：截止内不可变记录。异常：越权或损坏。"""
        ...

    def append_calculation(
        self, scope: ResearchWorkScope, tool_call_id: str, *, method: str, inputs: dict[str, JsonValue],
        result: dict[str, JsonValue], accepted: bool,
    ) -> ResearchWorkingRecord:
        """保存计算。参数：作用域、调用、方法、输入、结果、是否通过。返回：记录。异常：状态冲突。"""
        ...

    def append_report(self, scope: ResearchWorkScope, tool_call_id: str, report: ResearchReportContent) -> ResearchWorkingRecord:
        """保存报告草稿。参数：作用域、调用、报告。返回：记录。异常：状态或证据非法。"""
        ...

    def list_records(self, scope: ResearchWorkScope, *, after_sequence: int = 0, limit: int = 20) -> list[ResearchWorkingRecord]:
        """列出记录。参数：作用域、游标、数量。返回：列表。异常：范围或作用域非法。"""
        ...

    def get_record(self, scope: ResearchWorkScope, record_id: str) -> ResearchWorkingRecord:
        """读取记录。参数：作用域、ID。返回：记录。异常：不存在或越界。"""
        ...

    def list_checkpoints(self, scope: ResearchWorkScope, *, limit: int = 20) -> list[dict[str, JsonValue]]:
        """列出同研究历史工作记录。参数：作用域、数量。返回：带截止与方法的索引。异常：越界。"""
        ...

    def read_checkpoint(self, scope: ResearchWorkScope, record_id: str) -> dict[str, JsonValue]:
        """读取历史工作记录。参数：作用域、记录。返回：正文与来源。异常：截止越界或损坏。"""
        ...

    def latest_report(self, scope: ResearchWorkScope) -> ResearchReportContent | None:
        """读取当前 Run 草稿。参数：作用域。返回：报告或空。异常：完整性失败。"""
        ...
