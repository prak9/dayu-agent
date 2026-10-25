"""研究持久化的故障注入、并发及边界测试。"""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from alpha.contracts.research import (
    CommitResearchRevisionRequest, CreateResearchRequest, EvidenceClassification, ResearchConflictError,
    ResearchEvidence, ResearchRecord, ResearchState, ResearchTurn, ResearchTurnState, SubmitResearchTurnRequest,
)
from alpha.research.storage.artifacts import FsResearchArtifactStore
from alpha.research.storage.catalog import SQLiteResearchCatalog
from alpha.research.storage.encoding import decode_strings
from alpha.research.storage.revisions import SQLiteResearchRevisions
from alpha.research.storage.store import ResearchStore
from alpha.research.storage.turns import SQLiteResearchTurns
from tests.research.factories import TEST_METHOD_HASH, research_turn_preparation


def _ready_revision(tmp_path: Path) -> tuple[ResearchStore, FsResearchArtifactStore, CommitResearchRevisionRequest]:
    """准备已受理输入。参数：tmp_path 目录。返回：库、产物仓储及提交请求。异常：存储错误。"""
    store = ResearchStore(tmp_path / "research.db")
    research = SQLiteResearchCatalog(store).create(CreateResearchRequest("owner", "create", "质量"))
    turns = SQLiteResearchTurns(store)
    turn = turns.enqueue(SubmitResearchTurnRequest(research.research_id, "owner", "turn", "开始"), research_turn_preparation())
    turns.claim_next(research.research_id, "owner")
    turns.mark_submitted(turn.turn_id, "run")
    return store, FsResearchArtifactStore(tmp_path / "artifacts"), CommitResearchRevisionRequest(
        research.research_id, "owner", turn.turn_id, "run", "# 正文", TEST_METHOD_HASH,
    )


def test_snapshot_reused_after_db_rollback(tmp_path: Path, mocker: MockerFixture) -> None:
    """目录已提交而 SQL 失败时复用孤立快照。参数：目录、mock。返回：无。异常：断言失败。"""
    store, artifacts, request = _ready_revision(tmp_path)
    revisions = SQLiteResearchRevisions(store, artifacts)
    mocker.patch("alpha.research.storage.revisions._revision_from_row", side_effect=RuntimeError("模拟 DB 提交前崩溃"))
    with pytest.raises(RuntimeError, match="模拟"):
        revisions.commit(request)
    assert revisions.list_revisions(request.research_id, "owner") == []
    directories = list((tmp_path / "artifacts" / request.research_id / "revisions").iterdir())
    assert len(directories) == 1
    mocker.stopall()
    recovered = revisions.commit(request)
    assert recovered.revision_id == directories[0].name
    assert revisions.read_report(recovered.revision_id, "owner") == request.report_markdown
    assert len(list(directories[0].parent.iterdir())) == 1


def test_complete_revision_content_is_verified_and_owner_scoped(tmp_path: Path) -> None:
    """发布读取同时包含证据和契约，不能绕过所有权与文件完整性。参数：目录。返回：无。异常：断言失败。"""
    store, artifacts, request = _ready_revision(tmp_path)
    request = replace(request, data_contract_json='{"metrics":[]}')
    revisions = SQLiteResearchRevisions(store, artifacts)
    revision = revisions.commit(request)
    content = revisions.read_content(revision.revision_id, "owner")
    assert content.report_markdown == request.report_markdown and content.evidence == ()
    assert content.data_contract_json == request.data_contract_json
    with pytest.raises(PermissionError):
        revisions.read_content(revision.revision_id, "foreign")
    contract = tmp_path / "artifacts" / request.research_id / "revisions" / revision.revision_id / "data-contract.json"
    contract.write_text("null")
    with pytest.raises(ResearchConflictError, match="校验"):
        revisions.read_content(revision.revision_id, "owner")


def test_incomplete_directory_is_not_a_version(tmp_path: Path) -> None:
    """残留临时目录不被视为版本。参数：目录。返回：无。异常：断言失败。"""
    store, artifacts, request = _ready_revision(tmp_path)
    pending = tmp_path / "artifacts" / request.research_id / "revisions" / ".pending-interrupted"
    pending.mkdir(parents=True)
    (pending / "report.md").write_text("未写完")
    revisions = SQLiteResearchRevisions(store, artifacts)
    assert revisions.list_revisions(request.research_id, "owner") == []
    revision = revisions.commit(request)
    assert revisions.read_report(revision.revision_id, "owner") == "# 正文"


def test_revision_parent_and_source_correlation(tmp_path: Path) -> None:
    """新版本连接父版本并拒绝错误 Run。参数：目录。返回：无。异常：断言失败。"""
    store, artifacts, request = _ready_revision(tmp_path)
    revisions = SQLiteResearchRevisions(store, artifacts)
    with pytest.raises(ResearchConflictError):
        revisions.commit(replace(request, source_run_id="wrong"))
    with pytest.raises(ResearchConflictError, match="方法"):
        revisions.commit(replace(request, skill_hash="1" * 64))
    first = revisions.commit(request)
    turns = SQLiteResearchTurns(store)
    turns.settle(request.source_turn_id, "run")
    second_turn = turns.enqueue(SubmitResearchTurnRequest(request.research_id, "owner", "second", "增量"), research_turn_preparation())
    turns.claim_next(request.research_id, "owner")
    turns.mark_submitted(second_turn.turn_id, "run2")
    second = revisions.commit(replace(request, source_turn_id=second_turn.turn_id, source_run_id="run2", report_markdown="v2"))
    assert second.number == 2 and second.parent_revision_id == first.revision_id
    assert revisions.read_report(first.revision_id, "owner") == "# 正文"
    assert revisions.list_revisions(request.research_id, "owner") == [first, second]
    with pytest.raises(PermissionError):
        revisions.get(second.revision_id, "attacker")
    with pytest.raises(KeyError):
        revisions.get("missing", "owner")
    with pytest.raises(ValueError):
        revisions.commit(replace(request, report_markdown=" "))


def test_evidence_cutoff_missing_time_and_validation(tmp_path: Path) -> None:
    """证据必须记录时间依据且不得穿越截止日。参数：目录。返回：无。异常：断言失败。"""
    store, artifacts, request = _ready_revision(tmp_path)
    revisions = SQLiteResearchRevisions(store, artifacts)
    evidence = ResearchEvidence("e1", "https://example.com/filing", "filing", "收入", EvidenceClassification.REPORTED_FACT,
                                datetime.now(timezone.utc))
    with pytest.raises(ValueError, match="缺失原因"):
        revisions.commit(replace(request, evidence=(evidence,)))
    with pytest.raises(ValueError, match="晚于"):
        revisions.commit(replace(request, evidence=(replace(evidence, published_at=datetime(2099, 1, 1, tzinfo=timezone.utc)),)))
    with pytest.raises(ValueError, match="不能为空"):
        revisions.commit(replace(request, evidence=(replace(evidence, source_ref=""),)))
    valid = replace(evidence, time_missing_reason="来源未提供发布日期")
    with pytest.raises(ValueError, match="重复"):
        revisions.commit(replace(request, evidence=(valid, valid)))
    revision = revisions.commit(replace(request, evidence=(valid,), data_contract_json='{"currency":"USD"}'))
    evidence_file = tmp_path / "artifacts" / request.research_id / "revisions" / revision.revision_id / "evidence.json"
    assert json.loads(evidence_file.read_text())[0]["time_missing_reason"] == "来源未提供发布日期"
    evidence_file.unlink()
    with pytest.raises(ResearchConflictError, match="缺失"):
        revisions.read_report(revision.revision_id, "owner")


def test_turn_transitions_and_stop_fence(tmp_path: Path) -> None:
    """状态转换严格且停止只取消边界前输入。参数：目录。返回：无。异常：断言失败。"""
    store, _, request = _ready_revision(tmp_path)
    turns = SQLiteResearchTurns(store)
    active = turns.active(request.research_id, "owner")
    assert active is not None and active.run_id == "run"
    assert turns.mark_submitted(active.turn_id, "run") == active
    with pytest.raises(ResearchConflictError):
        turns.mark_submitted(active.turn_id, "another-run")
    with pytest.raises(ResearchConflictError):
        turns.settle(active.turn_id, "another-run")
    with pytest.raises(ValueError):
        turns.mark_submitted(active.turn_id, " ")
    second = turns.enqueue(SubmitResearchTurnRequest(request.research_id, "owner", "second", "停止前"), research_turn_preparation())
    third = turns.enqueue(SubmitResearchTurnRequest(request.research_id, "owner", "third", "停止后"), research_turn_preparation())
    assert turns.cancel_queued(request.research_id, "owner", through_sequence=second.sequence) == 1
    assert turns.get(second.turn_id, "owner").state == ResearchTurnState.CANCELLED
    turns.settle(active.turn_id, "run")
    assert turns.settle(active.turn_id, "run").state == ResearchTurnState.SETTLED
    assert turns.active(request.research_id, "owner") is None
    assert turns.claim_next(request.research_id, "owner") == replace(third, state=ResearchTurnState.DISPATCHING, host_epoch=0)


def test_durable_stop_preserves_later_input_and_fences_stale_dispatch(tmp_path: Path) -> None:
    """停止过程可恢复且后续输入不被旧派发取消。参数：目录。返回：无。异常：断言失败。"""
    store, _, request = _ready_revision(tmp_path)
    turns = SQLiteResearchTurns(store)
    old_queued = turns.enqueue(SubmitResearchTurnRequest(request.research_id, "owner", "old", "旧排队"), research_turn_preparation())
    stop = turns.begin_stop(request.research_id, "owner", "stop-callback")
    assert stop.through_sequence == old_queued.sequence
    later = turns.enqueue(SubmitResearchTurnRequest(request.research_id, "owner", "later", "停止之后"), research_turn_preparation())
    turns.settle(request.source_turn_id, "run")
    assert turns.claim_next(request.research_id, "owner", host_epoch=0) is None
    restarted = SQLiteResearchTurns(ResearchStore(tmp_path / "research.db"))
    assert restarted.begin_stop(request.research_id, "owner", "stop-callback") == stop
    completed = restarted.complete_stop(stop.stop_id, "owner", host_epoch=1)
    assert completed.completed_epoch == 1
    assert restarted.claim_next(request.research_id, "owner", host_epoch=0) is None
    next_turn = restarted.claim_next(request.research_id, "owner", host_epoch=1)
    assert next_turn is not None and next_turn.turn_id == later.turn_id and next_turn.host_epoch == 1
    assert turns.get(old_queued.turn_id, "owner").state == ResearchTurnState.CANCELLED
    assert restarted.begin_stop(request.research_id, "owner", "stop-callback") == completed
    assert restarted.complete_stop(stop.stop_id, "owner", host_epoch=1) == completed
    with pytest.raises(PermissionError):
        turns.get(later.turn_id, "intruder")
    with pytest.raises(KeyError):
        turns.get("absent", "owner")


def test_empty_queue_and_catalog_state_filters(tmp_path: Path) -> None:
    """空队列和重复归档不制造变化。参数：目录。返回：无。异常：断言失败。"""
    store = ResearchStore(tmp_path / "research.db")
    catalog = SQLiteResearchCatalog(store)
    research = catalog.create(CreateResearchRequest("owner", "create", "问题"))
    turns = SQLiteResearchTurns(store)
    assert turns.claim_next(research.research_id, "owner") is None
    assert turns.active(research.research_id, "owner") is None
    archived = catalog.archive(research.research_id, "owner")
    assert catalog.archive(research.research_id, "owner") == archived
    assert catalog.list_research("owner", state=ResearchState.ARCHIVED) == [archived]
    assert catalog.list_research("owner", state=ResearchState.ACTIVE) == []
    with pytest.raises(KeyError):
        catalog.get("absent", "owner")
    with pytest.raises(ValueError):
        catalog.create(CreateResearchRequest("", "key", "问题"))
    with pytest.raises(ValueError):
        turns.enqueue(SubmitResearchTurnRequest(research.research_id, "owner", "empty", " "), research_turn_preparation())


def test_schema_mismatch_is_not_silently_adapted(tmp_path: Path) -> None:
    """未知 schema 拒绝运行。参数：目录。返回：无。异常：断言失败。"""
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE obsolete (id TEXT)")
    with pytest.raises(RuntimeError, match="alpha init"):
        ResearchStore(path)
    for bad in ('{}', '[42]'):
        with pytest.raises(ValueError):
            decode_strings(bad)


def test_concurrent_initialization_and_admission(tmp_path: Path) -> None:
    """真实独立连接并发只能创建和领取一次。参数：目录。返回：无。异常：断言失败。"""
    path = tmp_path / "research.db"

    with ThreadPoolExecutor(max_workers=4) as executor:
        stores = list(executor.map(ResearchStore, [path] * 4))
    catalogs = [SQLiteResearchCatalog(store) for store in stores]
    request = CreateResearchRequest("owner", "shared", "并发研究")
    with ThreadPoolExecutor(max_workers=4) as executor:
        records = list(executor.map(_create, [(catalog, request) for catalog in catalogs]))
    assert len({record.research_id for record in records}) == 1
    queues = [SQLiteResearchTurns(store) for store in stores]
    turn_request = SubmitResearchTurnRequest(records[0].research_id, "owner", "shared", "并发输入")
    with ThreadPoolExecutor(max_workers=4) as executor:
        admitted = list(executor.map(_enqueue, [(queue, turn_request) for queue in queues]))
    assert len({turn.turn_id for turn in admitted}) == 1
    with ThreadPoolExecutor(max_workers=4) as executor:
        claims = list(executor.map(_claim, [(queue, records[0].research_id) for queue in queues]))
    assert sum(turn is not None for turn in claims) == 1


def _create(pair: tuple[SQLiteResearchCatalog, CreateResearchRequest]) -> ResearchRecord:
    """并发创建适配。参数：仓储及请求。返回：研究。异常：仓储异常。"""
    return pair[0].create(pair[1])


def _enqueue(pair: tuple[SQLiteResearchTurns, SubmitResearchTurnRequest]) -> ResearchTurn:
    """并发排队适配。参数：仓储及请求。返回：输入。异常：仓储异常。"""
    return pair[0].enqueue(pair[1], research_turn_preparation())


def _claim(pair: tuple[SQLiteResearchTurns, str]) -> ResearchTurn | None:
    """并发领取适配。参数：仓储及研究。返回：输入或空。异常：仓储异常。"""
    return pair[0].claim_next(pair[1], "owner")
