"""tool_snapshot_export 模块测试。"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, Optional

import pytest

from alpha.contracts.cancellation import CancelledError
from alpha.fins.domain.document_models import (
    CompanyMeta,
    DocumentHandle,
    DocumentQuery,
    FileObjectMeta,
    ProcessedCreateRequest,
    ProcessedHandle,
    ProcessedUpdateRequest,
    SourceHandle,
)
from alpha.fins.domain.enums import SourceKind
from alpha.fins.storage import FsProcessedDocumentRepository
from alpha.fins.storage.local_file_source import LocalFileSource
from tests.fins.legacy_repository_adapters import (
    export_tool_snapshot_with_legacy_repository as export_tool_snapshot,
)


class FakeRepository:
    """用于测试导出器的仓储桩。"""

    def __init__(self, *, market: str, root: Path) -> None:
        """初始化仓储桩。

        Args:
            market: 公司市场编码。
            root: 文件输出根目录。

        Returns:
            无。

        Raises:
            RuntimeError: 初始化失败时抛出。
        """

        self._market = market
        self._root = root
        self._filing_meta: dict[str, dict[str, Any]] = {
            "fil_001": {
                "document_id": "fil_001",
                "form_type": "10-K",
                "fiscal_year": 2025,
                "fiscal_period": "FY",
                "report_date": "2025-09-30",
                "filing_date": "2025-11-01",
                "amended": False,
                "ingest_complete": True,
                "is_deleted": False,
            },
            "fil_deleted": {
                "document_id": "fil_deleted",
                "form_type": "10-Q",
                "fiscal_year": 2025,
                "fiscal_period": "Q1",
                "ingest_complete": True,
                "is_deleted": True,
            },
        }
        self._material_meta: dict[str, dict[str, Any]] = {
            "mat_001": {
                "document_id": "mat_001",
                "form_type": "MATERIAL_OTHER",
                "material_name": "Deck",
                "filing_date": "2025-06-01",
                "report_date": "2025-06-01",
                "amended": False,
                "ingest_complete": True,
                "is_deleted": False,
            },
            "mat_incomplete": {
                "document_id": "mat_incomplete",
                "form_type": "MATERIAL_OTHER",
                "ingest_complete": False,
                "is_deleted": False,
            },
        }

    def get_company_meta(self, ticker: str) -> CompanyMeta:
        """返回公司元数据。

        Args:
            ticker: 股票代码。

        Returns:
            公司元数据对象。

        Raises:
            RuntimeError: 读取失败时抛出。
        """

        return CompanyMeta(
            company_id=ticker,
            company_name=f"{ticker} Co.",
            ticker=ticker,
            market=self._market,
            resolver_version="test",
            updated_at="2026-01-01T00:00:00+00:00",
        )

    def resolve_existing_ticker(self, candidates: list[str]) -> Optional[str]:
        """按候选顺序解析已存在 ticker。"""

        return candidates[0] if candidates else None

    def list_document_ids(self, ticker: str, source_kind: Optional[SourceKind] = None) -> list[str]:
        """返回文档 ID 列表。

        Args:
            ticker: 股票代码。
            source_kind: 来源类型。

        Returns:
            文档 ID 列表。

        Raises:
            RuntimeError: 查询失败时抛出。
        """

        del ticker
        if source_kind == SourceKind.FILING:
            return sorted(self._filing_meta.keys())
        if source_kind == SourceKind.MATERIAL:
            return sorted(self._material_meta.keys())
        return sorted(list(self._filing_meta.keys()) + list(self._material_meta.keys()))

    def get_document_meta(self, ticker: str, document_id: str) -> dict[str, Any]:
        """返回文档元数据。

        Args:
            ticker: 股票代码。
            document_id: 文档 ID。

        Returns:
            文档元数据字典。

        Raises:
            FileNotFoundError: 文档不存在时抛出。
        """

        del ticker
        if document_id in self._filing_meta:
            return dict(self._filing_meta[document_id])
        if document_id in self._material_meta:
            return dict(self._material_meta[document_id])
        raise FileNotFoundError(document_id)

    def get_source_handle(
        self,
        ticker: str,
        document_id: str,
        source_kind: SourceKind,
    ) -> SourceHandle:
        """返回源文档句柄。

        Args:
            ticker: 股票代码。
            document_id: 文档 ID。
            source_kind: 文档来源类型。

        Returns:
            源文档句柄。

        Raises:
            FileNotFoundError: 文档不存在时抛出。
        """

        if self._resolve_meta_by_kind(document_id=document_id, source_kind=source_kind) is None:
            raise FileNotFoundError(document_id)
        return SourceHandle(
            ticker=ticker,
            document_id=document_id,
            source_kind=source_kind.value,
        )

    def get_primary_source(
        self,
        ticker: str,
        document_id: str,
        source_kind: SourceKind,
    ) -> LocalFileSource:
        """返回主文件 Source。

        Args:
            ticker: 股票代码。
            document_id: 文档 ID。
            source_kind: 文档来源类型。

        Returns:
            本地文件 Source。

        Raises:
            FileNotFoundError: 文档不存在时抛出。
            OSError: 文件创建失败时抛出。
        """

        source_handle = self.get_source_handle(
            ticker=ticker,
            document_id=document_id,
            source_kind=source_kind,
        )
        source_path = self._ensure_source_file(source_handle=source_handle)
        return LocalFileSource(
            path=source_path,
            uri=str(source_path),
            media_type="text/html",
            content_length=source_path.stat().st_size,
        )

    def get_processed_handle(self, ticker: str, document_id: str) -> ProcessedHandle:
        """返回处理产物句柄。

        Args:
            ticker: 股票代码。
            document_id: 文档 ID。

        Returns:
            处理产物句柄。

        Raises:
            RuntimeError: 读取失败时抛出。
        """

        return ProcessedHandle(ticker=ticker, document_id=document_id)

    def get_processed_meta(self, ticker: str, document_id: str) -> dict[str, Any]:
        """返回 processed meta 字典。

        Args:
            ticker: 股票代码。
            document_id: 文档 ID。

        Returns:
            处理元数据字典。

        Raises:
            FileNotFoundError: 不存在时抛出。
        """

        del ticker
        if document_id.startswith("fil_"):
            return {"has_financial_statement": True, "has_xbrl": True}
        return {"has_financial_statement": False, "has_xbrl": False}

    def create_processed(self, req: ProcessedCreateRequest) -> DocumentHandle:
        """通过真实文件系统 processed 仓储创建文档。

        Args:
            req: processed 创建请求。

        Returns:
            文档句柄。

        Raises:
            OSError: 底层仓储写入失败时抛出。
        """

        return self._build_processed_repository().create_processed(req)

    def update_processed(self, req: ProcessedUpdateRequest) -> DocumentHandle:
        """通过真实文件系统 processed 仓储更新文档。

        Args:
            req: processed 更新请求。

        Returns:
            文档句柄。

        Raises:
            FileNotFoundError: processed 目录不存在时抛出。
            OSError: 底层仓储写入失败时抛出。
        """

        return self._build_processed_repository().update_processed(req)

    def store_file(
        self,
        handle: SourceHandle | ProcessedHandle,
        filename: str,
        data: BinaryIO,
        *,
        content_type: Optional[str] = None,
        metadata: Optional[dict[str, str]] = None,
    ) -> FileObjectMeta:
        """按 processed 句柄落盘文件。

        Args:
            handle: 处理产物句柄。
            filename: 文件名。
            data: 文件二进制流。
            content_type: 可选 MIME 类型。
            metadata: 可选扩展元数据。

        Returns:
            文件对象元数据。

        Raises:
            OSError: 文件写入失败时抛出。
        """

        del metadata
        target_dir = self._root / "portfolio" / handle.ticker / "processed" / handle.document_id
        target_dir.mkdir(parents=True, exist_ok=True)
        payload = data.read()
        if isinstance(data, BytesIO):
            data.seek(0)
        target_path = target_dir / filename
        target_path.write_bytes(payload)
        return FileObjectMeta(
            uri=str(target_path),
            content_type=content_type,
            size=len(payload),
        )

    def _resolve_meta_by_kind(
        self,
        *,
        document_id: str,
        source_kind: SourceKind,
    ) -> Optional[dict[str, Any]]:
        """按来源类型解析文档元数据。

        Args:
            document_id: 文档 ID。
            source_kind: 文档来源类型。

        Returns:
            文档元数据；不存在返回 `None`。

        Raises:
            RuntimeError: 解析失败时抛出。
        """

        if source_kind == SourceKind.FILING:
            return self._filing_meta.get(document_id)
        if source_kind == SourceKind.MATERIAL:
            return self._material_meta.get(document_id)
        return None

    def _ensure_source_file(self, *, source_handle: SourceHandle) -> Path:
        """确保测试源文件存在。

        Args:
            source_handle: 源文档句柄。

        Returns:
            测试源文件路径。

        Raises:
            OSError: 写入失败时抛出。
        """

        folder_name = "filings" if source_handle.source_kind == SourceKind.FILING.value else "materials"
        target_dir = (
            self._root
            / "portfolio"
            / source_handle.ticker
            / folder_name
            / source_handle.document_id
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        source_path = target_dir / "primary.html"
        if not source_path.exists():
            source_path.write_text("<html><body>fixture</body></html>", encoding="utf-8")
        return source_path

    def _build_processed_repository(self) -> FsProcessedDocumentRepository:
        """构建真实文件系统 processed 仓储。

        Args:
            无。

        Returns:
            指向当前测试根目录的 processed 仓储。

        Raises:
            OSError: 仓储初始化失败时抛出。
        """

        return FsProcessedDocumentRepository(self._root)


class BasicProcessorWithoutExtendedCapabilities:
    """仅具备基础章节/表格能力的处理器桩。"""

    PARSER_VERSION = "fake_parser_v1"

    def list_sections(self) -> list[dict[str, Any]]:
        """返回章节列表。

        Args:
            无。

        Returns:
            章节列表。

        Raises:
            RuntimeError: 读取失败时抛出。
        """

        return [{"ref": "s_0001", "title": "章节一", "level": 1, "parent_ref": None, "preview": "p"}]

    def list_tables(self) -> list[dict[str, Any]]:
        """返回表格列表。

        Args:
            无。

        Returns:
            空表格列表。

        Raises:
            RuntimeError: 读取失败时抛出。
        """

        return []

    def read_section(self, ref: str) -> dict[str, Any]:
        """读取章节内容。

        Args:
            ref: 章节引用。

        Returns:
            章节内容字典。

        Raises:
            KeyError: 章节不存在时抛出。
        """

        return {
            "ref": ref,
            "title": "章节一",
            "content": "这里是正文",
            "tables": [],
            "word_count": 4,
            "contains_full_text": True,
        }

    def read_table(self, table_ref: str) -> dict[str, Any]:
        """读取表格内容。

        Args:
            table_ref: 表格引用。

        Returns:
            表格内容字典。

        Raises:
            KeyError: 表格不存在时抛出。
        """

        return {
            "table_ref": table_ref,
            "caption": None,
            "data_format": "records",
            "data": [],
            "columns": [],
            "row_count": 0,
            "col_count": 0,
            "is_financial": False,
        }

    def search(self, query: str, within_ref: Optional[str] = None) -> list[dict[str, Any]]:
        """返回搜索命中。

        Args:
            query: 查询词。
            within_ref: 可选章节范围。

        Returns:
            命中列表。

        Raises:
            RuntimeError: 搜索失败时抛出。
        """

        del within_ref
        return [{"section_ref": "s_0001", "section_title": "章节一", "snippet": query}]


class FakeProcessorRegistry:
    """处理器注册表桩，固定返回同一个 Processor 实例。"""

    def __init__(self, processor: BasicProcessorWithoutExtendedCapabilities) -> None:
        """初始化注册表桩。

        Args:
            processor: 固定返回的处理器实例。

        Returns:
            无。

        Raises:
            RuntimeError: 初始化失败时抛出。
        """

        self._processor = processor

    def create(
        self,
        source: Any,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> BasicProcessorWithoutExtendedCapabilities:
        """创建处理器实例。

        Args:
            source: 源对象（测试中不使用）。
            form_type: 表单类型（测试中不使用）。
            media_type: 媒体类型（测试中不使用）。

        Returns:
            固定处理器实例。

        Raises:
            RuntimeError: 创建失败时抛出。
        """

        del source, form_type, media_type
        return self._processor

    def create_with_fallback(
        self,
        source: Any,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
        on_fallback: Optional[Any] = None,
    ) -> BasicProcessorWithoutExtendedCapabilities:
        """兼容统一回退接口并复用 create。

        Args:
            source: 源对象（测试中不使用）。
            form_type: 表单类型（测试中不使用）。
            media_type: 媒体类型（测试中不使用）。
            on_fallback: 回退回调（本桩不触发）。

        Returns:
            固定处理器实例。

        Raises:
            RuntimeError: 创建失败时抛出。
        """

        del on_fallback
        return self.create(source, form_type=form_type, media_type=media_type)


class FinancialStatementCapableProcessor(BasicProcessorWithoutExtendedCapabilities):
    """具备财务报表能力的处理器桩。"""

    def get_financial_statement(self, statement_type: str) -> dict[str, Any]:
        """返回带 XBRL 质量标记的财务报表结果。

        Args:
            statement_type: 报表类型。

        Returns:
            财报结果字典。

        Raises:
            RuntimeError: 读取失败时抛出。
        """

        return {
            "statement_type": statement_type,
            "data_quality": "xbrl",
            "currency": "USD",
            "rows": [
                {"concept": "us-gaap_Revenues", "label": "Revenue", "values": [100.0]},
            ],
            "periods": [
                {"period_end": "2025-09-30", "fiscal_year": 2025, "fiscal_period": "FY"},
            ],
            "units": ["USD"],
        }


class ExtractedFinancialStatementCapableProcessor(BasicProcessorWithoutExtendedCapabilities):
    """具备表格回退财务报表能力的处理器桩。"""

    def get_financial_statement(self, statement_type: str) -> dict[str, Any]:
        """返回带 extracted 质量标记的财务报表结果。

        Args:
            statement_type: 报表类型。

        Returns:
            财报结果字典。

        Raises:
            RuntimeError: 读取失败时抛出。
        """

        return {
            "statement_type": statement_type,
            "data_quality": "extracted",
            "currency": "HKD",
            "rows": [
                {"concept": "", "label": "Revenue", "values": [100.0, 120.0]},
            ],
            "periods": [
                {"period_end": "2024-12-31", "fiscal_year": 2024, "fiscal_period": "Q4"},
                {"period_end": "2025-12-31", "fiscal_year": 2025, "fiscal_period": "Q4"},
            ],
            "units": "HK$ in thousands",
            "scale": "thousands",
        }


@pytest.mark.unit
def test_export_tool_snapshot_writes_offline_files_and_preserves_not_supported(tmp_path: Path) -> None:
    """验证离线快照导出会生成默认工具文件，并保留 `not_supported` 结果。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    repository = FakeRepository(market="CN", root=tmp_path)
    processor = BasicProcessorWithoutExtendedCapabilities()
    processor_registry = FakeProcessorRegistry(processor)
    output_dir = tmp_path / "portfolio" / "000001" / "processed" / "fil_001"
    processed_handle = repository.get_processed_handle("000001", "fil_001")
    summary = export_tool_snapshot(
        repository=repository,
        processor_registry=processor_registry,
        processed_handle=processed_handle,
        ticker="000001",
        document_id="fil_001",
        source_kind=SourceKind.FILING,
        ci=False,
        expected_parser_signature="fake_parser_v1",
        source_meta={
            "form_type": "10-K",
            "document_version": "v1",
            "source_fingerprint": "fp_v1",
            "fiscal_year": 2025,
            "fiscal_period": "FY",
            "report_date": "2025-09-30",
        },
    )

    assert len(summary["written_files"]) == 8
    expected_files = [
        "tool_snapshot_list_documents.json",
        "tool_snapshot_get_document_sections.json",
        "tool_snapshot_read_section.json",
        "tool_snapshot_list_tables.json",
        "tool_snapshot_get_table.json",
        "tool_snapshot_get_page_content.json",
        "tool_snapshot_get_financial_statement.json",
        "tool_snapshot_meta.json",
    ]
    for file_name in expected_files:
        assert (output_dir / file_name).exists()

    assert not (output_dir / "tool_snapshot_search_document.json").exists()
    assert not (output_dir / "tool_snapshot_query_xbrl_facts.json").exists()

    sections_payload = json.loads((output_dir / "tool_snapshot_get_document_sections.json").read_text(encoding="utf-8"))
    sections_response = sections_payload["calls"][0]["response"]
    assert "has_page_info" not in sections_response

    list_tables_payload = json.loads((output_dir / "tool_snapshot_list_tables.json").read_text(encoding="utf-8"))
    list_tables_response = list_tables_payload["calls"][0]["response"]
    assert "has_page_info" not in list_tables_response

    page_payload = json.loads((output_dir / "tool_snapshot_get_page_content.json").read_text(encoding="utf-8"))
    assert page_payload["calls"][0]["request"]["page_no"] == 1
    assert page_payload["calls"][0]["response"]["error"]["code"] == "not_supported"
    assert page_payload["calls"][0]["response"]["supported"] is False

    statement_payload = json.loads(
        (output_dir / "tool_snapshot_get_financial_statement.json").read_text(encoding="utf-8")
    )
    assert len(statement_payload["calls"]) == 5
    assert statement_payload["calls"][0]["response"]["error"]["code"] == "not_supported"

    meta_payload = json.loads((output_dir / "tool_snapshot_meta.json").read_text(encoding="utf-8"))
    assert meta_payload["form_type"] == "10-K"
    assert meta_payload["document_type"] == "annual_report"
    assert meta_payload["has_financial_statement"] is False
    assert meta_payload["has_xbrl"] is False
    assert meta_payload["has_financial_data"] is False
    assert meta_payload["search_query_pack_name"] == "offline_disabled"
    assert meta_payload["search_query_pack_version"] == "search_query_pack_v1.0.0"
    assert meta_payload["search_query_count"] == 0

    list_documents_payload = json.loads((output_dir / "tool_snapshot_list_documents.json").read_text(encoding="utf-8"))
    listed_ids = [item["document_id"] for item in list_documents_payload["calls"][0]["response"]["documents"]]
    assert "fil_001" in listed_ids
    assert "mat_001" in listed_ids
    assert "fil_deleted" not in listed_ids
    assert "mat_incomplete" not in listed_ids

    summaries = FsProcessedDocumentRepository(tmp_path).list_processed_documents(
        "000001",
        DocumentQuery(source_kind=SourceKind.FILING.value),
    )
    assert [item.document_id for item in summaries] == ["fil_001"]


@pytest.mark.unit
def test_export_tool_snapshot_ci_uses_mixed_queries_for_hk_market(tmp_path: Path) -> None:
    """验证 CI 快照在 HK 市场使用繁简混合查询词包。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    repository = FakeRepository(market="HK", root=tmp_path)
    processor = BasicProcessorWithoutExtendedCapabilities()
    processor_registry = FakeProcessorRegistry(processor)
    output_dir = tmp_path / "portfolio" / "0300" / "processed" / "fil_001"
    processed_handle = repository.get_processed_handle("0300", "fil_001")

    export_tool_snapshot(
        repository=repository,
        processor_registry=processor_registry,
        processed_handle=processed_handle,
        ticker="0300",
        document_id="fil_001",
        source_kind=SourceKind.FILING,
        ci=True,
        expected_parser_signature="fake_parser_v1",
        source_meta={
            "form_type": "10-K",
            "document_version": "v1",
            "source_fingerprint": "fp_v1",
            "fiscal_year": 2025,
            "fiscal_period": "FY",
            "report_date": "2025-09-30",
        },
    )

    search_payload = json.loads((output_dir / "tool_snapshot_search_document.json").read_text(encoding="utf-8"))
    search_queries = [item["request"]["query"] for item in search_payload["calls"]]
    first_request = search_payload["calls"][0]["request"]
    assert len(search_queries) == 40
    assert "回購" in search_queries
    assert "營業收入" in search_queries
    assert "淨利潤" in search_queries
    assert first_request["query"] == first_request["query_text"]
    assert first_request["query_id"].startswith("annual_quarter_core40.q")
    assert first_request["query_intent"]
    assert first_request["query_weight"] == 1.0

    xbrl_payload = json.loads((output_dir / "tool_snapshot_query_xbrl_facts.json").read_text(encoding="utf-8"))
    xbrl_request = xbrl_payload["calls"][0]["request"]
    assert xbrl_request["concepts"] == ["Revenues", "NetIncomeLoss", "Assets"]
    assert xbrl_request["fiscal_year"] == 2025
    assert xbrl_request["fiscal_period"] == "FY"
    assert xbrl_request["period_end"] == "2025-09-30"

    meta_payload = json.loads((output_dir / "tool_snapshot_meta.json").read_text(encoding="utf-8"))
    assert meta_payload["form_type"] == "10-K"
    assert meta_payload["document_type"] == "annual_report"
    assert meta_payload["has_financial_statement"] is False
    assert meta_payload["has_xbrl"] is False
    assert meta_payload["has_financial_data"] is False
    assert meta_payload["search_query_pack_name"] == "annual_quarter_core40"
    assert meta_payload["search_query_pack_version"] == "search_query_pack_v1.0.0"
    assert meta_payload["search_query_count"] == 40
    assert meta_payload["snapshot_schema_version"] == "tool_snapshot_v1.0.0"


@pytest.mark.unit
def test_export_tool_snapshot_meta_marks_financial_capability_and_xbrl(tmp_path: Path) -> None:
    """验证 meta 中财务能力与 XBRL 标记可正确写入。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    repository = FakeRepository(market="US", root=tmp_path)
    processor = FinancialStatementCapableProcessor()
    processor_registry = FakeProcessorRegistry(processor)
    output_dir = tmp_path / "portfolio" / "V" / "processed" / "fil_001"
    processed_handle = repository.get_processed_handle("V", "fil_001")

    export_tool_snapshot(
        repository=repository,
        processor_registry=processor_registry,
        processed_handle=processed_handle,
        ticker="V",
        document_id="fil_001",
        source_kind=SourceKind.FILING,
        ci=False,
        expected_parser_signature="fake_parser_v1",
        source_meta={
            "form_type": "10-K",
            "document_version": "v1",
            "source_fingerprint": "fp_v1",
        },
    )

    meta_payload = json.loads((output_dir / "tool_snapshot_meta.json").read_text(encoding="utf-8"))
    assert meta_payload["form_type"] == "10-K"
    assert meta_payload["document_type"] == "annual_report"
    assert meta_payload["has_financial_statement"] is True
    assert meta_payload["has_xbrl"] is True
    assert meta_payload["financial_statement_availability"] == "structured_data_available"
    assert meta_payload["has_structured_financial_statements"] is True
    assert meta_payload["has_financial_statement_sections"] is True
    assert meta_payload["has_financial_data"] is True
    assert meta_payload["snapshot_schema_version"] == "tool_snapshot_v1.0.0"


@pytest.mark.unit
def test_export_tool_snapshot_meta_marks_extracted_financial_capability_without_xbrl(tmp_path: Path) -> None:
    """验证 extracted 财务报表能力会写入 has_financial_statement 且不误标 has_xbrl。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    repository = FakeRepository(market="US", root=tmp_path)
    processor = ExtractedFinancialStatementCapableProcessor()
    processor_registry = FakeProcessorRegistry(processor)
    output_dir = tmp_path / "portfolio" / "FUTU" / "processed" / "fil_001"
    processed_handle = repository.get_processed_handle("FUTU", "fil_001")

    export_tool_snapshot(
        repository=repository,
        processor_registry=processor_registry,
        processed_handle=processed_handle,
        ticker="FUTU",
        document_id="fil_001",
        source_kind=SourceKind.FILING,
        ci=False,
        expected_parser_signature="fake_parser_v1",
        source_meta={
            "form_type": "6-K",
            "document_version": "v1",
            "source_fingerprint": "fp_v1",
        },
    )

    meta_payload = json.loads((output_dir / "tool_snapshot_meta.json").read_text(encoding="utf-8"))
    assert meta_payload["form_type"] == "6-K"
    assert meta_payload["has_financial_statement"] is True
    assert meta_payload["has_xbrl"] is False
    assert meta_payload["financial_statement_availability"] == "structured_data_available"
    assert meta_payload["has_structured_financial_statements"] is True
    assert meta_payload["has_financial_statement_sections"] is True
    assert meta_payload["has_financial_data"] is True


@pytest.mark.unit
def test_export_tool_snapshot_honors_cancel_checker_before_work(tmp_path: Path) -> None:
    """验证工具快照导出会在开始前响应取消请求。"""

    repository = FakeRepository(market="US", root=tmp_path)
    processor = BasicProcessorWithoutExtendedCapabilities()
    processor_registry = FakeProcessorRegistry(processor)
    processed_handle = repository.get_processed_handle("V", "fil_001")
    output_dir = tmp_path / "portfolio" / "V" / "processed" / "fil_001"

    with pytest.raises(CancelledError, match="操作已被取消"):
        export_tool_snapshot(
            repository=repository,
            processor_registry=processor_registry,
            processed_handle=processed_handle,
            ticker="V",
            document_id="fil_001",
            source_kind=SourceKind.FILING,
            ci=False,
            expected_parser_signature="fake_parser_v1",
            source_meta={
                "form_type": "10-K",
                "document_version": "v1",
                "source_fingerprint": "fp_v1",
            },
            cancel_checker=lambda: True,
        )

    assert not output_dir.exists()


@pytest.mark.unit
def test_export_tool_snapshot_honors_cancel_checker_during_write_phase(tmp_path: Path) -> None:
    """验证工具快照导出会在写文件阶段边界响应取消请求。"""

    repository = FakeRepository(market="US", root=tmp_path)
    processor = BasicProcessorWithoutExtendedCapabilities()
    processor_registry = FakeProcessorRegistry(processor)
    processed_handle = repository.get_processed_handle("V", "fil_001")
    output_dir = tmp_path / "portfolio" / "V" / "processed" / "fil_001"
    state = {"count": 0}

    def _cancel_checker() -> bool:
        """在第 5 次检查时触发取消。"""

        state["count"] += 1
        return state["count"] >= 5

    with pytest.raises(CancelledError, match="操作已被取消"):
        export_tool_snapshot(
            repository=repository,
            processor_registry=processor_registry,
            processed_handle=processed_handle,
            ticker="V",
            document_id="fil_001",
            source_kind=SourceKind.FILING,
            ci=False,
            expected_parser_signature="fake_parser_v1",
            source_meta={
                "form_type": "10-K",
                "document_version": "v1",
                "source_fingerprint": "fp_v1",
            },
            cancel_checker=_cancel_checker,
        )

    assert (output_dir / "tool_snapshot_list_documents.json").exists()
    assert not (output_dir / "tool_snapshot_meta.json").exists()
