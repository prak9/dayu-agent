"""从持久受理解析研究来源，供各类分析仓储共同核验。"""

import sqlite3
from datetime import datetime

from alpha.contracts.research_working import ResearchWorkScope


def scope_for_run(conn: sqlite3.Connection, run_id: str) -> ResearchWorkScope:
    """读取可信作用域。参数：连接、Run。返回：作用域。异常：未关联。"""
    row = conn.execute("SELECT t.*,c.owner_id FROM research_turns t JOIN research_catalog c ON c.research_id=t.research_id WHERE t.run_id=?", (run_id,)).fetchone()
    if row is None:
        raise KeyError("Run 尚未关联研究输入")
    return ResearchWorkScope(str(row["research_id"]), str(row["turn_id"]), run_id,
                             datetime.fromisoformat(str(row["as_of"])), str(row["method_hash"]), bool(row["historical"]), str(row["owner_id"]))
