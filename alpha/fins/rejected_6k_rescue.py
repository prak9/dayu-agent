"""6-K rejected artifact 本地救回工具。

该模块用于在不重新触发 SEC download 的前提下，基于当前 `_classify_6k_text()`
规则重新审视 `.rejections/` 中的 `6-K` artifact，并把应当保留的样本通过仓储
回灌到 active filings。

关键约束：
- 只通过 `alpha.fins.storage` 下的仓储协议读写 source 与 rejected artifact。
- 不直接搬运 `portfolio/` 目录，不手改 manifest。
- 仅清理 `_download_rejections.json` 中对应 `document_id` 的 skip 记录；当前
  维护治理协议未暴露删除 `.rejections/` artifact 的 public API，因此原 artifact
  会保留为审计痕迹。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Literal, Optional

from alpha.fins.domain.document_models import (
    DocumentMeta,
    FileObjectMeta,
    RejectedFilingArtifact,
    SourceDocumentUpsertRequest,
    SourceFileEntry,
    SourceHandle,
)
from alpha.fins.domain.enums import SourceKind
from alpha.fins.pipelines.sec_6k_rules import _classify_6k_text, _extract_head_text
from alpha.fins.pipelines.sec_pipeline import SEC_PIPELINE_DOWNLOAD_VERSION
from alpha.fins.storage import (
    CompanyMetaRepositoryProtocol,
    DocumentBlobRepositoryProtocol,
    FilingMaintenanceRepositoryProtocol,
    FsCompanyMetaRepository,
    FsDocumentBlobRepository,
    FsFilingMaintenanceRepository,
    FsSourceDocumentRepository,
    SourceDocumentRepositoryProtocol,
)

_RESCUABLE_6K_CLASSIFICATIONS = frozenset({"RESULTS_RELEASE", "IFRS_RECON"})


@dataclass(frozen=True, slots=True)
class Rejected6KRescueCandidate:
    """待救回的 rejected 6-K 候选。"""

    ticker: str
    document_id: str
    current_classification: str
    rejection_category: str
    classification_version: str
    selected_primary_document: str


@dataclass(frozen=True, slots=True)
class Rejected6KRescueOutcome:
    """单个候选的救回结果。"""

    ticker: str
    document_id: str
    action: Literal["rescued", "skipped"]
    reason: str
    current_classification: str


@dataclass(frozen=True, slots=True)
class Rejected6KRescueReport:
    """rejected 6-K 本地救回报告。"""

    workspace_root: str
    apply: bool
    candidates: list[Rejected6KRescueCandidate] = field(default_factory=list)
    outcomes: list[Rejected6KRescueOutcome] = field(default_factory=list)


def rescue_rejected_6k_filings(
    *,
    workspace_root: Path,
    apply: bool,
    target_tickers: Optional[list[str]] = None,
    target_document_ids: Optional[list[str]] = None,
    company_repository: Optional[CompanyMetaRepositoryProtocol] = None,
    source_repository: Optional[SourceDocumentRepositoryProtocol] = None,
    blob_repository: Optional[DocumentBlobRepositoryProtocol] = None,
    maintenance_repository: Optional[FilingMaintenanceRepositoryProtocol] = None,
) -> Rejected6KRescueReport:
    """基于当前 6-K 分类规则救回 `.rejections/` 中应保留的 6-K。

    Args:
        workspace_root: workspace 根目录。
        apply: 是否实际写回 active filings；`False` 时只做 dry-run。
        target_tickers: 可选 ticker 子集；为空时扫描全部公司目录。
        target_document_ids: 可选 document_id 子集。
        company_repository: 可选公司仓储，便于测试注入。
        source_repository: 可选 source 仓储，便于测试注入。
        blob_repository: 可选 blob 仓储，便于测试注入。
        maintenance_repository: 可选 filing maintenance 仓储，便于测试注入。

    Returns:
        救回报告。

    Raises:
        OSError: 仓储读写失败时抛出。
        ValueError: 元数据内容非法时抛出。
    """

    resolved_workspace_root = workspace_root.resolve()
    normalized_target_tickers = _normalize_targets(target_tickers, uppercase=True)
    normalized_document_ids = _normalize_targets(target_document_ids, uppercase=False)
    document_id_filter = set(normalized_document_ids or [])

    effective_company_repository = company_repository or FsCompanyMetaRepository(resolved_workspace_root)
    effective_source_repository = source_repository or FsSourceDocumentRepository(resolved_workspace_root)
    effective_blob_repository = blob_repository or FsDocumentBlobRepository(resolved_workspace_root)
    effective_maintenance_repository = maintenance_repository or FsFilingMaintenanceRepository(
        resolved_workspace_root
    )

    tickers = _resolve_target_tickers(
        company_repository=effective_company_repository,
        target_tickers=normalized_target_tickers,
    )

    candidates: list[Rejected6KRescueCandidate] = []
    outcomes: list[Rejected6KRescueOutcome] = []
    for ticker in tickers:
        rejection_registry = effective_maintenance_repository.load_download_rejection_registry(ticker)
        registry_changed = False
        for artifact in effective_maintenance_repository.list_rejected_filing_artifacts(ticker):
            if not _should_consider_artifact(artifact, document_id_filter=document_id_filter):
                continue
            current_classification = _classify_rejected_filing_artifact(
                maintenance_repository=effective_maintenance_repository,
                artifact=artifact,
            )
            if current_classification not in _RESCUABLE_6K_CLASSIFICATIONS:
                continue
            candidates.append(
                Rejected6KRescueCandidate(
                    ticker=ticker,
                    document_id=artifact.document_id,
                    current_classification=current_classification,
                    rejection_category=artifact.rejection_category,
                    classification_version=artifact.classification_version,
                    selected_primary_document=_resolve_selected_primary_document(artifact),
                )
            )

            existing_meta = _get_source_meta_if_present(
                source_repository=effective_source_repository,
                ticker=ticker,
                document_id=artifact.document_id,
            )
            if existing_meta is not None and not bool(existing_meta.get("is_deleted", False)):
                outcomes.append(
                    Rejected6KRescueOutcome(
                        ticker=ticker,
                        document_id=artifact.document_id,
                        action="skipped",
                        reason="already_active",
                        current_classification=current_classification,
                    )
                )
                continue
            if not apply:
                outcomes.append(
                    Rejected6KRescueOutcome(
                        ticker=ticker,
                        document_id=artifact.document_id,
                        action="skipped",
                        reason="dry_run",
                        current_classification=current_classification,
                    )
                )
                continue

            _restore_rejected_filing_artifact(
                source_repository=effective_source_repository,
                blob_repository=effective_blob_repository,
                maintenance_repository=effective_maintenance_repository,
                artifact=artifact,
                existing_meta=existing_meta,
            )
            if artifact.document_id in rejection_registry:
                rejection_registry.pop(artifact.document_id, None)
                registry_changed = True
            outcomes.append(
                Rejected6KRescueOutcome(
                    ticker=ticker,
                    document_id=artifact.document_id,
                    action="rescued",
                    reason="restored_from_rejections",
                    current_classification=current_classification,
                )
            )

        if apply and registry_changed:
            effective_maintenance_repository.save_download_rejection_registry(ticker, rejection_registry)

    return Rejected6KRescueReport(
        workspace_root=str(resolved_workspace_root),
        apply=apply,
        candidates=candidates,
        outcomes=outcomes,
    )


def _normalize_targets(raw_items: Optional[list[str]], *, uppercase: bool) -> Optional[list[str]]:
    """规范化可选目标列表。

    Args:
        raw_items: 原始目标列表。
        uppercase: 是否将元素统一转换为大写。

    Returns:
        去空、去重后的目标列表；若结果为空则返回 `None`。

    Raises:
        无。
    """

    if raw_items is None:
        return None
    normalized: list[str] = []
    for item in raw_items:
        cleaned = str(item).strip()
        if not cleaned:
            continue
        if uppercase:
            cleaned = cleaned.upper()
        if cleaned in normalized:
            continue
        normalized.append(cleaned)
    return normalized or None


def _resolve_target_tickers(
    *,
    company_repository: CompanyMetaRepositoryProtocol,
    target_tickers: Optional[list[str]],
) -> list[str]:
    """解析本次需要扫描的 ticker 列表。

    Args:
        company_repository: 公司元数据仓储。
        target_tickers: 显式指定的 ticker 子集。

    Returns:
        本次需要扫描的规范 ticker 列表。

    Raises:
        OSError: 扫描公司元数据失败时抛出。
        ValueError: 公司元数据非法时抛出。
    """

    if target_tickers is not None:
        return list(target_tickers)
    tickers: list[str] = []
    for entry in company_repository.scan_company_meta_inventory():
        if entry.status != "available" or entry.company_meta is None:
            continue
        ticker = entry.company_meta.ticker.strip().upper()
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def _should_consider_artifact(
    artifact: RejectedFilingArtifact,
    *,
    document_id_filter: set[str],
) -> bool:
    """判断 rejected artifact 是否属于本次救回候选。

    Args:
        artifact: rejected filing artifact。
        document_id_filter: 可选 document_id 过滤集合。

    Returns:
        若该 artifact 需要参与本次 rescue 判定则返回 `True`。

    Raises:
        无。
    """

    if artifact.form_type.strip().upper() != "6-K":
        return False
    if artifact.rejection_reason != "6k_filtered":
        return False
    if document_id_filter and artifact.document_id not in document_id_filter:
        return False
    return True


def _classify_rejected_filing_artifact(
    *,
    maintenance_repository: FilingMaintenanceRepositoryProtocol,
    artifact: RejectedFilingArtifact,
) -> str:
    """读取 rejected artifact 主文件头部并重新分类。

    Args:
        maintenance_repository: filing maintenance 仓储。
        artifact: rejected filing artifact。

    Returns:
        当前规则下的 6-K 分类结果。

    Raises:
        FileNotFoundError: 主分类文件不存在时抛出。
        OSError: 文件读取失败时抛出。
    """

    payload = _read_rejected_primary_payload(
        maintenance_repository=maintenance_repository,
        artifact=artifact,
    )
    head_text = _extract_head_text(payload, max_lines=120)
    return _classify_6k_text(head_text)


def _read_rejected_primary_payload(
    *,
    maintenance_repository: FilingMaintenanceRepositoryProtocol,
    artifact: RejectedFilingArtifact,
) -> bytes:
    """读取 rejected artifact 的主分类文件字节内容。

    Args:
        maintenance_repository: filing maintenance 仓储。
        artifact: rejected filing artifact。

    Returns:
        主分类文件字节内容。

    Raises:
        FileNotFoundError: selected primary 与 primary 文件都缺失时抛出。
        OSError: 文件读取失败时抛出。
    """

    candidate_names = [_resolve_selected_primary_document(artifact), artifact.primary_document]
    for filename in candidate_names:
        normalized_filename = str(filename).strip()
        if not normalized_filename:
            continue
        try:
            return maintenance_repository.read_rejected_filing_file_bytes(
                artifact.ticker,
                artifact.document_id,
                normalized_filename,
            )
        except FileNotFoundError:
            continue
    raise FileNotFoundError(
        f"ticker={artifact.ticker} document_id={artifact.document_id} 缺少可读取的主分类文件"
    )


def _resolve_selected_primary_document(artifact: RejectedFilingArtifact) -> str:
    """返回 rescue 时应使用的主文件名。

    Args:
        artifact: rejected filing artifact。

    Returns:
        优先使用 `selected_primary_document`，为空时回退到 `primary_document`。

    Raises:
        无。
    """

    selected = str(artifact.selected_primary_document).strip()
    if selected:
        return selected
    return str(artifact.primary_document).strip()


def _get_source_meta_if_present(
    *,
    source_repository: SourceDocumentRepositoryProtocol,
    ticker: str,
    document_id: str,
) -> Optional[DocumentMeta]:
    """安全读取 active source meta。

    Args:
        source_repository: source 仓储。
        ticker: 股票代码。
        document_id: 文档 ID。

    Returns:
        命中时返回 source meta；若 active source 不存在则返回 `None`。

    Raises:
        OSError: 仓储读取失败时抛出。
        ValueError: 元数据非法时抛出。
    """

    try:
        return source_repository.get_source_meta(ticker, document_id, SourceKind.FILING)
    except FileNotFoundError:
        return None


def _restore_rejected_filing_artifact(
    *,
    source_repository: SourceDocumentRepositoryProtocol,
    blob_repository: DocumentBlobRepositoryProtocol,
    maintenance_repository: FilingMaintenanceRepositoryProtocol,
    artifact: RejectedFilingArtifact,
    existing_meta: Optional[DocumentMeta],
) -> None:
    """通过仓储把 rejected filing 回灌到 active filings。

    Args:
        source_repository: source 仓储。
        blob_repository: blob 仓储。
        maintenance_repository: filing maintenance 仓储。
        artifact: rejected filing artifact。
        existing_meta: 现有 active source meta；不存在时为 `None`。

    Returns:
        无。

    Raises:
        OSError: 仓储写入失败时抛出。
        ValueError: 元数据非法时抛出。
    """

    primary_document = _resolve_selected_primary_document(artifact)
    meta_payload = _build_rescued_source_meta(artifact=artifact, existing_meta=existing_meta)
    handle = SourceHandle(
        ticker=artifact.ticker,
        document_id=artifact.document_id,
        source_kind=SourceKind.FILING.value,
    )
    restored_entries = _copy_rejected_files_to_active_source(
        blob_repository=blob_repository,
        maintenance_repository=maintenance_repository,
        artifact=artifact,
        active_handle=handle,
    )
    request = SourceDocumentUpsertRequest(
        ticker=artifact.ticker,
        document_id=artifact.document_id,
        internal_document_id=artifact.internal_document_id,
        form_type=artifact.form_type,
        primary_document=primary_document,
        meta=meta_payload,
        file_entries=[entry.to_dict() for entry in restored_entries],
    )
    _write_rescued_source_document(
        source_repository=source_repository,
        request=request,
        existing_meta=existing_meta,
    )


def _write_rescued_source_document(
    *,
    source_repository: SourceDocumentRepositoryProtocol,
    request: SourceDocumentUpsertRequest,
    existing_meta: Optional[DocumentMeta],
) -> None:
    """把救回后的 source 文档写回 active filings。

    rescue 阶段偶尔会遇到“逻辑上存在 deleted meta，但实际 active 目录里的
    ``meta.json`` 已缺失”的半残状态。此时直接走 update 会因为底层文件不存在而
    失败；更稳妥的处理是回退到 create，让救回流程以 rejected artifact 为真源
    重建 active source。

    Args:
        source_repository: source 仓储。
        request: 待写入的 source upsert 请求。
        existing_meta: 当前 active source meta；不存在时为 ``None``。

    Returns:
        无。

    Raises:
        OSError: 仓储写入失败时抛出。
        ValueError: 元数据非法时抛出。
    """

    if existing_meta is None:
        source_repository.create_source_document(request, SourceKind.FILING)
        return
    try:
        source_repository.update_source_document(request, SourceKind.FILING)
    except FileNotFoundError:
        # deleted meta 可能来自旧 manifest / 半残状态；若 active 文件实体缺失，
        # 直接按 create 重建才是与 rejected artifact 同源的一致恢复路径。
        source_repository.create_source_document(request, SourceKind.FILING)


def _build_rescued_source_meta(
    *,
    artifact: RejectedFilingArtifact,
    existing_meta: Optional[DocumentMeta],
) -> DocumentMeta:
    """构建救回后应写入 active source 的 meta。

    Args:
        artifact: rejected filing artifact。
        existing_meta: 现有 active source meta；不存在时为 `None`。

    Returns:
        用于写回 source 仓储的 meta 字典。

    Raises:
        无。
    """

    preserved_created_at = None if existing_meta is None else existing_meta.get("created_at")
    preserved_first_ingested_at = None if existing_meta is None else existing_meta.get("first_ingested_at")
    preserved_document_version = None if existing_meta is None else existing_meta.get("document_version")
    return {
        "document_id": artifact.document_id,
        "internal_document_id": artifact.internal_document_id,
        "accession_number": artifact.accession_number,
        "company_id": artifact.company_id,
        "form_type": artifact.form_type,
        "fiscal_year": artifact.fiscal_year,
        "fiscal_period": artifact.fiscal_period,
        "report_kind": artifact.report_kind,
        "report_date": artifact.report_date,
        "filing_date": artifact.filing_date,
        "ingest_method": artifact.ingest_method,
        "ingest_complete": True,
        "is_deleted": False,
        "deleted_at": None,
        "document_version": str(preserved_document_version or "v1"),
        "source_fingerprint": artifact.source_fingerprint,
        "amended": artifact.amended,
        "has_xbrl": artifact.has_xbrl,
        "download_version": SEC_PIPELINE_DOWNLOAD_VERSION,
        "created_at": str(preserved_created_at or artifact.created_at),
        "first_ingested_at": str(preserved_first_ingested_at or artifact.created_at),
    }


def _copy_rejected_files_to_active_source(
    *,
    blob_repository: DocumentBlobRepositoryProtocol,
    maintenance_repository: FilingMaintenanceRepositoryProtocol,
    artifact: RejectedFilingArtifact,
    active_handle: SourceHandle,
) -> list[SourceFileEntry]:
    """把 rejected artifact 的文件复制到 active source 目录。

    Args:
        blob_repository: blob 仓储。
        maintenance_repository: filing maintenance 仓储。
        artifact: rejected filing artifact。
        active_handle: active source 句柄。

    Returns:
        写回后的 source 文件条目列表。

    Raises:
        OSError: 文件复制失败时抛出。
    """

    restored_entries: list[SourceFileEntry] = []
    _remove_stale_active_source_entries(
        blob_repository=blob_repository,
        active_handle=active_handle,
        valid_filenames={entry.name for entry in artifact.files},
    )
    for original_entry in artifact.files:
        payload = maintenance_repository.read_rejected_filing_file_bytes(
            artifact.ticker,
            artifact.document_id,
            original_entry.name,
        )
        stored_file_meta = blob_repository.store_file(
            handle=active_handle,
            filename=original_entry.name,
            data=BytesIO(payload),
            content_type=original_entry.content_type,
        )
        restored_entries.append(
            _build_restored_source_entry(
                original_entry=original_entry,
                stored_file_meta=stored_file_meta,
            )
        )
    return restored_entries


def _remove_stale_active_source_entries(
    *,
    blob_repository: DocumentBlobRepositoryProtocol,
    active_handle: SourceHandle,
    valid_filenames: set[str],
) -> None:
    """删除 active source 中不属于 rejected artifact 的旧文件。

    Args:
        blob_repository: blob 仓储。
        active_handle: active source 句柄。
        valid_filenames: 当前 artifact 允许保留的文件名集合。

    Returns:
        无。

    Raises:
        OSError: 文件删除失败时抛出。
    """

    for entry in blob_repository.list_entries(active_handle):
        if not entry.is_file:
            continue
        if entry.name in valid_filenames:
            continue
        blob_repository.delete_entry(active_handle, entry.name)


def _build_restored_source_entry(
    *,
    original_entry: SourceFileEntry,
    stored_file_meta: FileObjectMeta,
) -> SourceFileEntry:
    """将 rejected artifact 文件条目转换为 active source 文件条目。

    Args:
        original_entry: rejected artifact 中记录的原文件条目。
        stored_file_meta: 文件重新写回 active source 后的对象元数据。

    Returns:
        active source 文件条目。

    Raises:
        无。
    """

    return SourceFileEntry(
        name=original_entry.name,
        uri=stored_file_meta.uri,
        etag=stored_file_meta.etag,
        last_modified=stored_file_meta.last_modified,
        size=stored_file_meta.size,
        content_type=stored_file_meta.content_type,
        sha256=stored_file_meta.sha256,
        source_url=original_entry.source_url,
        http_etag=original_entry.http_etag,
        http_last_modified=original_entry.http_last_modified,
        ingested_at=original_entry.ingested_at,
    )
