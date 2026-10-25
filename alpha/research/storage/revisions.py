"""正式报告提交：文件快照先提交，数据库引用最后提交。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research_working import ResearchReportContent
from alpha.contracts.research import CommitResearchRevisionRequest, ResearchConflictError, ResearchRevision, ResearchTurnState
from alpha.research.storage.encoding import canonical_json, encode_time, owned_research, utc_now
from alpha.research.storage.protocols import ResearchArtifactStore
from alpha.research.storage.store import ResearchStore
from alpha.research.evidence import encode_research_evidence


def _revision_from_row(row: sqlite3.Row) -> ResearchRevision:
    """投影版本记录。参数：row 数据行。返回：版本。异常：损坏时间导致 ValueError。"""
    return ResearchRevision(
        revision_id=str(row["revision_id"]), research_id=str(row["research_id"]), number=int(row["number"]),
        parent_revision_id=str(row["parent_revision_id"]) if row["parent_revision_id"] is not None else None,
        source_turn_id=str(row["source_turn_id"]), source_run_id=str(row["source_run_id"]),
        as_of=datetime.fromisoformat(str(row["as_of"])), content_hash=str(row["content_hash"]),
        skill_hash=str(row["skill_hash"]), created_at=datetime.fromisoformat(str(row["created_at"])),
    )


class SQLiteResearchRevisions:
    """同一来源输入只提交一个版本，重放校验完整内容。"""

    def __init__(self, store: ResearchStore, artifacts: ResearchArtifactStore) -> None:
        """注入持久存储。参数：store 数据库、artifacts 文件端口。返回：无。异常：无。"""
        self._store = store
        self._artifacts = artifacts

    def commit(self, request: CommitResearchRevisionRequest) -> ResearchRevision:
        """提交不可变报告。参数：request 来源与内容。返回：版本。异常：越权、来源冲突或完整性错误。"""
        if not request.report_markdown.strip() or not request.skill_hash.strip():
            raise ValueError("正式报告和方法 hash 不能为空")
        data_contract = None if request.data_contract_json is None else canonical_json(
            cast(JsonValue, json.loads(request.data_contract_json))
        )
        with self._store.connection(write=True) as conn:
            owned_research(conn, request.research_id, request.owner_id)
            turn = conn.execute(
                "SELECT * FROM research_turns WHERE turn_id=? AND research_id=?", (request.source_turn_id, request.research_id),
            ).fetchone()
            if turn is None or str(turn["run_id"]) != request.source_run_id or str(turn["state"]) not in (
                ResearchTurnState.SUBMITTED.value, ResearchTurnState.SETTLED.value,
            ):
                raise ResearchConflictError("正式版本必须关联已受理的研究输入及其 Host Run")
            as_of = datetime.fromisoformat(str(turn["as_of"]))
            if str(turn["method_hash"]) != request.skill_hash:
                raise ResearchConflictError("报告方法必须与首次接受的方法包相同")
            # ID 与首次提交时间无关，文件已提交而 DB 回滚时可精确复用孤立快照。
            revision_id = "revision_" + uuid5(NAMESPACE_URL, f"alpha:{request.research_id}:{request.source_turn_id}").hex
            fingerprint = self._artifacts.commit_snapshot(
                request.research_id, revision_id, report_markdown=request.report_markdown,
                evidence_json=canonical_json(encode_research_evidence(request.evidence, as_of)), data_contract_json=data_contract,
                metadata_json=canonical_json({
                    "source_turn_id": request.source_turn_id, "source_run_id": request.source_run_id,
                    "as_of": encode_time(as_of), "skill_hash": request.skill_hash,
                }),
            )
            existing = conn.execute("SELECT * FROM research_revisions WHERE revision_id=?", (revision_id,)).fetchone()
            if existing is not None:
                if str(existing["content_hash"]) != fingerprint:
                    raise ResearchConflictError("正式报告内容不可变")
                return _revision_from_row(existing)
            previous = conn.execute(
                "SELECT * FROM research_revisions WHERE research_id=? ORDER BY number DESC LIMIT 1", (request.research_id,),
            ).fetchone()
            number = int(previous["number"]) + 1 if previous is not None else 1
            parent_id = str(previous["revision_id"]) if previous is not None else None
            conn.execute(
                "INSERT INTO research_revisions VALUES (?,?,?,?,?,?,?,?,?,?)",
                (revision_id, request.research_id, number, parent_id, request.source_turn_id, request.source_run_id,
                 encode_time(as_of), fingerprint, request.skill_hash, encode_time(utc_now())),
            )
            return self._get(conn, revision_id, request.owner_id)

    def _get(self, conn: sqlite3.Connection, revision_id: str, owner_id: str) -> ResearchRevision:
        """读取并校验版本所有权。参数：连接、版本、用户。返回：版本。异常：不存在或越权。"""
        row = conn.execute("SELECT * FROM research_revisions WHERE revision_id=?", (revision_id,)).fetchone()
        if row is None:
            raise KeyError(f"研究版本不存在：{revision_id}")
        owned_research(conn, str(row["research_id"]), owner_id)
        return _revision_from_row(row)

    def get(self, revision_id: str, owner_id: str) -> ResearchRevision:
        """读取版本。参数：版本、用户。返回：版本。异常：不存在或越权。"""
        with self._store.connection() as conn:
            return self._get(conn, revision_id, owner_id)

    def list_revisions(self, research_id: str, owner_id: str) -> list[ResearchRevision]:
        """列出研究版本。参数：研究、用户。返回：版本顺序列表。异常：不存在或越权。"""
        with self._store.connection() as conn:
            owned_research(conn, research_id, owner_id)
            return [_revision_from_row(row) for row in conn.execute(
                "SELECT * FROM research_revisions WHERE research_id=? ORDER BY number", (research_id,),
            ).fetchall()]

    def read_report(self, revision_id: str, owner_id: str) -> str:
        """完整性校验后读取报告。参数：版本、用户。返回：正文。异常：越权或损坏。"""
        revision = self.get(revision_id, owner_id)
        return self._artifacts.read_report(revision.research_id, revision_id, revision.content_hash)

    def read_content(self, revision_id: str, owner_id: str) -> ResearchReportContent:
        """按所有权读取全部证据及数据契约。参数：版本、用户。返回：完整内容。异常：越权、缺失或完整性失败。"""
        revision = self.get(revision_id, owner_id)
        return self._artifacts.read_content(revision.research_id, revision_id, revision.content_hash)
