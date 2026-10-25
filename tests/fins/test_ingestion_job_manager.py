"""ingestion.job_manager 测试。"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from typing import Any, AsyncIterator, Optional

import pytest
from pytest_mock import MockerFixture

from alpha.fins.ingestion.job_manager import (
    IngestionJobManager,
    get_or_create_ingestion_job_manager,
)
from alpha.fins.ingestion.process_events import ProcessEvent, ProcessEventType
from alpha.fins.ingestion.service import FinsIngestionService
from alpha.fins.pipelines.download_events import DownloadEvent, DownloadEventType


class _BlockingDownloadBackend:
    """用于验证 active job 复用的下载后端桩。"""

    def __init__(self, *, started_event: threading.Event, release_event: threading.Event) -> None:
        """初始化阻塞式后端。"""

        self._started_event = started_event
        self._release_event = release_event

    async def download_stream(
        self,
        ticker: str,
        form_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        overwrite: bool = False,
        rebuild: bool = False,
        ticker_aliases: Optional[list[str]] = None,
        cancel_checker: Optional[Any] = None,
    ) -> AsyncIterator[DownloadEvent]:
        """在 release 前保持运行中的下载流。"""

        del form_type, start_date, end_date, overwrite, rebuild, ticker_aliases, cancel_checker
        yield DownloadEvent(event_type=DownloadEventType.PIPELINE_STARTED, ticker=ticker, payload={})
        yield DownloadEvent(
            event_type=DownloadEventType.FILING_STARTED,
            ticker=ticker,
            document_id="fil_1",
            payload={"form_type": "10-K", "total_filings": 1},
        )
        self._started_event.set()
        while not self._release_event.is_set():
            await asyncio.sleep(0.01)
        yield DownloadEvent(
            event_type=DownloadEventType.FILING_COMPLETED,
            ticker=ticker,
            document_id="fil_1",
            payload={"status": "downloaded", "downloaded_files": 1},
        )
        yield DownloadEvent(
            event_type=DownloadEventType.PIPELINE_COMPLETED,
            ticker=ticker,
            payload={
                "result": {
                    "action": "download",
                    "ticker": ticker,
                    "status": "ok",
                    "summary": {"total": 1, "downloaded": 1, "skipped": 0, "failed": 0},
                    "filings": [{"document_id": "fil_1", "status": "downloaded", "downloaded_files": 1}],
                }
            },
        )

    async def process_stream(
        self,
        ticker: str,
        overwrite: bool = False,
        ci: bool = False,
        document_ids: Optional[list[str]] = None,
        cancel_checker: Optional[Any] = None,
    ) -> AsyncIterator[ProcessEvent]:
        """该后端不实现预处理。"""

        del ticker, overwrite, ci, document_ids, cancel_checker
        if False:
            yield ProcessEvent(event_type=ProcessEventType.PIPELINE_STARTED, ticker="AAPL", payload={})


class _ResumableProcessBackend:
    """用于验证取消与续做语义的预处理后端桩。"""

    def __init__(self, *, shared_state: dict[str, Any]) -> None:
        """初始化共享状态后端。"""

        self._shared_state = shared_state

    async def download_stream(
        self,
        ticker: str,
        form_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        overwrite: bool = False,
        rebuild: bool = False,
        ticker_aliases: Optional[list[str]] = None,
        cancel_checker: Optional[Any] = None,
    ) -> AsyncIterator[DownloadEvent]:
        """该后端不实现下载。"""

        del ticker, form_type, start_date, end_date, overwrite, rebuild, ticker_aliases, cancel_checker
        if False:
            yield DownloadEvent(event_type=DownloadEventType.PIPELINE_STARTED, ticker="AAPL", payload={})

    async def process_stream(
        self,
        ticker: str,
        overwrite: bool = False,
        ci: bool = False,
        document_ids: Optional[list[str]] = None,
        cancel_checker: Optional[Any] = None,
    ) -> AsyncIterator[ProcessEvent]:
        """基于共享已完成集合模拟可恢复预处理。"""

        del overwrite, ci
        requested_document_ids = self._shared_state.setdefault("requested_document_ids", [])
        requested_document_ids.append(list(document_ids) if document_ids is not None else None)
        completed_documents: set[str] = self._shared_state.setdefault("completed_documents", set())
        results: list[dict[str, Any]] = []
        documents = list(document_ids) if document_ids is not None else ["fil_1", "fil_2"]
        yield ProcessEvent(
            event_type=ProcessEventType.PIPELINE_STARTED,
            ticker=ticker,
            payload={"total_documents": len(documents), "filing_total": len(documents), "material_total": 0},
        )
        for document_id in documents:
            if cancel_checker is not None and cancel_checker():
                break
            if document_id in completed_documents:
                item = {
                    "document_id": document_id,
                    "status": "skipped",
                    "reason": "version_matched",
                }
                results.append(item)
                yield ProcessEvent(
                    event_type=ProcessEventType.DOCUMENT_SKIPPED,
                    ticker=ticker,
                    document_id=document_id,
                    payload={"source_kind": "filing", "reason": "version_matched", "result_summary": item},
                )
                continue
            yield ProcessEvent(
                event_type=ProcessEventType.DOCUMENT_STARTED,
                ticker=ticker,
                document_id=document_id,
                payload={"source_kind": "filing"},
            )
            await asyncio.sleep(0.01)
            completed_documents.add(document_id)
            item = {"document_id": document_id, "status": "processed"}
            results.append(item)
            yield ProcessEvent(
                event_type=ProcessEventType.DOCUMENT_COMPLETED,
                ticker=ticker,
                document_id=document_id,
                payload={"source_kind": "filing", "result_summary": item},
            )
            if document_id == "fil_1":
                self._shared_state["first_completed_event"].set()
                await asyncio.sleep(0.05)
        filing_summary = {
            "total": len(results),
            "processed": sum(1 for item in results if item.get("status") == "processed"),
            "skipped": sum(1 for item in results if item.get("status") == "skipped"),
            "failed": 0,
        }
        yield ProcessEvent(
            event_type=ProcessEventType.PIPELINE_COMPLETED,
            ticker=ticker,
            payload={
                "result": {
                    "action": "process",
                    "ticker": ticker,
                    "status": "cancelled" if cancel_checker is not None and cancel_checker() else "ok",
                    "filing_summary": filing_summary,
                    "material_summary": {"total": 0, "processed": 0, "skipped": 0, "failed": 0},
                    "filings": results,
                    "materials": [],
                }
            },
        )


class _DownloadIssueBackend:
    """用于验证 download recent_issues 聚合的后端桩。"""

    async def download_stream(
        self,
        ticker: str,
        form_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        overwrite: bool = False,
        rebuild: bool = False,
        ticker_aliases: Optional[list[str]] = None,
        cancel_checker: Optional[Any] = None,
    ) -> AsyncIterator[DownloadEvent]:
        """产出带 skip/fail reason 的下载事件流。"""

        del form_type, start_date, end_date, overwrite, rebuild, ticker_aliases, cancel_checker
        yield DownloadEvent(event_type=DownloadEventType.PIPELINE_STARTED, ticker=ticker, payload={})
        yield DownloadEvent(
            event_type=DownloadEventType.FILING_STARTED,
            ticker=ticker,
            document_id="fil_1",
            payload={"form_type": "10-K", "total_filings": 2},
        )
        yield DownloadEvent(
            event_type=DownloadEventType.FILING_COMPLETED,
            ticker=ticker,
            document_id="fil_1",
            payload={
                "filing_result": {
                    "document_id": "fil_1",
                    "status": "skipped",
                    "skip_reason": "not_modified",
                    "reason_code": "not_modified",
                    "reason_message": "所有文件均未修改，跳过重新下载",
                }
            },
        )
        yield DownloadEvent(
            event_type=DownloadEventType.FILING_STARTED,
            ticker=ticker,
            document_id="fil_2",
            payload={"form_type": "10-Q", "total_filings": 2},
        )
        yield DownloadEvent(
            event_type=DownloadEventType.FILING_FAILED,
            ticker=ticker,
            document_id="fil_2",
            payload={
                "filing_result": {
                    "document_id": "fil_2",
                    "status": "failed",
                    "reason_code": "file_download_failed",
                    "failed_files": [{"error": "network down"}],
                }
            },
        )
        yield DownloadEvent(
            event_type=DownloadEventType.PIPELINE_COMPLETED,
            ticker=ticker,
            payload={
                "result": {
                    "action": "download",
                    "ticker": ticker,
                    "status": "ok",
                    "summary": {"total": 2, "downloaded": 0, "skipped": 1, "failed": 1},
                    "filings": [
                        {
                            "document_id": "fil_1",
                            "status": "skipped",
                            "skip_reason": "not_modified",
                            "reason_code": "not_modified",
                            "reason_message": "所有文件均未修改，跳过重新下载",
                        },
                        {
                            "document_id": "fil_2",
                            "status": "failed",
                            "reason_code": "file_download_failed",
                            "reason_message": "network down",
                            "failed_files": [{"error": "network down"}],
                        },
                    ],
                }
            },
        )

    async def process_stream(
        self,
        ticker: str,
        overwrite: bool = False,
        ci: bool = False,
        document_ids: Optional[list[str]] = None,
        cancel_checker: Optional[Any] = None,
    ) -> AsyncIterator[ProcessEvent]:
        """该后端不实现预处理。"""

        del ticker, overwrite, ci, document_ids, cancel_checker
        if False:
            yield ProcessEvent(event_type=ProcessEventType.PIPELINE_STARTED, ticker="AAPL", payload={})


@pytest.mark.unit
def test_global_manager_reuses_active_download_job_across_callers() -> None:
    """验证全局 manager 可复用 active job，且生命周期独立于调用方引用。"""

    started_event = threading.Event()
    release_event = threading.Event()

    def service_factory(ticker: str) -> FinsIngestionService:
        """构建测试用长事务服务。"""

        del ticker
        return FinsIngestionService(
            backend=_BlockingDownloadBackend(
                started_event=started_event,
                release_event=release_event,
            )
        )

    manager_key = f"test-manager-{uuid.uuid4().hex}"
    manager = get_or_create_ingestion_job_manager(
        manager_key=manager_key,
        service_factory=service_factory,
    )
    request_outcome, snapshot = manager.start_download_job(
        ticker="AAPL",
        form_types=["10-K"],
        filed_date_from=None,
        filed_date_to=None,
        overwrite=False,
    )
    assert request_outcome == "started"
    assert started_event.wait(timeout=1.0) is True

    manager_again = get_or_create_ingestion_job_manager(
        manager_key=manager_key,
        service_factory=lambda ticker: (_ for _ in ()).throw(AssertionError("不应重新构建 manager")),
    )
    reused_outcome, reused_snapshot = manager_again.start_download_job(
        ticker="AAPL",
        form_types=["10-K"],
        filed_date_from=None,
        filed_date_to=None,
        overwrite=False,
    )
    assert reused_outcome == "reused_active_job"
    assert snapshot["job"]["job_id"] == reused_snapshot["job"]["job_id"]

    release_event.set()
    final_snapshot = _wait_for_job_snapshot(
        manager,
        snapshot["job"]["job_id"],
        lambda item: item["job"]["status"] == "succeeded",
    )
    assert final_snapshot["result_summary"]["filings_completed"] == 1
    assert final_snapshot["progress"]["percent"] == 100


@pytest.mark.unit
def test_process_job_cancel_and_restart_resume_completed_work() -> None:
    """验证取消后的重启会复用已完成工作，而不是复用旧 job_id。"""

    shared_state = {
        "completed_documents": set(),
        "first_completed_event": threading.Event(),
    }

    def service_factory(ticker: str) -> FinsIngestionService:
        """构建共享状态后端服务。"""

        del ticker
        return FinsIngestionService(backend=_ResumableProcessBackend(shared_state=shared_state))

    manager = IngestionJobManager(
        service_factory=service_factory,
        manager_key=f"resume-{uuid.uuid4().hex}",
    )
    _, first_snapshot = manager.start_process_job(ticker="AAPL", overwrite=False)
    first_job_id = first_snapshot["job"]["job_id"]
    assert shared_state["first_completed_event"].wait(timeout=1.0) is True

    cancellation_outcome, cancelling_snapshot = manager.cancel_job(first_job_id)
    assert cancellation_outcome == "cancellation_requested"
    assert cancelling_snapshot is not None

    cancelled_snapshot = _wait_for_job_snapshot(
        manager,
        first_job_id,
        lambda item: item["job"]["status"] == "cancelled",
    )
    assert cancelled_snapshot["progress"]["completed"] == 1
    assert cancelled_snapshot["result_summary"]["filings_processed"] == 1

    second_outcome, second_snapshot = manager.start_process_job(ticker="AAPL", overwrite=False)
    assert second_outcome == "started"
    assert second_snapshot["job"]["job_id"] != first_job_id

    succeeded_snapshot = _wait_for_job_snapshot(
        manager,
        second_snapshot["job"]["job_id"],
        lambda item: item["job"]["status"] == "succeeded",
    )
    assert succeeded_snapshot["result_summary"]["filings_processed"] == 1
    assert succeeded_snapshot["result_summary"]["filings_skipped"] == 1
    assert succeeded_snapshot["progress"]["completed"] == 2


@pytest.mark.unit
def test_process_job_forwards_document_ids_to_backend() -> None:
    """验证 process job 会把规范化后的 document_ids 透传到 ingestion backend。"""

    shared_state = {
        "completed_documents": set(),
        "first_completed_event": threading.Event(),
        "requested_document_ids": [],
    }

    def service_factory(ticker: str) -> FinsIngestionService:
        """构建带共享状态的预处理服务。"""

        del ticker
        return FinsIngestionService(backend=_ResumableProcessBackend(shared_state=shared_state))

    manager = IngestionJobManager(
        service_factory=service_factory,
        manager_key=f"document-ids-{uuid.uuid4().hex}",
    )

    _, snapshot = manager.start_process_job(
        ticker="AAPL",
        overwrite=False,
        document_ids=["fil_2"],
    )
    final_snapshot = _wait_for_job_snapshot(
        manager,
        snapshot["job"]["job_id"],
        lambda item: item["job"]["status"] == "succeeded",
    )

    assert shared_state["requested_document_ids"] == [["fil_2"]]
    assert final_snapshot["progress"]["completed"] == 1
    assert final_snapshot["result_summary"]["filings_processed"] == 1


@pytest.mark.unit
def test_process_job_reuses_active_job_for_equivalent_document_ids() -> None:
    """验证等价 document_ids 请求会复用同一个 active process job。"""

    shared_state = {
        "completed_documents": set(),
        "first_completed_event": threading.Event(),
        "requested_document_ids": [],
    }

    def service_factory(ticker: str) -> FinsIngestionService:
        """构建带共享状态的预处理服务。"""

        del ticker
        return FinsIngestionService(backend=_ResumableProcessBackend(shared_state=shared_state))

    manager = IngestionJobManager(
        service_factory=service_factory,
        manager_key=f"document-ids-reuse-{uuid.uuid4().hex}",
    )

    first_outcome, first_snapshot = manager.start_process_job(
        ticker="AAPL",
        overwrite=False,
        document_ids=[" fil_2 ", "fil_1", "", "fil_2"],
    )
    assert first_outcome == "started"
    assert shared_state["first_completed_event"].wait(timeout=1.0) is True

    second_outcome, second_snapshot = manager.start_process_job(
        ticker="AAPL",
        overwrite=False,
        document_ids=["fil_1", "fil_2"],
    )

    assert second_outcome == "reused_active_job"
    assert second_snapshot["job"]["job_id"] == first_snapshot["job"]["job_id"]

    cancelled_outcome, _ = manager.cancel_job(first_snapshot["job"]["job_id"])
    assert cancelled_outcome == "cancellation_requested"
    cancelled_snapshot = _wait_for_job_snapshot(
        manager,
        first_snapshot["job"]["job_id"],
        lambda item: item["job"]["status"] == "cancelled",
    )

    assert shared_state["requested_document_ids"] == [["fil_1", "fil_2"]]
    assert cancelled_snapshot["progress"]["completed"] == 1


@pytest.mark.unit
def test_download_job_status_exposes_recent_issues(mocker: MockerFixture) -> None:
    """多表单保持可解析且保留失败摘要。参数：模拟器。返回：无。异常：断言失败。"""

    from alpha.fins.pipelines.sec_form_utils import split_form_input

    backend = _DownloadIssueBackend()
    spy = mocker.spy(backend, "download_stream")
    manager = IngestionJobManager(
        service_factory=lambda ticker: FinsIngestionService(backend=backend),
        manager_key=f"download-issues-{uuid.uuid4().hex}",
    )
    _, snapshot = manager.start_download_job(
        ticker="AAPL",
        form_types=["10-K", "10-Q"],
        filed_date_from=None,
        filed_date_to=None,
        overwrite=False,
    )
    final_snapshot = _wait_for_job_snapshot(
        manager,
        snapshot["job"]["job_id"],
        lambda item: item["job"]["status"] == "succeeded",
    )
    assert final_snapshot["recent_issues"] == [
        {
            "document_id": "fil_1",
            "status": "skipped",
            "reason_code": "not_modified",
            "reason_message": "所有文件均未修改，跳过重新下载",
        },
        {
            "document_id": "fil_2",
            "status": "failed",
            "reason_code": "file_download_failed",
            "reason_message": "network down",
        },
    ]
    assert final_snapshot["result_summary"]["filings_failed"] == 1
    assert spy.call_args is not None
    assert split_form_input(spy.call_args.kwargs["form_type"]) == ["10-K", "10-Q"]



def _wait_for_job_snapshot(
    manager: IngestionJobManager,
    job_id: str,
    predicate: Any,
    *,
    timeout_seconds: float = 2.0,
) -> dict[str, Any]:
    """轮询等待 job 满足目标状态。"""

    deadline = time.time() + timeout_seconds
    last_snapshot: Optional[dict[str, Any]] = None
    while time.time() < deadline:
        snapshot = manager.get_job_snapshot(job_id)
        if snapshot is not None:
            last_snapshot = snapshot
            if predicate(snapshot):
                return snapshot
        time.sleep(0.01)
    raise AssertionError(f"等待 job 超时: job_id={job_id} last_snapshot={last_snapshot}")
