"""受 Host 取消约束的真实财报读取快照边界。"""

from io import BytesIO
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

import pytest
from pytest_mock import MockerFixture

from alpha.contracts.cancellation import CancellationToken, CancelledError
from alpha.contracts.fins import DownloadResultData, FinsCommandName, FinsEvent, FinsEventType, FinsResult, ProcessSingleResultData
from alpha.fins.domain.document_models import DocumentEntry
from alpha.fins.research_reader import FinsResearchReader
from alpha.fins.service_runtime import DefaultFinsRuntime


def _reader(mocker: MockerFixture, tmp_path: Path) -> FinsResearchReader:
    """模拟仓储端口，直接消费真实快照代码。参数：mock。返回：读取器。异常：无。"""
    runtime = mocker.Mock(spec=DefaultFinsRuntime.create(workspace_root=tmp_path))
    runtime.processed_repository.get_processed_meta.return_value = {"parser_version": "v1", "filing_date": "2026-01-01"}
    runtime.source_repository.get_source_meta.return_value = {"filing_date": "2026-01-01"}
    runtime.source_repository.get_primary_source.return_value.open.side_effect = lambda: BytesIO(b"source")
    runtime.blob_repository.list_entries.return_value = [DocumentEntry("snapshot.json", True), DocumentEntry("nested", False)]
    runtime.blob_repository.read_file_bytes.return_value = b"parsed"
    runtime.get_tool_service.return_value.get_financial_statement.return_value = {"periods": [{"period_end": "2026-01-01"}], "rows": [{"values": [12]}]}
    runtime.get_tool_service.return_value.get_table.return_value = {"table_ref": "t_1", "rows": [["Revenue", 12]]}
    runtime.execute.return_value = FinsResult(FinsCommandName.PROCESS_FILING, ProcessSingleResultData("sec", "process_filing", "processed", "AAPL", "doc"))
    return FinsResearchReader(cast(DefaultFinsRuntime, runtime))


def test_read_has_actual_source_processed_and_result_snapshots(mocker: MockerFixture, tmp_path: Path) -> None:
    """结果包含实际数值和可追溯哈希。参数：mock。返回：无。异常：断言失败。"""
    reader = _reader(mocker, tmp_path)
    result = reader.read("AAPL", "doc", statement_type="income", table_ref=None, token=CancellationToken())
    snapshot = result["snapshot"]
    assert isinstance(snapshot, dict) and len(str(snapshot["source_hash"])) == 64 and len(str(snapshot["processed_hash"])) == 64
    assert result["result"] == {"periods": [{"period_end": "2026-01-01"}], "rows": [{"values": [12]}]}
    assert result["accessed_at"]
    table = reader.read("AAPL", "doc", statement_type=None, table_ref="t_1", token=None)
    assert table["table_ref"] == "t_1"


def test_changed_snapshot_and_ambiguous_locators_are_rejected(mocker: MockerFixture, tmp_path: Path) -> None:
    """读取期间变更和定位歧义不能生成凭据。参数：mock。返回：无。异常：断言失败。"""
    reader = _reader(mocker, tmp_path)
    mocker.patch.object(reader.runtime.processed_repository, "get_processed_meta", side_effect=[{"parser_version": "v1"}, {"parser_version": "v2"}])
    with pytest.raises(RuntimeError, match="发生变化"):
        reader.read("AAPL", "doc", statement_type="income", table_ref=None, token=None)
    with pytest.raises(ValueError):
        reader.read("AAPL", "doc", statement_type=None, table_ref=None, token=None)
    with pytest.raises(ValueError):
        reader.read("AAPL", "doc", statement_type="income", table_ref="t1", token=None)


def test_cancelled_read_or_prepare_never_starts_work(mocker: MockerFixture, tmp_path: Path) -> None:
    """已经取消时不处理或读取原件。参数：mock。返回：无。异常：断言失败。"""
    reader = _reader(mocker, tmp_path)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(CancelledError):
        reader.prepare("AAPL", "doc", token)
    with pytest.raises(CancelledError):
        reader.read("AAPL", "doc", statement_type="income", table_ref=None, token=token)


def test_prepare_uses_parent_cancellation_and_rejects_stream_result(mocker: MockerFixture, tmp_path: Path) -> None:
    """同步处理消费父取消，不留下独立后台 job。参数：mock。返回：无。异常：断言失败。"""
    reader = _reader(mocker, tmp_path)
    assert reader.prepare("AAPL", "doc", CancellationToken())["processed"] is True
    assert reader.prepare("AAPL", "doc", None)["document_id"] == "doc"
    mocker.patch.object(reader.runtime, "execute", return_value=None)
    with pytest.raises(RuntimeError, match="流式"):
        reader.prepare("AAPL", "doc", None)


def test_failed_processing_cannot_be_reported_as_prepared(mocker: MockerFixture, tmp_path: Path) -> None:
    """处理失败不能被包装为成功。参数：mock、目录。返回：无。异常：断言失败。"""
    reader = _reader(mocker, tmp_path)
    mocker.patch.object(reader.runtime, "execute", return_value=FinsResult(FinsCommandName.PROCESS_FILING,
                        ProcessSingleResultData("sec", "process_filing", "failed", "AAPL", "doc")))
    with pytest.raises(RuntimeError, match="未完成"):
        reader.prepare("AAPL", "doc", None)


async def _downloads(closed: list[bool], *, cancel: CancellationToken | None = None, result: bool = True) -> AsyncGenerator[FinsEvent, None]:
    """提供有界结果流。参数：收尾记录、可选取消、是否含结果。返回：事件流。异常：无。"""
    try:
        if cancel is not None:
            cancel.cancel()
        if result:
            yield FinsEvent(FinsEventType.RESULT, FinsCommandName.DOWNLOAD, DownloadResultData("sec", "ok", "BABA"))
    finally:
        closed.append(True)


def test_download_consumes_selected_forms_and_closes_parent_owned_stream(mocker: MockerFixture, tmp_path: Path) -> None:
    """下载沿用明确表单并在当前 Host 作用域收尾。参数：mock、目录。返回：无。异常：断言失败。"""
    reader = _reader(mocker, tmp_path)
    closed: list[bool] = []
    execute = mocker.patch.object(reader.runtime, "execute", return_value=_downloads(closed))
    result = reader.download("BABA", ("20-F", "6-K"), "2025-01-01", "2026-10-25", CancellationToken())
    assert result["ticker"] == "BABA" and closed == [True]
    command = execute.call_args.args[0]
    assert command.payload.form_type == ("20-F", "6-K") and command.stream
    closed.clear()
    token = CancellationToken()
    execute.return_value = _downloads(closed, cancel=token)
    with pytest.raises(CancelledError):
        reader.download("BABA", (), None, None, token)
    assert closed == [True]


def test_download_missing_result_and_wrong_execution_shape_fail(mocker: MockerFixture, tmp_path: Path) -> None:
    """无最终清单不能冒充成功。参数：mock、目录。返回：无。异常：断言失败。"""
    reader = _reader(mocker, tmp_path)
    mocker.patch.object(reader.runtime, "execute", return_value=_downloads([], result=False))
    with pytest.raises(RuntimeError, match="完整结果"):
        reader.download("BABA", (), None, None, None)
    mocker.patch.object(reader.runtime, "execute", return_value=None)
    with pytest.raises(RuntimeError, match="流式"):
        reader.download("BABA", (), None, None, None)
