"""渠道话题到研究的唯一绑定仓储，不推测外部 UI 的导航能力。"""

from __future__ import annotations

import sqlite3
from uuid import uuid4

from alpha.contracts.research import ResearchConflictError
from alpha.contracts.research_channels import BindResearchChannelRequest, ResearchChannelBinding
from alpha.research.storage.encoding import owned_research
from alpha.research.storage.store import ResearchStore


def _binding(row: sqlite3.Row) -> ResearchChannelBinding:
    """投影绑定。参数：数据行。返回：绑定。异常：无。"""
    return ResearchChannelBinding(str(row["binding_id"]), str(row["research_id"]), str(row["channel"]),
                                  str(row["instance_id"]), str(row["conversation_id"]), str(row["topic_id"]))


class SQLiteResearchBindings:
    """固定渠道实例内一研究对应一话题，重复回调不改变绑定。"""

    def __init__(self, store: ResearchStore) -> None:
        """注入研究库。参数：store 存储。返回：无。异常：无。"""
        self._store = store

    def bind(self, request: BindResearchChannelRequest) -> ResearchChannelBinding:
        """显式绑定。参数：request 定位与所有权。返回：绑定。异常：越权、定位冲突或空字段。"""
        scope = (request.channel, request.instance_id, request.conversation_id, request.topic_id)
        if not all(value.strip() for value in scope):
            raise ValueError("绑定的渠道、实例、会话和话题均不能为空")
        with self._store.connection(write=True) as conn:
            owned_research(conn, request.research_id, request.owner_id)
            existing = conn.execute(
                "SELECT * FROM research_channel_bindings WHERE channel=? AND instance_id=? AND conversation_id=? AND topic_id=?",
                scope,
            ).fetchone()
            if existing is not None:
                if str(existing["research_id"]) != request.research_id:
                    raise ResearchConflictError("该话题已绑定其他研究")
                return _binding(existing)
            research_binding = conn.execute(
                "SELECT 1 FROM research_channel_bindings WHERE research_id=? AND channel=? AND instance_id=?",
                (request.research_id, request.channel, request.instance_id),
            ).fetchone()
            if research_binding is not None:
                raise ResearchConflictError("该研究已在本渠道绑定其他话题")
            binding_id = f"binding_{uuid4().hex}"
            conn.execute("INSERT INTO research_channel_bindings VALUES (?,?,?,?,?,?)", (binding_id, request.research_id, *scope))
            row = conn.execute("SELECT * FROM research_channel_bindings WHERE binding_id=?", (binding_id,)).fetchone()
            return _binding(row)

    def resolve(
        self, *, owner_id: str, channel: str, instance_id: str, conversation_id: str, topic_id: str,
    ) -> ResearchChannelBinding | None:
        """解析当前话题。参数：所有者与完整定位。返回：绑定或空。异常：越权。"""
        with self._store.connection() as conn:
            row = conn.execute(
                "SELECT * FROM research_channel_bindings WHERE channel=? AND instance_id=? AND conversation_id=? AND topic_id=?",
                (channel, instance_id, conversation_id, topic_id),
            ).fetchone()
            if row is None:
                return None
            owned_research(conn, str(row["research_id"]), owner_id)
            return _binding(row)

    def for_research(self, research_id: str, owner_id: str, *, channel: str, instance_id: str) -> ResearchChannelBinding | None:
        """查找研究的渠道话题。参数：研究、用户、渠道、实例。返回：绑定或空。异常：越权或不存在。"""
        with self._store.connection() as conn:
            owned_research(conn, research_id, owner_id)
            row = conn.execute(
                "SELECT * FROM research_channel_bindings WHERE research_id=? AND channel=? AND instance_id=?",
                (research_id, channel, instance_id),
            ).fetchone()
            return _binding(row) if row is not None else None
