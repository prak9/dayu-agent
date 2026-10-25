"""指定报告版本的发布意图、固定正文和有进程身份的业务租约。"""

from __future__ import annotations

import sqlite3
import time
from uuid import uuid4

from alpha.contracts.publication import PublicationClaim, PublicationPayload, PublicationState, PublishResearchRequest, ResearchPublication
from alpha.contracts.research import ResearchConflictError
from alpha.process_liveness import OwnerIdentity, current_owner_identity, is_owner_identity_alive
from alpha.research.storage.encoding import canonical_json, content_hash, encode_time, utc_now
from alpha.research.storage.store import ResearchStore
from alpha.research.publication_identity import publication_identifier
from alpha.research.publication_segments import split_publication

_SELECT = "SELECT p.*,r.research_id,c.owner_id FROM research_publications p JOIN research_revisions r ON r.revision_id=p.revision_id JOIN research_catalog c ON c.research_id=r.research_id"


def _text(row: sqlite3.Row, name: str) -> str | None:
    """投影可空文本。参数：行、字段。返回：文本或空。异常：无。"""
    return str(row[name]) if row[name] is not None else None


def _publication(row: sqlite3.Row) -> ResearchPublication:
    """投影发布业务状态。参数：行。返回：记录。异常：损坏字段。"""
    return ResearchPublication(str(row["publication_id"]), str(row["revision_id"]), str(row["target_id"]), str(row["content_hash"]),
                               PublicationState(str(row["state"])), _text(row, "run_id"), _text(row, "page_id"), _text(row, "page_url"),
                               _text(row, "remote_task_id"), _text(row, "error"))


def _payload(row: sqlite3.Row) -> PublicationPayload:
    """核验固定正文。参数：行。返回：正文。异常：完整性损坏。"""
    title, markdown = str(row["title"]), str(row["markdown"])
    digest = content_hash(canonical_json({"title": title, "markdown": markdown}))
    if digest != str(row["payload_hash"]):
        raise ResearchConflictError("发布正文快照完整性损坏")
    return PublicationPayload(str(row["owner_id"]), str(row["research_id"]), title, markdown, digest)


def _require(conn: sqlite3.Connection, publication_id: str, *, lease_id: str | None = None) -> sqlite3.Row:
    """读取并可选 fencing。参数：连接、发布 ID、租约。返回：行。异常：不存在或租约失效。"""
    row: sqlite3.Row | None = conn.execute(_SELECT + " WHERE p.publication_id=?", (publication_id,)).fetchone()
    if row is None:
        raise KeyError(f"发布意图不存在：{publication_id}")
    if lease_id is not None and row["lease_id"] != lease_id:
        raise ResearchConflictError("发布执行租约已过期，拒绝迟到结果")
    return row


def _holder_alive(row: sqlite3.Row) -> bool:
    """核验业务执行者。参数：发布行。返回：是否仍持有存活进程。异常：进程查询错误。"""
    return row["lease_id"] is not None and row["owner_pid"] is not None and is_owner_identity_alive(OwnerIdentity(
        int(row["owner_pid"]), float(row["owner_start_time"]) if row["owner_start_time"] is not None else None, _text(row, "owner_boot_id"),
    ))


def _segments(conn: sqlite3.Connection, row: sqlite3.Row) -> tuple[str, ...]:
    """核验冻结分段连续性和完整内容。参数：连接、发布行。返回：原始分段。异常：损坏。"""
    rows = conn.execute("SELECT * FROM publication_segments WHERE publication_id=? ORDER BY position", (row["publication_id"],)).fetchall()
    segments = tuple(str(item["markdown"]) for item in rows)
    if (not rows or "".join(segments) != str(row["markdown"]) or any(
            int(item["position"]) != index or content_hash(str(item["markdown"])) != str(item["content_hash"])
            for index, item in enumerate(rows))):
        raise ResearchConflictError("发布分段快照完整性损坏")
    return segments


class SQLiteResearchPublications:
    """一版一目标唯一发布，未知结果不因租约接管而重新创建页面。"""

    def __init__(self, store: ResearchStore) -> None:
        """注入研究库。参数：存储。返回：无。异常：无。"""
        self._store = store

    def request(self, request: PublishResearchRequest, *, target_id: str, title: str, markdown: str) -> ResearchPublication:
        """接受明确版本意图并冻结首份正文。参数：授权、固定目标、标题、正文。返回：原或新发布。异常：越权、无报告或键冲突。"""
        if not request.request_key.strip() or not target_id.strip() or not title.strip() or not markdown.strip():
            raise ValueError("发布请求键、固定目标和正文不能为空")
        fingerprint = content_hash(canonical_json({"revision_id": request.revision_id, "target_id": target_id}))
        with self._store.connection(write=True) as conn:
            revision = conn.execute("SELECT r.*,c.owner_id FROM research_revisions r JOIN research_catalog c ON c.research_id=r.research_id WHERE r.revision_id=?",
                                    (request.revision_id,)).fetchone()
            if revision is None:
                raise KeyError("只能发布已提交的正式报告版本")
            if str(revision["owner_id"]) != request.owner_id:
                raise PermissionError("无权发布该报告")
            previous = conn.execute("SELECT * FROM publication_requests WHERE owner_id=? AND request_key=?", (request.owner_id, request.request_key)).fetchone()
            if previous is not None and str(previous["input_hash"]) != fingerprint:
                raise ResearchConflictError("相同发布请求键的目标版本改变")
            existing = conn.execute(_SELECT + " WHERE p.revision_id=? AND p.target_id=?", (request.revision_id, target_id)).fetchone()
            if existing is None:
                identifier = publication_identifier(request.revision_id, target_id)
                payload_hash = content_hash(canonical_json({"title": title, "markdown": markdown}))
                conn.execute("INSERT INTO research_publications(publication_id,revision_id,target_id,content_hash,title,markdown,payload_hash,state,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                             (identifier, request.revision_id, target_id, revision["content_hash"], title, markdown, payload_hash,
                              PublicationState.PENDING.value, encode_time(utc_now())))
                conn.executemany("INSERT INTO publication_segments VALUES (?,?,?,?)", [
                    (identifier, index, segment, content_hash(segment)) for index, segment in enumerate(split_publication(markdown))])
                existing = _require(conn, identifier)
            _payload(existing)
            if previous is None and str(existing["state"]) == PublicationState.FAILED_TERMINAL.value:
                if _holder_alive(existing):
                    raise ResearchConflictError("原发布执行正在释放资源，请稍后重试")
                # 新的明确请求可在修复权限后重试；创建边界已经跨过时只能只读调和。
                state = PublicationState.RECONCILING if bool(existing["creation_started"]) else PublicationState.PENDING
                conn.execute("UPDATE research_publications SET state=?,error=NULL,retry_at=0 WHERE publication_id=?",
                             (state.value, existing["publication_id"]))
                existing = _require(conn, str(existing["publication_id"]))
            conn.execute("INSERT OR IGNORE INTO publication_requests VALUES (?,?,?,?)",
                         (request.owner_id, request.request_key, fingerprint, existing["publication_id"]))
            return _publication(existing)

    def get(self, publication_id: str, owner_id: str) -> ResearchPublication:
        """校验所有权后查询状态。参数：发布、用户。返回：记录。异常：越权、缺失或损坏。"""
        with self._store.connection() as conn:
            row = _require(conn, publication_id)
            if str(row["owner_id"]) != owner_id:
                raise PermissionError("无权查看该发布")
            _payload(row)
            return _publication(row)

    def list_for_owner(self, owner_id: str) -> list[ResearchPublication]:
        """列出所有者的发布结果。参数：用户。返回：按创建时间排列的记录。异常：正文损坏。"""
        with self._store.connection() as conn:
            rows = conn.execute(_SELECT + " WHERE c.owner_id=? ORDER BY p.created_at,p.publication_id", (owner_id,)).fetchall()
            for row in rows:
                _payload(row)
            return [_publication(row) for row in rows]

    def claim_next(self) -> PublicationClaim | None:
        """领取到期工作。参数：无。返回：含恢复标记的租约或空。异常：正文损坏。"""
        with self._store.connection(write=True) as conn:
            rows = conn.execute(_SELECT + " WHERE p.state IN (?,?,?,?) AND p.retry_at<=? ORDER BY p.created_at,p.publication_id",
                                (PublicationState.PENDING.value, PublicationState.PUBLISHING.value, PublicationState.RECONCILING.value,
                                 PublicationState.FAILED_RETRYABLE.value, time.time())).fetchall()
            for row in rows:
                held = row["lease_id"] is not None
                if _holder_alive(row):
                    continue
                interrupted = held
                state = PublicationState.RECONCILING if interrupted or str(row["state"]) == PublicationState.RECONCILING.value else PublicationState.PUBLISHING
                owner = current_owner_identity()
                lease = uuid4().hex
                conn.execute("UPDATE research_publications SET state=?,lease_id=?,owner_pid=?,owner_start_time=?,owner_boot_id=?,attempt=MAX(attempt,1) WHERE publication_id=?",
                             (state.value, lease, owner.pid, owner.process_start_time, owner.boot_id, row["publication_id"]))
                current = _require(conn, str(row["publication_id"]))
                return PublicationClaim(_publication(current), _payload(current), lease, int(current["attempt"]), interrupted,
                                        bool(current["creation_started"]), _segments(conn, current), int(current["written_segments"]))
            return None

    def advance_attempt(self, claim: PublicationClaim) -> PublicationClaim:
        """原 Host 尝试已终态后登记新尝试。参数：当前租约。返回：新尝试身份。异常：租约失效。"""
        with self._store.connection(write=True) as conn:
            _require(conn, claim.publication.publication_id, lease_id=claim.lease_id)
            conn.execute("UPDATE research_publications SET attempt=attempt+1,run_id=NULL WHERE publication_id=?", (claim.publication.publication_id,))
            row = _require(conn, claim.publication.publication_id)
            return PublicationClaim(_publication(row), _payload(row), claim.lease_id, int(row["attempt"]), claim.interrupted,
                                    bool(row["creation_started"]), _segments(conn, row), int(row["written_segments"]))

    def record_progress(self, claim: PublicationClaim, written: int) -> None:
        """回读验证后单调推进分段。参数：租约、已写段数。返回：无。异常：退步、越界或租约失效。"""
        with self._store.connection(write=True) as conn:
            row = _require(conn, claim.publication.publication_id, lease_id=claim.lease_id)
            if not int(row["written_segments"]) <= written <= len(_segments(conn, row)):
                raise ResearchConflictError("发布分段进度不能退步或越界")
            conn.execute("UPDATE research_publications SET written_segments=? WHERE publication_id=?", (written, claim.publication.publication_id))

    def mark_creation_started(self, claim: PublicationClaim) -> None:
        """在外部 POST 前持久跨过创建边界。参数：租约。返回：无。异常：租约失效或已经跨过边界。"""
        with self._store.connection(write=True) as conn:
            row = _require(conn, claim.publication.publication_id, lease_id=claim.lease_id)
            if bool(row["creation_started"]):
                raise ResearchConflictError("创建请求可能已经发送，必须先调和")
            conn.execute("UPDATE research_publications SET creation_started=1 WHERE publication_id=?", (claim.publication.publication_id,))

    def mark_creation_rejected(self, claim: PublicationClaim) -> None:
        """明确无副作用的创建拒绝后恢复创建资格。参数：租约。返回：无。异常：已知远端身份或租约冲突。"""
        with self._store.connection(write=True) as conn:
            row = _require(conn, claim.publication.publication_id, lease_id=claim.lease_id)
            if row["page_id"] is not None or row["remote_task_id"] is not None:
                raise ResearchConflictError("已有远端身份，不能清除创建边界")
            conn.execute("UPDATE research_publications SET creation_started=0 WHERE publication_id=?", (claim.publication.publication_id,))

    def link_run(self, claim: PublicationClaim, run_id: str) -> None:
        """记录 Host 持久接受结果。参数：租约、Run。返回：无。异常：来源变化或租约失效。"""
        with self._store.connection(write=True) as conn:
            row = _require(conn, claim.publication.publication_id, lease_id=claim.lease_id)
            if row["run_id"] is not None and str(row["run_id"]) != run_id:
                raise ResearchConflictError("同一发布执行尝试不能更换 Run")
            conn.execute("UPDATE research_publications SET run_id=? WHERE publication_id=?", (run_id, claim.publication.publication_id))

    def save_page(self, claim: PublicationClaim, page_id: str, page_url: str) -> None:
        """保存已知页面并清除已完成创建任务。参数：租约、页面、URL。返回：无。异常：不同页面冲突。"""
        with self._store.connection(write=True) as conn:
            row = _require(conn, claim.publication.publication_id, lease_id=claim.lease_id)
            if row["page_id"] is not None and str(row["page_id"]) != page_id:
                raise ResearchConflictError("同一发布找到多个远端页面")
            conn.execute("UPDATE research_publications SET page_id=?,page_url=?,remote_task_id=NULL,creation_started=1 WHERE publication_id=?",
                         (page_id, page_url, claim.publication.publication_id))

    def save_task(self, claim: PublicationClaim, task_id: str) -> None:
        """保存远端异步身份，不能因此宣称发布成功。参数：租约、task ID。返回：无。异常：租约失效。"""
        with self._store.connection(write=True) as conn:
            _require(conn, claim.publication.publication_id, lease_id=claim.lease_id)
            conn.execute("UPDATE research_publications SET remote_task_id=?,creation_started=1 WHERE publication_id=?", (task_id, claim.publication.publication_id))

    def mark_published(self, claim: PublicationClaim) -> ResearchPublication:
        """业务完成回读后确认发布。参数：当前租约。返回：发布结果。异常：无页面、任务未完或租约失效。"""
        with self._store.connection(write=True) as conn:
            row = _require(conn, claim.publication.publication_id, lease_id=claim.lease_id)
            if row["page_id"] is None or row["remote_task_id"] is not None:
                raise ResearchConflictError("页面未知或任务未完成，不能确认发布")
            if int(row["written_segments"]) != len(_segments(conn, row)):
                raise ResearchConflictError("发布分段尚未全部回读确认")
            conn.execute("UPDATE research_publications SET state=?,error=NULL,retry_at=0 WHERE publication_id=?",
                         (PublicationState.PUBLISHED.value, claim.publication.publication_id))
            return _publication(_require(conn, claim.publication.publication_id))

    def defer(self, claim: PublicationClaim, state: PublicationState, error: str, *, retry_after: float = 0) -> None:
        """记录失败或待调和。参数：租约、明确状态、错误、重试延迟。返回：无。异常：非法状态、终态或租约失效。"""
        if state not in (PublicationState.FAILED_RETRYABLE, PublicationState.FAILED_TERMINAL, PublicationState.RECONCILING, PublicationState.PUBLISHING):
            raise ValueError("非法发布延后状态")
        with self._store.connection(write=True) as conn:
            row = _require(conn, claim.publication.publication_id, lease_id=claim.lease_id)
            if str(row["state"]) == PublicationState.PUBLISHED.value:
                raise ResearchConflictError("已发布页面不允许改回写入状态")
            conn.execute("UPDATE research_publications SET state=?,error=?,retry_at=? WHERE publication_id=?",
                         (state.value, error, time.time() + retry_after, claim.publication.publication_id))

    def release(self, claim: PublicationClaim) -> None:
        """释放自身业务租约。参数：租约。返回：无。异常：数据库错误。"""
        with self._store.connection(write=True) as conn:
            conn.execute("UPDATE research_publications SET lease_id=NULL,owner_pid=NULL,owner_start_time=NULL,owner_boot_id=NULL WHERE publication_id=? AND lease_id=?",
                         (claim.publication.publication_id, claim.lease_id))
