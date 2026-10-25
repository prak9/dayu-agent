"""processing_helpers 模块单元测试。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pytest

from alpha.engine.processors.processor_registry import ProcessorRegistry
from alpha.fins.domain.document_models import ProcessedCreateRequest, ProcessedUpdateRequest
from alpha.fins.domain.document_models import DocumentHandle, DocumentMeta, DocumentQuery, DocumentSummary, ProcessedDeleteRequest, ProcessedHandle
from alpha.fins.domain.enums import SourceKind
from alpha.fins.pipelines import processing_helpers as helpers


@dataclass
class _ProcessorWithVersion:
    """带 PARSER_VERSION 的处理器桩。"""

    PARSER_VERSION = "processor_v1"


@dataclass
class _ProcessorWithoutVersion:
    """缺失 PARSER_VERSION 的处理器桩。"""

    PARSER_VERSION = "   "


class _RegistryStub(ProcessorRegistry):
    """处理器注册表桩。"""

    def __init__(self, resolved_cls: Optional[type[Any]]) -> None:
        """初始化注册表桩。

        Args:
            resolved_cls: `resolve` 返回的处理器类。

        Returns:
            无。

        Raises:
            无。
        """

        super().__init__()
        self._resolved_cls = resolved_cls

    def resolve(
        self,
        source: Any,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> Optional[type[Any]]:
        """返回预设处理器类。

        Args:
            source: 来源对象。
            form_type: 表单类型。
            media_type: 媒体类型。

        Returns:
            预设处理器类。

        Raises:
            无。
        """

        del source, form_type, media_type
        return self._resolved_cls


class _SourceStub:
    """source 桩对象。"""

    media_type = "text/html"


class _RepositoryStub:
    """仓储桩。"""

    def __init__(self) -> None:
        """初始化仓储桩。"""

        self.created_request: Optional[ProcessedCreateRequest] = None
        self.updated_request: Optional[ProcessedUpdateRequest] = None

    def create_processed(self, req: ProcessedCreateRequest) -> DocumentHandle:
        """记录 create 请求。

        Args:
            req: 创建请求。

        Returns:
            无。

        Raises:
            无。
        """

        self.created_request = req
        return DocumentHandle(ticker=req.ticker, document_id=req.document_id, form_type=req.form_type)

    def update_processed(self, req: ProcessedUpdateRequest) -> DocumentHandle:
        """记录 update 请求。

        Args:
            req: 更新请求。

        Returns:
            无。

        Raises:
            无。
        """

        self.updated_request = req
        return DocumentHandle(ticker=req.ticker, document_id=req.document_id, form_type=req.form_type)

    def delete_processed(self, req: ProcessedDeleteRequest) -> None:
        """删除 processed 文档（测试桩无操作）。

        Args:
            req: 删除请求。

        Returns:
            无。

        Raises:
            无。
        """

        _ = req

    def get_processed_handle(self, ticker: str, document_id: str) -> ProcessedHandle:
        """返回 processed 句柄。"""

        return ProcessedHandle(ticker=ticker, document_id=document_id)

    def get_processed_meta(self, ticker: str, document_id: str) -> DocumentMeta:
        """返回空 processed 元数据。"""

        _ = (ticker, document_id)
        return {}

    def list_processed_documents(self, ticker: str, query: DocumentQuery) -> list[DocumentSummary]:
        """返回空 processed 摘要列表。"""

        _ = (ticker, query)
        return []

    def clear_processed_documents(self, ticker: str) -> None:
        """清空 processed 文档（测试桩无操作）。"""

        _ = ticker

    def mark_processed_reprocess_required(self, ticker: str, document_id: str, required: bool) -> None:
        """标记是否需要重处理（测试桩无操作）。"""

        _ = (ticker, document_id, required)


@pytest.mark.unit
def test_resolve_parser_version_from_cls_returns_stripped_value() -> None:
    """验证类级 parser version 会被去空白并返回。"""

    class _Processor:
        PARSER_VERSION = "  v2  "

    assert helpers.resolve_parser_version_from_cls(_Processor) == "v2"


@pytest.mark.unit
def test_resolve_parser_version_from_cls_raises_when_missing() -> None:
    """验证缺失 PARSER_VERSION 时抛出异常。"""

    with pytest.raises(RuntimeError, match="PARSER_VERSION"):
        helpers.resolve_parser_version_from_cls(_ProcessorWithoutVersion)


@pytest.mark.unit
def test_resolve_processor_parser_version_from_instance() -> None:
    """验证实例级 parser version 读取。"""

    assert helpers.resolve_processor_parser_version(_ProcessorWithVersion()) == "processor_v1"


@pytest.mark.unit
def test_resolve_expected_parser_version_from_registry() -> None:
    """验证从注册表解析期望 parser version。"""

    registry = _RegistryStub(_ProcessorWithVersion)
    actual = helpers.resolve_expected_parser_version(
        processor_registry=registry, source=_SourceStub(), form_type="10-K"
    )

    assert actual == "processor_v1"


@pytest.mark.unit
def test_resolve_expected_parser_version_raises_when_resolve_none() -> None:
    """验证未命中处理器时抛出异常。"""

    registry = _RegistryStub(None)
    with pytest.raises(RuntimeError, match="未找到可用处理器"):
        helpers.resolve_expected_parser_version(
            processor_registry=registry,
            source=_SourceStub(),
            form_type="10-K",
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "overwrite,processed_meta,source_meta,expected_schema,expected_parser,expected",
    [
        (True, {"schema_version": "v1"}, {"document_version": "v1"}, "v1", "p1", False),
        (False, {}, {"document_version": "v1"}, "v1", "p1", False),
        (False, {"reprocess_required": True}, {"document_version": "v1"}, "v1", "p1", False),
        (
            False,
            {
                "source_document_version": "v1",
                "schema_version": "v1",
                "parser_version": "p1",
                "source_fingerprint": "f2",
            },
            {"document_version": "v1", "source_fingerprint": "f1"},
            "v1",
            "p1",
            False,
        ),
        (
            False,
            {
                "source_document_version": "v1",
                "schema_version": "v1",
                "parser_version": "p1",
                "source_fingerprint": "f1",
            },
            {"document_version": "v1", "source_fingerprint": "f1"},
            "v1",
            "p1",
            True,
        ),
    ],
)
def test_can_skip_processing_branches(
    overwrite: bool,
    processed_meta: dict[str, Any],
    source_meta: dict[str, Any],
    expected_schema: str,
    expected_parser: str,
    expected: bool,
) -> None:
    """验证 can_skip_processing 的主要分支。"""

    actual = helpers.can_skip_processing(
        source_meta=source_meta,
        processed_meta=processed_meta,
        overwrite=overwrite,
        expected_parser_version=expected_parser,
        expected_schema_version=expected_schema,
    )

    assert actual is expected


@pytest.mark.unit
def test_build_processed_payload_uses_defaults_and_fields() -> None:
    """验证 processed payload 组装字段。"""

    payload = helpers.build_processed_payload(
        source_meta={
            "document_version": "v9",
            "source_fingerprint": "abc",
            "form_type": "10-Q",
            "report_date": "2025-03-29",
            "filing_date": "2025-05-02",
            "amended": True,
        },
        section_count=3,
        table_count=2,
        parser_version="parser_v1",
        quality="full",
        has_xbrl=True,
        schema_version="schema_v1",
        fiscal_year=2025,
        fiscal_period="Q1",
    )

    assert payload["form_type"] == "10-Q"
    assert payload["meta"]["source_document_version"] == "v9"
    assert payload["meta"]["parser_version"] == "parser_v1"
    assert payload["meta"]["section_count"] == 3
    assert payload["meta"]["table_count"] == 2
    assert payload["meta"]["amended"] is True


@pytest.mark.unit
def test_upsert_processed_document_create_and_update_paths() -> None:
    """验证 upsert 根据 processed_exists 走 create/update。"""

    repo = _RepositoryStub()
    payload = {"meta": {"schema_version": "v1"}, "form_type": "10-K"}

    helpers.upsert_processed_document(
        repository=repo,
        ticker="AAPL",
        document_id="fil_1",
        source_kind=SourceKind.FILING,
        source_meta={"internal_document_id": "int_1"},
        processed_exists=False,
        processed_payload=payload,
        sections=[{"ref": "sec_1"}],
        tables=[{"table_ref": "tbl_1"}],
        financials={"ok": True},
    )

    assert isinstance(repo.created_request, ProcessedCreateRequest)
    assert repo.created_request is not None
    assert repo.created_request.internal_document_id == "int_1"
    assert repo.created_request.source_kind == "filing"

    helpers.upsert_processed_document(
        repository=repo,
        ticker="AAPL",
        document_id="fil_2",
        source_kind=SourceKind.MATERIAL,
        source_meta={},
        processed_exists=True,
        processed_payload=payload,
        sections=[],
        tables=[],
        financials=None,
    )

    assert isinstance(repo.updated_request, ProcessedUpdateRequest)
    assert repo.updated_request is not None
    assert repo.updated_request.internal_document_id == "fil_2"
    assert repo.updated_request.source_kind == "material"


@pytest.mark.unit
def test_extract_process_identity_fields_prefers_processed_then_source() -> None:
    """验证 process 回显字段优先级。"""

    actual = helpers.extract_process_identity_fields(
        source_meta={"form_type": "10-K", "fiscal_year": 2024},
        processed_meta={"form_type": "10-Q", "fiscal_year": 2025},
    )
    assert actual == {"form_type": "10-Q", "fiscal_year": 2025}

    fallback = helpers.extract_process_identity_fields(
        source_meta={"form_type": "10-K", "fiscal_year": 2024},
        processed_meta={"form_type": "", "fiscal_year": ""},
    )
    assert fallback == {"form_type": "10-K", "fiscal_year": 2024}


@pytest.mark.unit
def test_log_process_document_result_includes_optional_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 process 日志会拼接可选字段。"""

    captured: dict[str, Any] = {}

    def _fake_info(message: str, *, module: str) -> None:
        """记录日志调用。

        Args:
            message: 日志文本。
            module: 模块名。

        Returns:
            无。

        Raises:
            无。
        """

        captured["message"] = message
        captured["module"] = module

    monkeypatch.setattr(helpers.Log, "info", _fake_info)

    helpers.log_process_document_result(
        module="TEST",
        ticker="AAPL",
        source_kind=SourceKind.FILING,
        result={
            "document_id": "fil_1",
            "status": "processed",
            "form_type": "10-K",
            "fiscal_year": 2024,
            "reason": "ok",
            "quality": "full",
            "section_count": 8,
            "table_count": 3,
        },
    )

    assert captured["module"] == "TEST"
    assert "form_type=10-K" in captured["message"]
    assert "fiscal_year=2024" in captured["message"]
    assert "reason=ok" in captured["message"]
    assert "quality=full" in captured["message"]
    assert "section_count=8" in captured["message"]
    assert "table_count=3" in captured["message"]
