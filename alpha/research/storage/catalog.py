"""研究目录与归档状态仓储，不管理 Host Session 生命周期。"""

from __future__ import annotations

from uuid import uuid4

from alpha.contracts.research import CreateResearchRequest, ResearchConflictError, ResearchRecord, ResearchState
from alpha.research.storage.encoding import canonical_json, content_hash, encode_time, owned_research, research_from_row, utc_now
from alpha.research.storage.store import ResearchStore


class SQLiteResearchCatalog:
    """按所有权隔离研究、固定 Session 关联并校验归档条件。"""

    def __init__(self, store: ResearchStore) -> None:
        """注入存储。参数：store 事务基础设施。返回：无。异常：无。"""
        self._store = store

    def create(self, request: CreateResearchRequest) -> ResearchRecord:
        """幂等创建研究。参数：request 显式输入。返回：研究。异常：空输入、键冲突或存储错误。"""
        if not request.owner_id.strip() or not request.request_key.strip() or not request.question.strip():
            raise ValueError("owner_id、request_key 和研究问题不能为空")
        encoded_cutoff = encode_time(request.as_of)
        fingerprint = content_hash(canonical_json({
            "question": request.question, "title": request.title, "subjects": list(request.subjects),
            "as_of": encoded_cutoff, "depth": request.depth.value,
        }))
        with self._store.connection(write=True) as conn:
            existing = conn.execute(
                "SELECT * FROM research_catalog WHERE owner_id=? AND request_key=?",
                (request.owner_id, request.request_key),
            ).fetchone()
            if existing is not None:
                if str(existing["input_hash"]) != fingerprint:
                    raise ResearchConflictError("相同创建键的输入发生变化")
                return research_from_row(existing)
            research_id = f"research_{uuid4().hex}"
            now = encode_time(utc_now())
            conn.execute(
                "INSERT INTO research_catalog VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (research_id, request.owner_id, request.request_key, fingerprint, request.title or request.question,
                 request.question, canonical_json(list(request.subjects)), research_id, ResearchState.ACTIVE.value,
                 1, encoded_cutoff, request.depth.value, now, now),
            )
            return research_from_row(owned_research(conn, research_id, request.owner_id))

    def get(self, research_id: str, owner_id: str) -> ResearchRecord:
        """读取研究。参数：research_id、owner_id。返回：研究。异常：不存在、越权或存储错误。"""
        with self._store.connection() as conn:
            return research_from_row(owned_research(conn, research_id, owner_id))

    def list_research(self, owner_id: str, *, state: ResearchState | None = None) -> list[ResearchRecord]:
        """列出用户研究。参数：owner_id 用户、state 可选过滤。返回：更新时间降序列表。异常：存储错误。"""
        with self._store.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM research_catalog WHERE owner_id=? AND (? IS NULL OR state=?) "
                "ORDER BY updated_at DESC, research_id", (owner_id, state, state),
            ).fetchall()
            return [research_from_row(row) for row in rows]

    def archive(self, research_id: str, owner_id: str) -> ResearchRecord:
        """归档空闲研究。参数：research_id、owner_id。返回：研究。异常：繁忙、越权或不存在。"""
        return self._set_state(research_id, owner_id, ResearchState.ARCHIVED)

    def reopen(self, research_id: str, owner_id: str) -> ResearchRecord:
        """重新打开研究。参数：research_id、owner_id。返回：保留原 Session 的研究。异常：越权或不存在。"""
        return self._set_state(research_id, owner_id, ResearchState.ACTIVE)

    def _set_state(self, research_id: str, owner_id: str, state: ResearchState) -> ResearchRecord:
        """原子切换业务状态。参数：研究、所有者、目标状态。返回：研究。异常：繁忙或所有权错误。"""
        with self._store.connection(write=True) as conn:
            row = owned_research(conn, research_id, owner_id)
            if state == ResearchState.ARCHIVED:
                busy = conn.execute(
                    "SELECT 1 FROM research_turns WHERE research_id=? AND state IN ('queued','dispatching','submitted')",
                    (research_id,),
                ).fetchone()
                if busy is not None:
                    raise ResearchConflictError("研究仍有待处理输入，请先停止并等待执行结束")
                stopping = conn.execute("SELECT 1 FROM research_stop_fences WHERE research_id=? AND completed_epoch IS NULL",
                                        (research_id,)).fetchone()
                if stopping is not None:
                    raise ResearchConflictError("停止请求尚未完成 Host fencing")
            if str(row["state"]) != state.value:
                conn.execute(
                    "UPDATE research_catalog SET state=?,version=version+1,updated_at=? WHERE research_id=?",
                    (state.value, encode_time(utc_now()), research_id),
                )
            return research_from_row(owned_research(conn, research_id, owner_id))
