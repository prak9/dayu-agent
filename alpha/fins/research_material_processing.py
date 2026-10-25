"""研究财报材料的按需结构处理，原件与产物均经 Fins 仓储协议。"""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from alpha.contracts.cancellation import CancellationToken
from alpha.contracts.research_materials import FinancialMaterialTarget
from alpha.fins.docling_export import convert_pdf_bytes_to_docling_json_bytes
from alpha.fins.domain.document_models import SourceDocumentUpsertRequest, SourceHandle
from alpha.fins.domain.enums import SourceKind
from alpha.fins.storage._fs_repository_factory import build_fs_repository_set
from alpha.fins.storage import BatchingRepositoryProtocol, DocumentBlobRepositoryProtocol, SourceDocumentRepositoryProtocol
from alpha.fins.storage import FsBatchingRepository, FsDocumentBlobRepository, FsSourceDocumentRepository


@dataclass(frozen=True)
class FinsResearchMaterialProcessor:
    """按需生成已有 Fins 章节和表格工具可读的主文档。"""

    _sources: SourceDocumentRepositoryProtocol
    _blobs: DocumentBlobRepositoryProtocol
    _batch: BatchingRepositoryProtocol

    def prepare(self, target: FinancialMaterialTarget, document_id: str, name: str, token: CancellationToken | None) -> str:
        """按需生成 Fins 已支持的 Docling 主文档。参数：目标、文档、原件、令牌。返回：文档 ID。异常：取消或转换/存储错误。"""
        if token is not None:
            token.raise_if_cancelled()
        meta = self._sources.get_source_meta(target.ticker, document_id, SourceKind.MATERIAL)
        if str(meta.get("primary_document", "")).endswith("_docling.json") or not name.lower().endswith(".pdf"):
            return document_id
        raw = self._blobs.read_file_bytes(SourceHandle(target.ticker, document_id, SourceKind.MATERIAL.value), name)
        converted = convert_pdf_bytes_to_docling_json_bytes(raw, name)
        if token is not None:
            token.raise_if_cancelled()
        batch = self._batch.begin_batch(target.ticker)
        try:
            handle = SourceHandle(target.ticker, document_id, SourceKind.MATERIAL.value)
            original = self._blobs.list_files(handle)
            filename = Path(name).stem + "_docling.json"
            artifact = self._blobs.store_file(handle, filename, BytesIO(converted), content_type="application/json")
            self._sources.update_source_document(SourceDocumentUpsertRequest(target.ticker, document_id, document_id,
                form_type=target.form_type, primary_document=filename, files=[*original, artifact]), SourceKind.MATERIAL)
            self._batch.commit_batch(batch)
        except BaseException:
            self._batch.rollback_batch(batch)
            raise
        return document_id


def prepare_financial_material_processor(workspace_root: Path) -> FinsResearchMaterialProcessor:
    """装配财报处理端口。参数：工作区。返回：处理器。异常：仓储初始化错误。"""
    shared = build_fs_repository_set(workspace_root=workspace_root)
    return FinsResearchMaterialProcessor(FsSourceDocumentRepository(workspace_root, repository_set=shared),
        FsDocumentBlobRepository(workspace_root, repository_set=shared), FsBatchingRepository(workspace_root, repository_set=shared))
