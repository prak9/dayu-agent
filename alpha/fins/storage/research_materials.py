"""研究渠道上传财报的 Fins 源文档仓储适配，不绕开财报文件存取协议。"""

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from alpha.contracts.research_materials import FinancialMaterialTarget
from alpha.fins.domain.document_models import SourceDocumentUpsertRequest, SourceHandle
from alpha.fins.domain.enums import SourceKind
from alpha.fins.storage._fs_repository_factory import build_fs_repository_set
from alpha.fins.storage.fs_batching_repository import FsBatchingRepository
from alpha.fins.storage.fs_document_blob_repository import FsDocumentBlobRepository
from alpha.fins.storage.fs_source_document_repository import FsSourceDocumentRepository


class FsFinancialMaterialBlobs:
    """以内容身份保存未核验财报材料；Fins 工具继续负责结构处理。"""

    def __init__(self, workspace_root: Path) -> None:
        """装配同一批处理上下文。参数：工作区。返回：无。异常：仓储初始化错误。"""
        shared = build_fs_repository_set(workspace_root=workspace_root)
        self._batch = FsBatchingRepository(workspace_root, repository_set=shared)
        self._sources = FsSourceDocumentRepository(workspace_root, repository_set=shared)
        self._blobs = FsDocumentBlobRepository(workspace_root, repository_set=shared)

    def put(self, target: FinancialMaterialTarget, document_id: str, name: str, content: bytes) -> str:
        """事务保存稳定财报材料。参数：目标、文档、文件名、内容。返回：引用。异常：同身份不同字节或存储错误。"""
        batch = self._batch.begin_batch(target.ticker)
        handle = SourceHandle(target.ticker, document_id, SourceKind.MATERIAL.value)
        try:
            try:
                existing = self._sources.get_source_meta(target.ticker, document_id, SourceKind.MATERIAL)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if self._blobs.read_file_bytes(handle, name) != content:
                    raise ValueError("财报材料身份冲突")
            else:
                request = SourceDocumentUpsertRequest(target.ticker, document_id, document_id, form_type=target.form_type,
                    meta={"material_name": name, "source_fingerprint": sha256(content).hexdigest(), "ingest_complete": True})
                self._sources.create_source_document(request, SourceKind.MATERIAL)
                file = self._blobs.store_file(handle, name, BytesIO(content))
                self._sources.update_source_document(replace(request, primary_document=name, files=[file]), SourceKind.MATERIAL)
            self._batch.commit_batch(batch)
        except BaseException:
            self._batch.rollback_batch(batch)
            raise
        return f"fins://{target.ticker}/materials/{document_id}/{name}"

    def read(self, target: FinancialMaterialTarget, document_id: str, name: str) -> bytes:
        """从 Fins 读取原文件。参数：目标、文档、名称。返回：字节。异常：不存在或仓储错误。"""
        return self._blobs.read_file_bytes(SourceHandle(target.ticker, document_id, SourceKind.MATERIAL.value), name)
