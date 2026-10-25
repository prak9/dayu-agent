"""研究输入的幂等排队与串行派发仓储。"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
import re
from uuid import uuid4

from alpha.contracts.research import ResearchConflictError, ResearchState, ResearchStopFence, ResearchTurn, ResearchTurnState, ResearchTurnPreparation, SubmitResearchTurnRequest
from alpha.contracts.agent_execution_serialization import serialize_accepted_execution_spec
from alpha.contracts.execution_options import serialize_execution_options_snapshot
from alpha.contracts.research_financials import encode_financial_requirements
from alpha.research.storage.encoding import canonical_json, content_hash, encode_time, owned_research, turn_from_row, utc_now
from alpha.research.storage.store import ResearchStore

_METHOD_HASH = re.compile(r"[a-f0-9]{64}\Z")


@dataclass(frozen=True)
class _EncodedInput:
    """请求身份与首次落盘共用的规范值。"""

    input_hash: str
    requested_cutoff: str | None
    options_json: str | None


def _encode_input(request: SubmitResearchTurnRequest) -> _EncodedInput:
    """编码原始输入身份。参数：request 显式请求。返回：摘要、截止策略及选项。异常：空输入或时间非法。"""
    if not request.request_key.strip() or (not request.user_text.strip() and not request.attachment_refs):
        raise ValueError("输入键及研究内容不能为空")
    cutoff = encode_time(request.as_of)
    options = serialize_execution_options_snapshot(request.execution_options) if request.execution_options is not None else None
    fingerprint = content_hash(canonical_json({
        "user_text": request.user_text, "as_of": cutoff, "attachment_refs": list(request.attachment_refs),
        "execution_options": options,
        "financial_requirements": encode_financial_requirements(request.financial_requirements),
        "execution_mode": request.execution_mode.value, "publication_policy": request.publication_policy.value,
        "publication_target_id": request.publication_target_id,
    }))
    return _EncodedInput(fingerprint, cutoff, canonical_json(options) if options is not None else None)


def _require_turn(conn: sqlite3.Connection, turn_id: str) -> sqlite3.Row:
    """读取内部输入。参数：conn 连接、turn_id 输入。返回：记录行。异常：不存在时 KeyError。"""
    row: sqlite3.Row | None = conn.execute("SELECT * FROM research_turns WHERE turn_id=?", (turn_id,)).fetchone()
    if row is None:
        raise KeyError(f"研究输入不存在：{turn_id}")
    return row


def _stop_from_row(row: sqlite3.Row) -> ResearchStopFence:
    """投影停止边界。参数：数据行。返回：边界。异常：损坏数据导致 ValueError。"""
    return ResearchStopFence(str(row["stop_id"]), str(row["research_id"]), str(row["request_key"]),
                             int(row["through_sequence"]), int(row["completed_epoch"]) if row["completed_epoch"] is not None else None)


class SQLiteResearchTurns:
    """管理输入业务队列；执行成败始终向 Host 查询。"""

    def __init__(self, store: ResearchStore) -> None:
        """注入存储。参数：store 事务基础设施。返回：无。异常：无。"""
        self._store = store

    def enqueue(self, request: SubmitResearchTurnRequest, preparation: ResearchTurnPreparation) -> ResearchTurn:
        """幂等接受输入及规格。参数：request 显式输入、preparation 已准备规格。返回：固定截止时间与资源的输入。异常：越权、空输入或键冲突。"""
        encoded = _encode_input(request)
        with self._store.connection(write=True) as conn:
            research = owned_research(conn, request.research_id, request.owner_id)
            existing = conn.execute(
                "SELECT * FROM research_turns WHERE research_id=? AND request_key=?",
                (request.research_id, request.request_key),
            ).fetchone()
            # 重放先于状态校验；研究归档后仍能确认此前是否接受成功。
            if existing is not None:
                if str(existing["input_hash"]) != encoded.input_hash:
                    raise ResearchConflictError("相同输入键的内容发生变化")
                return turn_from_row(existing)
            if not _METHOD_HASH.fullmatch(preparation.method_hash) or not preparation.accepted_spec.model.model_name.strip():
                raise ValueError("方法哈希或已接受模型规格非法")
            if str(research["state"]) != ResearchState.ACTIVE.value:
                raise ResearchConflictError("已归档研究不接受新输入")
            cutoff = encoded.requested_cutoff or research["as_of"] or encode_time(utc_now())
            sequence = int(conn.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM research_turns WHERE research_id=?", (request.research_id,),
            ).fetchone()[0])
            turn_id = f"turn_{uuid4().hex}"
            conn.execute(
                "INSERT INTO research_turns VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (turn_id, request.research_id, request.request_key, sequence, request.user_text,
                 canonical_json(list(request.attachment_refs)), encoded.input_hash, cutoff, ResearchTurnState.QUEUED.value,
                 None, encode_time(utc_now()), None, preparation.method_hash,
                 canonical_json(serialize_accepted_execution_spec(preparation.accepted_spec)),
                 encoded.options_json, int(encoded.requested_cutoff is not None or research["as_of"] is not None), None,
                 canonical_json(encode_financial_requirements(request.financial_requirements)), request.execution_mode.value, request.publication_policy.value,
                 request.publication_target_id),
            )
            conn.execute("UPDATE research_catalog SET version=version+1,updated_at=? WHERE research_id=?",
                         (encode_time(utc_now()), request.research_id))
            return turn_from_row(_require_turn(conn, turn_id))

    def find(self, request: SubmitResearchTurnRequest) -> ResearchTurn | None:
        """在重新准备配置前查询受理。参数：原始请求。返回：原输入或空。异常：越权或同键内容变化。"""
        encoded = _encode_input(request)
        with self._store.connection() as conn:
            owned_research(conn, request.research_id, request.owner_id)
            row = conn.execute("SELECT * FROM research_turns WHERE research_id=? AND request_key=?",
                               (request.research_id, request.request_key)).fetchone()
            if row is None:
                return None
            if str(row["input_hash"]) != encoded.input_hash:
                raise ResearchConflictError("相同输入键的内容发生变化")
            return turn_from_row(row)

    def get(self, turn_id: str, owner_id: str) -> ResearchTurn:
        """读取输入。参数：turn_id、owner_id。返回：输入。异常：不存在或越权。"""
        with self._store.connection() as conn:
            row = _require_turn(conn, turn_id)
            owned_research(conn, str(row["research_id"]), owner_id)
            return turn_from_row(row)

    def claim_next(self, research_id: str, owner_id: str, *, host_epoch: int = 0) -> ResearchTurn | None:
        """领取最早输入。参数：研究、用户、Host 当前代际。返回：输入或空。异常：不存在或越权。"""
        with self._store.connection(write=True) as conn:
            owned_research(conn, research_id, owner_id)
            stopped = conn.execute(
                "SELECT 1 FROM research_stop_fences WHERE research_id=? AND (completed_epoch IS NULL OR completed_epoch>?)",
                (research_id, host_epoch),
            ).fetchone()
            if stopped is not None:
                return None
            busy = conn.execute(
                "SELECT 1 FROM research_turns WHERE research_id=? AND state IN ('dispatching','submitted')",
                (research_id,),
            ).fetchone()
            if busy is not None:
                return None
            row = conn.execute(
                "SELECT * FROM research_turns WHERE research_id=? AND state=? ORDER BY sequence LIMIT 1",
                (research_id, ResearchTurnState.QUEUED.value),
            ).fetchone()
            if row is None:
                return None
            turn_id = str(row["turn_id"])
            conn.execute("UPDATE research_turns SET state=?,host_epoch=? WHERE turn_id=?", (ResearchTurnState.DISPATCHING.value, host_epoch, turn_id))
            return turn_from_row(_require_turn(conn, turn_id))

    def active(self, research_id: str, owner_id: str) -> ResearchTurn | None:
        """读取待调和的派发输入。参数：研究、用户。返回：输入或空。异常：不存在或越权。"""
        with self._store.connection() as conn:
            owned_research(conn, research_id, owner_id)
            row = conn.execute(
                "SELECT * FROM research_turns WHERE research_id=? AND state IN ('dispatching','submitted')", (research_id,),
            ).fetchone()
            return turn_from_row(row) if row is not None else None

    def latest(self, research_id: str, owner_id: str) -> ResearchTurn | None:
        """读取最新业务输入。参数：研究、用户。返回：输入或空。异常：越权或不存在。"""
        with self._store.connection() as conn:
            owned_research(conn, research_id, owner_id)
            row = conn.execute("SELECT * FROM research_turns WHERE research_id=? ORDER BY sequence DESC LIMIT 1", (research_id,)).fetchone()
            return turn_from_row(row) if row is not None else None

    def queued_count(self, research_id: str, owner_id: str) -> int:
        """读取排队数。参数：研究、用户。返回：数量。异常：越权或不存在。"""
        with self._store.connection() as conn:
            owned_research(conn, research_id, owner_id)
            return int(conn.execute("SELECT COUNT(*) FROM research_turns WHERE research_id=? AND state=?",
                                    (research_id, ResearchTurnState.QUEUED.value)).fetchone()[0])

    def latest_executed(self, research_id: str, owner_id: str) -> ResearchTurn | None:
        """保留排队输入之前的执行身份供恢复 UI 使用。参数：研究、用户。返回：最近受理输入。异常：越权。"""
        with self._store.connection() as conn:
            owned_research(conn, research_id, owner_id)
            row = conn.execute("SELECT * FROM research_turns WHERE research_id=? AND run_id IS NOT NULL ORDER BY sequence DESC LIMIT 1", (research_id,)).fetchone()
            return turn_from_row(row) if row is not None else None

    def mark_submitted(self, turn_id: str, run_id: str) -> ResearchTurn:
        """记录 Host 持久受理结果。参数：输入、Run ID。返回：输入。异常：派发状态或 Run 冲突。"""
        if not run_id.strip():
            raise ValueError("Host Run ID 不能为空")
        with self._store.connection(write=True) as conn:
            row = _require_turn(conn, turn_id)
            if str(row["state"]) == ResearchTurnState.SUBMITTED.value and str(row["run_id"]) == run_id:
                return turn_from_row(row)
            if str(row["state"]) != ResearchTurnState.DISPATCHING.value:
                raise ResearchConflictError("只能确认待派发输入，且不可更换 Host Run")
            conn.execute("UPDATE research_turns SET state=?,run_id=? WHERE turn_id=?",
                         (ResearchTurnState.SUBMITTED.value, run_id, turn_id))
            return turn_from_row(_require_turn(conn, turn_id))

    def request_resume(self, turn_id: str, owner_id: str, request_key: str, *, host_epoch: int) -> ResearchTurn:
        """预留原输入的显式恢复派发。参数：输入、用户、稳定键、代际。返回：原输入。异常：越权、繁忙或未收敛。"""
        if not request_key.strip():
            raise ValueError("恢复请求键不能为空")
        with self._store.connection(write=True) as conn:
            row = _require_turn(conn, turn_id)
            owned_research(conn, str(row["research_id"]), owner_id)
            if row["resume_request_key"] == request_key:
                return turn_from_row(row)
            if str(row["state"]) != ResearchTurnState.SETTLED.value or row["run_id"] is None:
                raise ResearchConflictError("显式恢复前须观察原 Run 终态")
            busy = conn.execute("SELECT 1 FROM research_turns WHERE research_id=? AND state IN ('dispatching','submitted')",
                                (row["research_id"],)).fetchone()
            if busy is not None:
                raise ResearchConflictError("研究已有待派发或活跃输入")
            conn.execute("UPDATE research_turns SET state=?,host_epoch=?,resume_request_key=? WHERE turn_id=?",
                         (ResearchTurnState.DISPATCHING.value, host_epoch, request_key, turn_id))
            conn.execute("UPDATE research_catalog SET version=version+1,updated_at=? WHERE research_id=?",
                         (encode_time(utc_now()), row["research_id"]))
            return turn_from_row(_require_turn(conn, turn_id))

    def settle(self, turn_id: str, run_id: str) -> ResearchTurn:
        """确认已观察到 Host 终态。参数：输入、Run ID。返回：输入。异常：状态或 Run 不一致。"""
        with self._store.connection(write=True) as conn:
            row = _require_turn(conn, turn_id)
            if str(row["run_id"]) != run_id or str(row["state"]) not in (
                ResearchTurnState.SUBMITTED.value, ResearchTurnState.SETTLED.value,
            ):
                raise ResearchConflictError("输入尚未受理或 Host Run 不匹配")
            conn.execute("UPDATE research_turns SET state=? WHERE turn_id=?", (ResearchTurnState.SETTLED.value, turn_id))
            return turn_from_row(_require_turn(conn, turn_id))

    def cancel_queued(self, research_id: str, owner_id: str, *, through_sequence: int | None = None) -> int:
        """取消停止边界内的排队输入。参数：研究、用户、序号上界。返回：取消数。异常：越权或不存在。"""
        with self._store.connection(write=True) as conn:
            owned_research(conn, research_id, owner_id)
            return conn.execute(
                "UPDATE research_turns SET state=? WHERE research_id=? AND state=? AND (? IS NULL OR sequence<=?)",
                (ResearchTurnState.CANCELLED.value, research_id, ResearchTurnState.QUEUED.value,
                 through_sequence, through_sequence),
            ).rowcount

    def begin_stop(self, research_id: str, owner_id: str, request_key: str, *, expected_version: int | None = None) -> ResearchStopFence:
        """持久划定停止范围。参数：研究、用户、稳定停止键。返回：边界。异常：越权或空键。"""
        if not request_key.strip():
            raise ValueError("停止请求键不能为空")
        with self._store.connection(write=True) as conn:
            research = owned_research(conn, research_id, owner_id)
            existing = conn.execute(
                "SELECT * FROM research_stop_fences WHERE research_id=? AND request_key=?", (research_id, request_key),
            ).fetchone()
            if existing is None:
                existing = conn.execute(
                    "SELECT * FROM research_stop_fences WHERE research_id=? AND completed_epoch IS NULL", (research_id,),
                ).fetchone()
            if existing is not None:
                return _stop_from_row(existing)
            if expected_version is not None and int(research["version"]) != expected_version:
                raise ResearchConflictError("研究已更新，请刷新状态卡后停止")
            sequence = int(conn.execute("SELECT COALESCE(MAX(sequence),0) FROM research_turns WHERE research_id=?",
                                        (research_id,)).fetchone()[0])
            stop_id = f"stop_{uuid4().hex}"
            conn.execute("INSERT INTO research_stop_fences VALUES (?,?,?,?,NULL)", (stop_id, research_id, request_key, sequence))
            conn.execute("UPDATE research_turns SET state=? WHERE research_id=? AND sequence<=? AND state=?",
                         (ResearchTurnState.CANCELLED.value, research_id, sequence, ResearchTurnState.QUEUED.value))
            return ResearchStopFence(stop_id, research_id, request_key, sequence, None)

    def complete_stop(self, stop_id: str, owner_id: str, *, host_epoch: int) -> ResearchStopFence:
        """记录 Host fencing 完成。参数：停止 ID、用户、Host 代际。返回：边界。异常：不存在、越权或冲突。"""
        with self._store.connection(write=True) as conn:
            row = conn.execute("SELECT * FROM research_stop_fences WHERE stop_id=?", (stop_id,)).fetchone()
            if row is None:
                raise KeyError(f"停止请求不存在：{stop_id}")
            owned_research(conn, str(row["research_id"]), owner_id)
            if row["completed_epoch"] is not None and int(row["completed_epoch"]) != host_epoch:
                raise ResearchConflictError("同一停止请求的 Host 代际发生变化")
            conn.execute("UPDATE research_stop_fences SET completed_epoch=? WHERE stop_id=?", (host_epoch, stop_id))
            # 未登记 Run 的旧派发已被 Host epoch 拒绝；有 Run 的输入仍等 Host 终态。
            conn.execute("UPDATE research_turns SET state=? WHERE research_id=? AND sequence<=? AND state=?",
                         (ResearchTurnState.CANCELLED.value, row["research_id"], row["through_sequence"], ResearchTurnState.DISPATCHING.value))
            return _stop_from_row(conn.execute("SELECT * FROM research_stop_fences WHERE stop_id=?", (stop_id,)).fetchone())
