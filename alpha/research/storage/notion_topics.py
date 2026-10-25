"""研究主题页绑定；研究 ID 与 Invest 根目录共同确定身份。"""

import sqlite3
from uuid import uuid4

from alpha.contracts.notion_topics import ResearchTopicClaim
from alpha.contracts.research import ResearchConflictError
from alpha.process_liveness import OwnerIdentity, current_owner_identity, is_owner_identity_alive
from alpha.research.storage.encoding import owned_research
from alpha.research.storage.store import ResearchStore


def _text(row: sqlite3.Row, field: str) -> str | None:
    """读取可空字段。参数：行、字段。返回：文本或空。异常：无。"""
    return str(row[field]) if row[field] is not None else None


def _require(conn: sqlite3.Connection, research_id: str, root_id: str, lease_id: str | None = None) -> sqlite3.Row:
    """核验稳定绑定和租约。参数：连接、研究、根、可选租约。返回：行。异常：缺失或过期。"""
    row: sqlite3.Row | None = conn.execute("SELECT * FROM research_notion_topics WHERE research_id=? AND root_id=?", (research_id, root_id)).fetchone()
    if row is None:
        raise KeyError("研究主题尚未固定")
    if lease_id is not None and row["lease_id"] != lease_id:
        raise ResearchConflictError("主题租约已过期，拒绝迟到结果")
    return row


class SQLiteResearchTopics:
    """先持久保存创建边界，未知结果只能读取调和。"""

    def __init__(self, store: ResearchStore) -> None:
        """注入数据库。参数：研究库。返回：无。异常：无。"""
        self._store = store

    def reserve(self, research_id: str, owner_id: str, root_id: str, title: str) -> None:
        """固定授权主题，重试不按新标题换绑。参数：研究、用户、根目录、标题。返回：无。异常：越权或空值。"""
        if not root_id.strip() or not title.strip():
            raise ValueError("研究主题需要根目录与标题")
        with self._store.connection(write=True) as conn:
            owned_research(conn, research_id, owner_id)
            conn.execute("INSERT OR IGNORE INTO research_notion_topics(research_id,root_id,title) VALUES (?,?,?)", (research_id, root_id, title))

    def claim(self, research_id: str, root_id: str) -> ResearchTopicClaim:
        """取得唯一业务租约。参数：研究、根目录。返回：租约。异常：存活执行者繁忙。"""
        with self._store.connection(write=True) as conn:
            row = _require(conn, research_id, root_id)
            if row["lease_id"] is not None and row["owner_pid"] is not None and is_owner_identity_alive(OwnerIdentity(
                    int(row["owner_pid"]), float(row["owner_start_time"]) if row["owner_start_time"] is not None else None, _text(row, "owner_boot_id"))):
                raise ResearchConflictError("研究主题正由另一发布执行处理")
            owner, lease = current_owner_identity(), uuid4().hex
            conn.execute("UPDATE research_notion_topics SET lease_id=?,owner_pid=?,owner_start_time=?,owner_boot_id=? WHERE research_id=? AND root_id=?",
                         (lease, owner.pid, owner.process_start_time, owner.boot_id, research_id, root_id))
            return ResearchTopicClaim(research_id, root_id, str(row["title"]), lease, bool(row["creation_started"]), _text(row, "page_id"), _text(row, "remote_task_id"))

    def mark_started(self, claim: ResearchTopicClaim) -> None:
        """在 POST 前固定不可盲重试边界。参数：租约。返回：无。异常：已经跨界或租约过期。"""
        with self._store.connection(write=True) as conn:
            row = _require(conn, claim.research_id, claim.root_id, claim.lease_id)
            if row["creation_started"]:
                raise ResearchConflictError("主题创建边界已存在")
            conn.execute("UPDATE research_notion_topics SET creation_started=1 WHERE research_id=? AND root_id=?", (claim.research_id, claim.root_id))

    def mark_rejected(self, claim: ResearchTopicClaim) -> None:
        """明确拒绝后允许重试。参数：租约。返回：无。异常：已有远端身份或租约过期。"""
        with self._store.connection(write=True) as conn:
            row = _require(conn, claim.research_id, claim.root_id, claim.lease_id)
            if row["page_id"] is not None or row["remote_task_id"] is not None:
                raise ResearchConflictError("已有远端主题身份，不能恢复创建资格")
            conn.execute("UPDATE research_notion_topics SET creation_started=0 WHERE research_id=? AND root_id=?", (claim.research_id, claim.root_id))

    def save_page(self, claim: ResearchTopicClaim, page_id: str) -> None:
        """保存唯一页身份。参数：租约、页面 ID。返回：无。异常：过期或身份变化。"""
        if not page_id.strip():
            raise ValueError("主题页面 ID 不能为空")
        with self._store.connection(write=True) as conn:
            row = _require(conn, claim.research_id, claim.root_id, claim.lease_id)
            if row["page_id"] is not None and row["page_id"] != page_id:
                raise ResearchConflictError("研究主题不能隐式换绑")
            conn.execute("UPDATE research_notion_topics SET page_id=?,remote_task_id=NULL WHERE research_id=? AND root_id=?", (page_id, claim.research_id, claim.root_id))

    def save_task(self, claim: ResearchTopicClaim, task_id: str) -> None:
        """保存不可重发的异步身份。参数：租约、任务 ID。返回：无。异常：过期或身份变化。"""
        with self._store.connection(write=True) as conn:
            row = _require(conn, claim.research_id, claim.root_id, claim.lease_id)
            if not task_id.strip() or (row["remote_task_id"] is not None and row["remote_task_id"] != task_id):
                raise ResearchConflictError("研究主题异步身份发生冲突")
            conn.execute("UPDATE research_notion_topics SET remote_task_id=? WHERE research_id=? AND root_id=?", (task_id, claim.research_id, claim.root_id))

    def release(self, claim: ResearchTopicClaim) -> None:
        """仅释放自身租约。参数：租约。返回：无。异常：数据库错误。"""
        with self._store.connection(write=True) as conn:
            conn.execute("UPDATE research_notion_topics SET lease_id=NULL,owner_pid=NULL,owner_start_time=NULL,owner_boot_id=NULL "
                         "WHERE research_id=? AND root_id=? AND lease_id=?", (claim.research_id, claim.root_id, claim.lease_id))
