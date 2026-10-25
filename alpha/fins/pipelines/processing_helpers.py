"""预处理共享辅助函数。

该模块抽取 `SecPipeline` 与 `CnPipeline` 在预处理阶段的公共逻辑，
避免重复实现版本判定、跳过判定、文档筛选与 processed 落盘流程。
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from alpha.log import Log
from alpha.engine.processors.processor_registry import ProcessorRegistry
from alpha.fins.domain.document_models import (
    ProcessedCreateRequest,
    ProcessedUpdateRequest,
)
from alpha.fins.domain.enums import SourceKind
from alpha.fins.storage import ProcessedDocumentRepositoryProtocol


def resolve_parser_version_from_cls(processor_cls: type[Any]) -> str:
    """从处理器类提取 parser version。

    Args:
        processor_cls: 处理器类。

    Returns:
        parser version 字符串。

    Raises:
        RuntimeError: 处理器未声明有效 `PARSER_VERSION` 时抛出。
    """

    get_parser_version = getattr(processor_cls, "get_parser_version", None)
    if callable(get_parser_version):
        parser_version = get_parser_version()
    else:
        parser_version = getattr(processor_cls, "PARSER_VERSION", None)
    if not isinstance(parser_version, str) or not parser_version.strip():
        raise RuntimeError(
            f"处理器未声明有效 parser version（get_parser_version/PARSER_VERSION）: "
            f"{processor_cls.__module__}.{processor_cls.__name__}"
        )
    return parser_version.strip()


def resolve_processor_parser_version(processor: Any) -> str:
    """从处理器实例提取 parser version。

    Args:
        processor: 处理器实例。

    Returns:
        parser version 字符串。

    Raises:
        RuntimeError: 处理器未声明有效 `PARSER_VERSION` 时抛出。
    """

    return resolve_parser_version_from_cls(processor.__class__)


def resolve_expected_parser_version(
    processor_registry: ProcessorRegistry,
    source: Any,
    form_type: Optional[str],
) -> str:
    """根据当前 source 解析期望 parser version。

    Args:
        processor_registry: 处理器注册表。
        source: 文档来源对象。
        form_type: 可选表单类型。

    Returns:
        期望 parser version 字符串。

    Raises:
        RuntimeError: 未命中可用处理器时抛出。
    """

    processor_cls = processor_registry.resolve(
        source=source,
        form_type=form_type,
        media_type=getattr(source, "media_type", None),
    )
    if processor_cls is None:
        raise RuntimeError("未找到可用处理器，无法解析 parser_version")
    return resolve_parser_version_from_cls(processor_cls)


def can_skip_processing(
    source_meta: dict[str, Any],
    processed_meta: dict[str, Any],
    overwrite: bool,
    expected_parser_version: str,
    expected_schema_version: str,
) -> bool:
    """判断是否可跳过预处理。

    Args:
        source_meta: 源文档 `meta.json`。
        processed_meta: 已有 processed `meta.json`。
        overwrite: 是否强制重处理。
        expected_parser_version: 当前应使用的 parser version。
        expected_schema_version: 当前 schema version。

    Returns:
        满足跳过条件时返回 `True`。

    Raises:
        无。
    """

    # 复杂逻辑说明：跳过判定需要同时比较覆盖标记、版本一致性和重处理标记。
    if overwrite:
        return False
    if not processed_meta:
        return False
    if bool(processed_meta.get("reprocess_required", False)):
        return False
    if str(processed_meta.get("source_document_version", "")) != str(source_meta.get("document_version", "")):
        return False
    if str(processed_meta.get("schema_version", "")) != expected_schema_version:
        return False
    if str(processed_meta.get("parser_version", "")) != expected_parser_version:
        return False

    source_fingerprint = str(source_meta.get("source_fingerprint", ""))
    processed_fingerprint = str(processed_meta.get("source_fingerprint", ""))
    if source_fingerprint != processed_fingerprint:
        return False
    return True


def filter_requested_document_ids(
    document_ids: list[str],
    requested_document_ids: Optional[Sequence[str]],
) -> list[str]:
    """按请求参数筛选待处理文档 ID。

    Args:
        document_ids: 当前 source 目录下的全部文档 ID。
        requested_document_ids: 调用方显式请求处理的文档 ID 列表；为空时表示不过滤。

    Returns:
        保留原始顺序后的筛选结果列表。

    Raises:
        无。
    """

    if requested_document_ids is None:
        return list(document_ids)
    normalized_requested_ids = {
        str(document_id).strip()
        for document_id in requested_document_ids
        if str(document_id).strip()
    }
    if not normalized_requested_ids:
        return list(document_ids)
    return [document_id for document_id in document_ids if document_id in normalized_requested_ids]


def build_processed_payload(
    *,
    source_meta: dict[str, Any],
    section_count: int,
    table_count: int,
    parser_version: str,
    quality: str,
    has_xbrl: bool,
    schema_version: str,
    fiscal_year: Optional[int] = None,
    fiscal_period: Optional[str] = None,
) -> dict[str, Any]:
    """构建 processed 请求载荷。

    Args:
        source_meta: 源文档 meta。
        section_count: 章节数量。
        table_count: 表格数量。
        parser_version: 实际处理器版本。
        quality: 处理质量（`full/partial/fallback`）。
        has_xbrl: 是否包含 XBRL 财务数据。
        schema_version: 处理 schema 版本。
        fiscal_year: 可选财年。
        fiscal_period: 可选财期。

    Returns:
        供 `create_processed/update_processed` 使用的载荷字典。

    Raises:
        无。
    """

    meta_payload = {
        "source_document_version": str(source_meta.get("document_version", "v1")),
        "schema_version": schema_version,
        "parser_version": parser_version,
        "source_fingerprint": str(source_meta.get("source_fingerprint", "")),
        "reprocess_required": False,
        "form_type": source_meta.get("form_type"),
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "report_date": source_meta.get("report_date"),
        "filing_date": source_meta.get("filing_date"),
        "amended": bool(source_meta.get("amended", False)),
        "quality": quality,
        "section_count": section_count,
        "table_count": table_count,
        "has_xbrl": has_xbrl,
    }
    return {
        "meta": meta_payload,
        "form_type": source_meta.get("form_type"),
    }


def upsert_processed_document(
    *,
    repository: ProcessedDocumentRepositoryProtocol,
    ticker: str,
    document_id: str,
    source_kind: SourceKind,
    source_meta: dict[str, Any],
    processed_exists: bool,
    processed_payload: dict[str, Any],
    sections: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    financials: Optional[dict[str, Any]] = None,
) -> None:
    """创建或更新 processed 文档。

    Args:
        repository: processed 文档仓储。
        ticker: 股票代码。
        document_id: 文档 ID。
        source_kind: 来源类型（filing/material）。
        source_meta: 源文档元数据。
        processed_exists: processed 是否已存在。
        processed_payload: 处理后 meta/form_type 载荷。
        sections: 章节摘要列表。
        tables: 表格摘要列表。
        financials: 可选财务结果。

    Returns:
        无。

    Raises:
        OSError: 仓储写入失败时抛出。
    """

    internal_document_id = str(source_meta.get("internal_document_id") or document_id)
    if processed_exists:
        request = ProcessedUpdateRequest(
            ticker=ticker,
            document_id=document_id,
            internal_document_id=internal_document_id,
            source_kind=source_kind.value,
            form_type=processed_payload["form_type"],
            meta=processed_payload["meta"],
            sections=sections,
            tables=tables,
            financials=financials,
        )
        repository.update_processed(request)
        return
    request = ProcessedCreateRequest(
        ticker=ticker,
        document_id=document_id,
        internal_document_id=internal_document_id,
        source_kind=source_kind.value,
        form_type=processed_payload["form_type"],
        meta=processed_payload["meta"],
        sections=sections,
        tables=tables,
        financials=financials,
    )
    repository.create_processed(request)


def register_processed_snapshot_document(
    *,
    repository: ProcessedDocumentRepositoryProtocol,
    ticker: str,
    document_id: str,
    source_kind: SourceKind,
    source_meta: dict[str, Any],
    parser_signature: str,
    has_xbrl: bool,
) -> None:
    """把已落盘 snapshot 显式登记到 processed 仓储。

    `process/process_filing/process_material` 会先把 `tool_snapshot_*.json`
    直接写入 `processed/{document_id}`。如果不再显式回写一次
    `update_processed()`，则 `processed/manifest.json` 不会同步更新，后续
    只能读到目录下的 `tool_snapshot_meta.json`，却无法通过
    `list_processed_documents()` 发现文档。

    Args:
        repository: processed 文档仓储。
        ticker: 股票代码。
        document_id: 文档 ID。
        source_kind: 来源类型。
        source_meta: 源文档元数据。
        parser_signature: 当前解析器签名。
        has_xbrl: 当前 snapshot 是否包含 XBRL 财务能力。

    Returns:
        无。

    Raises:
        FileNotFoundError: `processed/{document_id}` 尚不存在时抛出。
        OSError: 仓储写入失败时抛出。
    """

    internal_document_id = str(source_meta.get("internal_document_id") or document_id)
    request = ProcessedUpdateRequest(
        ticker=ticker,
        document_id=document_id,
        internal_document_id=internal_document_id,
        source_kind=source_kind.value,
        form_type=source_meta.get("form_type"),
        meta={
            "form_type": source_meta.get("form_type"),
            "fiscal_year": source_meta.get("fiscal_year"),
            "fiscal_period": source_meta.get("fiscal_period"),
            "report_date": source_meta.get("report_date"),
            "filing_date": source_meta.get("filing_date"),
            "amended": bool(source_meta.get("amended", False)),
            "source_document_version": str(source_meta.get("document_version", "v1")),
            "source_fingerprint": str(source_meta.get("source_fingerprint", "")),
            "parser_version": parser_signature,
        },
        sections=None,
        tables=None,
        financials={"snapshot_registered": True} if has_xbrl else None,
    )
    repository.update_processed(request)


def extract_process_identity_fields(
    *,
    source_meta: Optional[dict[str, Any]] = None,
    processed_meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """提取 process 回显常用身份字段。

    Args:
        source_meta: 源文档元数据。
        processed_meta: processed 元数据。

    Returns:
        包含可用 `form_type/fiscal_year` 的字典；无可用字段时返回空字典。

    Raises:
        无。
    """

    result: dict[str, Any] = {}
    resolved_form_type: Optional[str] = None
    resolved_fiscal_year: Optional[Any] = None

    if processed_meta is not None:
        processed_form_type = str(processed_meta.get("form_type", "")).strip()
        if processed_form_type:
            resolved_form_type = processed_form_type
        processed_fiscal_year = processed_meta.get("fiscal_year")
        if processed_fiscal_year not in (None, ""):
            resolved_fiscal_year = processed_fiscal_year

    if source_meta is not None:
        source_form_type = str(source_meta.get("form_type", "")).strip()
        if resolved_form_type is None and source_form_type:
            resolved_form_type = source_form_type
        source_fiscal_year = source_meta.get("fiscal_year")
        if resolved_fiscal_year in (None, "") and source_fiscal_year not in (None, ""):
            resolved_fiscal_year = source_fiscal_year

    if resolved_form_type is not None:
        result["form_type"] = resolved_form_type
    if resolved_fiscal_year not in (None, ""):
        result["fiscal_year"] = resolved_fiscal_year
    return result


def log_process_document_result(
    *,
    module: str,
    ticker: str,
    source_kind: SourceKind,
    result: dict[str, Any],
) -> None:
    """输出单文档处理进度日志。

    Args:
        module: 日志模块名。
        ticker: 股票代码。
        source_kind: 文档来源类型。
        result: 单文档处理结果字典。

    Returns:
        无。

    Raises:
        无。
    """

    document_id = str(result.get("document_id", "")).strip() or "-"
    status = str(result.get("status", "")).strip() or "unknown"
    reason = result.get("reason")
    form_type = result.get("form_type")
    fiscal_year = result.get("fiscal_year")
    quality = result.get("quality")
    section_count = result.get("section_count")
    table_count = result.get("table_count")

    optional_parts: list[str] = []
    if form_type not in (None, ""):
        optional_parts.append(f"form_type={form_type}")
    if fiscal_year not in (None, ""):
        optional_parts.append(f"fiscal_year={fiscal_year}")
    if reason not in (None, ""):
        optional_parts.append(f"reason={reason}")
    if quality not in (None, ""):
        optional_parts.append(f"quality={quality}")
    if section_count not in (None, ""):
        optional_parts.append(f"section_count={section_count}")
    if table_count not in (None, ""):
        optional_parts.append(f"table_count={table_count}")

    suffix = f" {' '.join(optional_parts)}" if optional_parts else ""
    Log.info(
        (
            "process进度: "
            f"ticker={ticker} source_kind={source_kind.value} "
            f"document_id={document_id} status={status}{suffix}"
        ),
        module=module,
    )
