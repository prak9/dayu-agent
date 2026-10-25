"""CnPipeline 离线快照导出流程测试。"""

from __future__ import annotations

import json
import logging
from io import BytesIO
from pathlib import Path
from typing import Any, Optional, Protocol

import pytest

from alpha.contracts.cancellation import CancelledError
from alpha.engine.processors.base import (
    SearchHit,
    SectionContent,
    SectionSummary,
    TableContent,
    TableSummary,
    build_search_hit,
    build_section_content,
    build_section_summary,
    build_table_content,
    build_table_summary,
)
from alpha.engine.processors.processor_registry import ProcessorRegistry
from alpha.engine.processors.source import Source
from alpha.fins.domain.document_models import FilingCreateRequest, MaterialCreateRequest
from alpha.fins.domain.enums import SourceKind
from alpha.fins.pipelines.cn_pipeline import CnPipeline
from alpha.fins.storage.local_file_store import LocalFileStore
from tests.fins.storage_testkit import build_storage_core


class _SourceRepositoryLike(Protocol):
    """CnPipeline process 测试所需的最小仓储边界。"""

    portfolio_root: Path

    def create_filing(self, req: FilingCreateRequest) -> object:
        """创建 filing 源文档。"""

    def create_material(self, req: MaterialCreateRequest) -> object:
        """创建 material 源文档。"""


def _repository(repository: _SourceRepositoryLike) -> _SourceRepositoryLike:
    """显式收窄 build_storage_core 返回的仓储类型。"""

    return repository


class FakeJsonProcessor:
    """测试用 JSON 处理器。"""

    PARSER_VERSION = "fake_json_processor_v1.0.0"

    @classmethod
    def get_parser_version(cls) -> str:
        """返回处理器版本。"""

        return str(cls.PARSER_VERSION)

    def __init__(
        self,
        source: Source,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> None:
        """初始化处理器。

        Args:
            source: 文档来源。
            form_type: 可选表单类型。
            media_type: 可选媒体类型。

        Returns:
            无。

        Raises:
            ValueError: 参数非法时抛出。
        """

        del form_type
        del media_type
        self._source = source

    @classmethod
    def supports(
        cls,
        source: Source,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> bool:
        """判断是否支持处理。

        Args:
            source: 文档来源。
            form_type: 可选表单类型。
            media_type: 可选媒体类型。

        Returns:
            是否支持。

        Raises:
            OSError: 读取失败时可能抛出。
        """

        del form_type
        resolved_media = str(media_type or source.media_type or "").lower()
        return "json" in resolved_media

    def list_sections(self) -> list[SectionSummary]:
        """返回章节列表。

        Args:
            无。

        Returns:
            章节列表。

        Raises:
            RuntimeError: 读取失败时抛出。
        """

        return [
            build_section_summary(
                ref="s_0001",
                title="章节一",
                level=1,
                parent_ref=None,
                preview="preview",
            )
        ]

    def get_section_title(self, ref: str) -> Optional[str]:
        """根据 section ref 获取章节标题。

        Args:
            ref: 章节引用。

        Returns:
            章节标题字符串；ref 不存在时返回 None。
        """
        for sec in self.list_sections():
            if sec.get("ref") == ref:
                return sec.get("title")
        return None

    def list_tables(self) -> list[TableSummary]:
        """返回表格列表。

        Args:
            无。

        Returns:
            表格列表。

        Raises:
            RuntimeError: 读取失败时抛出。
        """

        return [
            build_table_summary(
                table_ref="t_0001",
                caption=None,
                context_before="ctx",
                row_count=1,
                col_count=1,
                table_type="data",
                headers=["A"],
                section_ref="s_0001",
                is_financial=False,
            )
        ]

    def read_section(self, ref: str) -> SectionContent:
        """读取章节内容。

        Args:
            ref: 章节引用。

        Returns:
            章节内容。

        Raises:
            KeyError: 章节不存在时抛出。
        """

        return build_section_content(
            ref=ref,
            title="章节一",
            content="text [[t_0001]]",
            tables=["t_0001"],
            word_count=2,
            contains_full_text=False,
        )

    def read_table(self, table_ref: str) -> TableContent:
        """读取表格内容。

        Args:
            table_ref: 表格引用。

        Returns:
            表格内容。

        Raises:
            KeyError: 表格不存在时抛出。
        """

        return build_table_content(
            table_ref=table_ref,
            caption=None,
            data_format="records",
            data=[{"A": 1}],
            columns=["A"],
            row_count=1,
            col_count=1,
            section_ref="s_0001",
            table_type="data",
            is_financial=False,
        )

    def search(self, query: str, within_ref: Optional[str] = None) -> list[SearchHit]:
        """搜索章节内容。

        Args:
            query: 搜索词。
            within_ref: 可选章节范围。

        Returns:
            命中列表。

        Raises:
            RuntimeError: 搜索失败时抛出。
        """

        del within_ref
        if query:
            return [
                build_search_hit(
                    section_ref="s_0001",
                    section_title="章节一",
                    snippet=query,
                )
            ]
        return []

    def get_full_text(self) -> str:
        """返回文档全文。"""

        return "章节一 text"

    def get_full_text_with_table_markers(self) -> str:
        """返回带表格占位符的文档全文。"""

        return "章节一 text [[t_0001]]"


class BrokenJsonProcessor(FakeJsonProcessor):
    """测试用异常处理器。"""

    PARSER_VERSION = "broken_json_processor_v1.0.0"

    def __init__(
        self,
        source: Source,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> None:
        """初始化时抛错。

        Args:
            source: 文档来源。
            form_type: 可选表单类型。
            media_type: 可选媒体类型。

        Returns:
            无。

        Raises:
            RuntimeError: 始终抛出。
        """

        del source
        del form_type
        del media_type
        raise RuntimeError("processor init failed")


def _build_registry(processor_cls: type[FakeJsonProcessor]) -> ProcessorRegistry:
    """构建测试注册表。

    Args:
        processor_cls: 处理器类。

    Returns:
        注册表实例。

    Raises:
        RuntimeError: 注册失败时抛出。
    """

    registry = ProcessorRegistry()
    registry.register(processor_cls, name="fake_json_processor", priority=100, overwrite=True)
    return registry


def _prepare_source_document(
    repository: _SourceRepositoryLike,
    *,
    ticker: str,
    document_id: str,
    filename: str,
    source_kind: SourceKind,
    ingest_complete: bool = True,
    is_deleted: bool = False,
) -> None:
    """准备 source 文档与文件。

    Args:
        repository: 仓储实例。
        ticker: 股票代码。
        document_id: 文档 ID。
        filename: 文件名。
        source_kind: 来源类型。
        ingest_complete: 是否完成入库。
        is_deleted: 是否逻辑删除。

    Returns:
        无。

    Raises:
        OSError: 写入失败时抛出。
    """

    store = LocalFileStore(root=repository.portfolio_root, scheme="local")
    prefix = "filings" if source_kind == SourceKind.FILING else "materials"
    key = f"{ticker}/{prefix}/{document_id}/{filename}"
    file_meta = store.put_object(key, BytesIO(b"{}"))
    base_kwargs = {
        "ticker": ticker,
        "document_id": document_id,
        "internal_document_id": document_id,
        "form_type": "FY" if source_kind == SourceKind.FILING else "MATERIAL_OTHER",
        "primary_document": filename,
        "files": [file_meta],
        "meta": {
            "ingest_complete": ingest_complete,
            "is_deleted": is_deleted,
            "document_version": "v1",
            "source_fingerprint": "fingerprint_v1",
            "fiscal_year": 2025,
            "fiscal_period": "FY",
        },
    }
    if source_kind == SourceKind.FILING:
        repository.create_filing(FilingCreateRequest(**base_kwargs))
        return
    repository.create_material(MaterialCreateRequest(**base_kwargs))


@pytest.mark.unit
def test_cn_pipeline_process_runs_filings_and_materials(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """验证 process 会处理 filings 与 materials 并生成离线快照。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    repository = _repository(build_storage_core(tmp_path))
    _prepare_source_document(
        repository,
        ticker="000001",
        document_id="fil_cn_001",
        filename="filing_docling.json",
        source_kind=SourceKind.FILING,
    )
    _prepare_source_document(
        repository,
        ticker="000001",
        document_id="mat_001",
        filename="material_docling.json",
        source_kind=SourceKind.MATERIAL,
    )

    pipeline = CnPipeline(
        workspace_root=tmp_path,
        processor_registry=_build_registry(FakeJsonProcessor),
    )

    with caplog.at_level(logging.INFO):
        result = pipeline.process("000001")

    assert result["status"] == "ok"
    assert result["filing_summary"]["processed"] == 1
    assert result["material_summary"]["processed"] == 1

    assert "document_id=fil_cn_001 status=processed form_type=FY fiscal_year=2025" in caplog.text
    assert "document_id=mat_001 status=processed form_type=MATERIAL_OTHER fiscal_year=2025" in caplog.text
    filing_snapshot_dir = tmp_path / "portfolio" / "000001" / "processed" / "fil_cn_001"
    material_snapshot_dir = tmp_path / "portfolio" / "000001" / "processed" / "mat_001"
    assert (filing_snapshot_dir / "tool_snapshot_meta.json").exists()
    assert (material_snapshot_dir / "tool_snapshot_meta.json").exists()
    assert not (filing_snapshot_dir / "tool_snapshot_search_document.json").exists()
    assert not (filing_snapshot_dir / "tool_snapshot_query_xbrl_facts.json").exists()


@pytest.mark.unit
def test_process_filing_honors_cancel_checker_before_export(tmp_path: Path) -> None:
    """验证 CN 单文档处理会在同步阶段边界响应取消请求。"""

    repository = _repository(build_storage_core(tmp_path))
    _prepare_source_document(
        repository,
        ticker="000001",
        document_id="fil_cn_cancelled",
        filename="filing_docling.json",
        source_kind=SourceKind.FILING,
    )

    pipeline = CnPipeline(
        workspace_root=tmp_path,
        processor_registry=_build_registry(FakeJsonProcessor),
    )

    with pytest.raises(CancelledError, match="操作已被取消"):
        pipeline.process_filing(
            "000001",
            "fil_cn_cancelled",
            cancel_checker=lambda: True,
        )

    processed_dir = tmp_path / "portfolio" / "000001" / "processed" / "fil_cn_cancelled"
    assert not processed_dir.exists()


@pytest.mark.unit
def test_cn_pipeline_process_skips_incomplete_and_deleted(tmp_path: Path) -> None:
    """验证 process 会跳过未完成与已删除文档。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    repository = _repository(build_storage_core(tmp_path))
    _prepare_source_document(
        repository,
        ticker="000001",
        document_id="fil_cn_incomplete",
        filename="a_docling.json",
        source_kind=SourceKind.FILING,
        ingest_complete=False,
    )
    _prepare_source_document(
        repository,
        ticker="000001",
        document_id="mat_deleted",
        filename="b_docling.json",
        source_kind=SourceKind.MATERIAL,
        is_deleted=True,
    )

    pipeline = CnPipeline(
        workspace_root=tmp_path,
        processor_registry=_build_registry(FakeJsonProcessor),
    )
    result = pipeline.process("000001")

    assert result["filing_summary"]["processed"] == 0
    assert result["filing_summary"]["skipped"] == 1
    assert result["material_summary"]["processed"] == 0
    assert result["material_summary"]["skipped"] == 1


@pytest.mark.unit
def test_cn_pipeline_process_can_limit_to_requested_document_ids(tmp_path: Path) -> None:
    """验证 CN `process(document_ids=...)` 只处理指定文档。"""

    repository = build_storage_core(tmp_path)
    _prepare_source_document(
        repository,
        ticker="000001",
        document_id="fil_cn_001",
        filename="a_docling.json",
        source_kind=SourceKind.FILING,
    )
    _prepare_source_document(
        repository,
        ticker="000001",
        document_id="fil_cn_002",
        filename="b_docling.json",
        source_kind=SourceKind.FILING,
    )

    pipeline = CnPipeline(
        workspace_root=tmp_path,
        processor_registry=_build_registry(FakeJsonProcessor),
    )
    result = pipeline.process("000001", document_ids=["fil_cn_002"])

    assert result["filing_summary"]["total"] == 1
    assert result["filing_summary"]["processed"] == 1
    assert (tmp_path / "portfolio" / "000001" / "processed" / "fil_cn_002").exists()
    assert not (tmp_path / "portfolio" / "000001" / "processed" / "fil_cn_001").exists()


@pytest.mark.unit
def test_cn_pipeline_process_filing_respects_version_and_overwrite(tmp_path: Path) -> None:
    """验证 process_filing 的版本命中与 overwrite 行为。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    repository = build_storage_core(tmp_path)
    _prepare_source_document(
        repository,
        ticker="000001",
        document_id="fil_cn_ver",
        filename="f_docling.json",
        source_kind=SourceKind.FILING,
    )
    pipeline = CnPipeline(
        workspace_root=tmp_path,
        processor_registry=_build_registry(FakeJsonProcessor),
    )

    first = pipeline.process_filing("000001", "fil_cn_ver", overwrite=False)
    second = pipeline.process_filing("000001", "fil_cn_ver", overwrite=False)
    third = pipeline.process_filing("000001", "fil_cn_ver", overwrite=True)

    assert first["status"] == "processed"
    assert second["status"] == "skipped"
    assert second["reason"] == "version_matched"
    assert third["status"] == "processed"


@pytest.mark.unit
def test_cn_pipeline_process_fails_when_processor_init_error(tmp_path: Path) -> None:
    """验证处理器异常会在 process 汇总中标记 failed。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    repository = build_storage_core(tmp_path)
    _prepare_source_document(
        repository,
        ticker="000001",
        document_id="fil_cn_fail",
        filename="f_docling.json",
        source_kind=SourceKind.FILING,
    )
    pipeline = CnPipeline(
        workspace_root=tmp_path,
        processor_registry=_build_registry(BrokenJsonProcessor),
    )

    result = pipeline.process("000001")
    assert result["filing_summary"]["failed"] == 1


@pytest.mark.unit
def test_cn_pipeline_process_filing_ci_exports_full_snapshot_files(tmp_path: Path) -> None:
    """验证 CN `process_filing(ci=True)` 会导出 CI 全量快照文件。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    repository = build_storage_core(tmp_path)
    document_id = "fil_cn_truth"
    _prepare_source_document(
        repository,
        ticker="000001",
        document_id=document_id,
        filename="f_docling.json",
        source_kind=SourceKind.FILING,
    )
    pipeline = CnPipeline(
        workspace_root=tmp_path,
        processor_registry=_build_registry(FakeJsonProcessor),
    )

    result = pipeline.process_filing("000001", document_id, overwrite=False, ci=True)

    assert result["status"] == "processed"
    processed_dir = tmp_path / "portfolio" / "000001" / "processed" / document_id
    expected_files = [
        "tool_snapshot_list_documents.json",
        "tool_snapshot_get_document_sections.json",
        "tool_snapshot_read_section.json",
        "tool_snapshot_search_document.json",
        "tool_snapshot_list_tables.json",
        "tool_snapshot_get_table.json",
        "tool_snapshot_get_page_content.json",
        "tool_snapshot_get_financial_statement.json",
        "tool_snapshot_query_xbrl_facts.json",
        "tool_snapshot_meta.json",
    ]
    for file_name in expected_files:
        assert (processed_dir / file_name).exists()

    search_payload = json.loads((processed_dir / "tool_snapshot_search_document.json").read_text(encoding="utf-8"))
    search_queries = [item["request"]["query"] for item in search_payload["calls"]]
    first_request = search_payload["calls"][0]["request"]
    assert len(search_queries) == 40
    assert "公司沿革" in search_queries
    assert "营业收入" in search_queries
    assert "净利润" in search_queries
    assert "回购计划" in search_queries
    assert first_request["query"] == first_request["query_text"]
    assert first_request["query_id"].startswith("annual_quarter_core40.q")
    assert first_request["query_intent"]
    assert first_request["query_weight"] == 1.0

    page_payload = json.loads((processed_dir / "tool_snapshot_get_page_content.json").read_text(encoding="utf-8"))
    first_page_response = page_payload["calls"][0]["response"]
    assert first_page_response["error"]["code"] == "not_supported"
    assert first_page_response["supported"] is False


@pytest.mark.unit
def test_cn_pipeline_process_filing_ci_rebuilds_snapshot_meta_on_version_skip(tmp_path: Path) -> None:
    """验证 CN `process_filing(ci=True)` 命中版本跳过时会补齐快照文件。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    repository = build_storage_core(tmp_path)
    document_id = "fil_cn_truth_skip"
    _prepare_source_document(
        repository,
        ticker="000001",
        document_id=document_id,
        filename="f_docling.json",
        source_kind=SourceKind.FILING,
    )
    pipeline = CnPipeline(
        workspace_root=tmp_path,
        processor_registry=_build_registry(FakeJsonProcessor),
    )

    first = pipeline.process_filing("000001", document_id, overwrite=False, ci=True)
    assert first["status"] == "processed"

    processed_dir = tmp_path / "portfolio" / "000001" / "processed" / document_id
    snapshot_meta_file = processed_dir / "tool_snapshot_meta.json"
    snapshot_meta_file.unlink()

    second = pipeline.process_filing("000001", document_id, overwrite=False, ci=True)
    assert second["status"] == "processed"
    assert snapshot_meta_file.exists()
