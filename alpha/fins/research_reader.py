"""研究使用的财报处理与读取适配；全部文档访问经过 Fins 仓储。"""

import hashlib
import json
import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import cast

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.cancellation import CancellationToken
from alpha.contracts.fins import DownloadCommandPayload, DownloadResultData, FinsCommand, FinsCommandName, FinsEventType, FinsResult, ProcessFilingCommandPayload, ProcessSingleResultData
from alpha.fins.domain.enums import SourceKind
from alpha.fins.service_runtime import DefaultFinsRuntime

_HASH_CHUNK_BYTES = 1024 * 1024
_PROCESSED_STATUS = "processed"
_SKIPPED_STATUS = "skipped"
_MATCHED_VERSION_REASON = "version_matched"

@dataclass(frozen=True)
class FinsResearchReader:
    """直接消费当前 Host 工具调用的取消令牌，不创建脱离父执行的后台 job。"""

    runtime: DefaultFinsRuntime

    def download(self, ticker: str, form_types: tuple[str, ...], start_date: str | None, end_date: str | None,
                 token: CancellationToken | None) -> dict[str, JsonValue]:
        """在父工具调用内消费可取消下载流。参数：公司、表单、日期范围、取消。返回：源文档清单。异常：取消或下载错误。"""
        return asyncio.run(self._download(FinsCommand(FinsCommandName.DOWNLOAD,
            DownloadCommandPayload(ticker, form_type=form_types, start_date=start_date, end_date=end_date), stream=True), token))

    async def _download(self, command: FinsCommand, token: CancellationToken | None) -> dict[str, JsonValue]:
        """消费 Fins 的类型化结果并保证流收尾。参数：固定命令、取消真源。返回：下载结果。异常：取消或缺失结果。"""
        if token is not None:
            token.raise_if_cancelled()
        stream = self.runtime.execute(command, cancel_checker=token.is_cancelled if token is not None else None)
        if not isinstance(stream, AsyncGenerator):
            raise RuntimeError("财报下载未返回流式结果")
        result: DownloadResultData | None = None
        async with aclosing(stream):
            async for event in stream:
                if token is not None:
                    token.raise_if_cancelled()
                if event.type == FinsEventType.RESULT and isinstance(event.payload, DownloadResultData):
                    result = event.payload
        if result is None:
            raise RuntimeError("财报下载没有完整结果")
        return cast(dict[str, JsonValue], asdict(result))

    def prepare(self, ticker: str, document_id: str, token: CancellationToken | None) -> dict[str, JsonValue]:
        """准备选定源文档。参数：公司、文档、取消。返回：处理摘要。异常：取消或处理失败。"""
        if token is not None:
            token.raise_if_cancelled()
        result = self.runtime.execute(FinsCommand(FinsCommandName.PROCESS_FILING, ProcessFilingCommandPayload(ticker, document_id)),
                                      cancel_checker=token.is_cancelled if token is not None else None)
        if not isinstance(result, FinsResult):
            raise RuntimeError("财报同步处理返回了流式结果")
        data = result.data
        if not isinstance(data, ProcessSingleResultData):
            raise RuntimeError("财报同步处理返回了错误结果类型")
        cached = data.status == _SKIPPED_STATUS and data.reason == _MATCHED_VERSION_REASON
        if data.status != _PROCESSED_STATUS and not cached:
            raise RuntimeError(f"财报处理未完成：{data.status} / {data.reason}")
        if token is not None:
            token.raise_if_cancelled()
        return {"ticker": data.ticker, "document_id": data.document_id, "processed": True, "cached": cached}

    def _snapshot(self, ticker: str, document_id: str) -> dict[str, JsonValue]:
        """固定原件和处理产物。参数：公司、文档。返回：内容哈希及元数据。异常：缺失或仓储错误。"""
        processed_meta = cast(dict[str, JsonValue], self.runtime.processed_repository.get_processed_meta(ticker, document_id))
        source_meta = cast(dict[str, JsonValue], self.runtime.source_repository.get_source_meta(ticker, document_id, SourceKind.FILING))
        source = self.runtime.source_repository.get_primary_source(ticker, document_id, SourceKind.FILING)
        processed = self.runtime.processed_repository.get_processed_handle(ticker, document_id)
        files: dict[str, JsonValue] = {}
        for entry in self.runtime.blob_repository.list_entries(processed):
            if entry.is_file:
                files[entry.name] = hashlib.sha256(self.runtime.blob_repository.read_file_bytes(processed, entry.name)).hexdigest()
        with source.open() as stream:
            digest = hashlib.sha256()
            while chunk := stream.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
            primary_source_hash = digest.hexdigest()
        source_handle = self.runtime.source_repository.get_source_handle(ticker, document_id, SourceKind.FILING)
        source_files: dict[str, JsonValue] = {}
        for entry in self.runtime.blob_repository.list_entries(source_handle):
            if entry.is_file:
                source_files[entry.name] = hashlib.sha256(self.runtime.blob_repository.read_file_bytes(source_handle, entry.name)).hexdigest()
        source_hash = hashlib.sha256(json.dumps(source_files, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        processed_hash = hashlib.sha256(json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        return {"source_hash": source_hash, "source_files": source_files, "primary_source_hash": primary_source_hash, "source_meta": source_meta,
                "processed_hash": processed_hash, "processed_files": files, "processed_meta": processed_meta}

    def read(self, ticker: str, document_id: str, *, statement_type: str | None, table_ref: str | None,
             token: CancellationToken | None) -> dict[str, JsonValue]:
        """读取并固定实际工具结果。参数：公司、文档、报表或表格、取消。返回：快照及结果。异常：参数、并发变更或取消。"""
        if (statement_type is None) == (table_ref is None):
            raise ValueError("必须且只能选择 statement_type 或 table_ref")
        if token is not None:
            token.raise_if_cancelled()
        before = self._snapshot(ticker, document_id)
        service = self.runtime.get_tool_service()
        raw = (service.get_financial_statement(ticker=ticker, document_id=document_id, statement_type=statement_type)
               if statement_type is not None else service.get_table(ticker=ticker, document_id=document_id, table_ref=table_ref or ""))
        result = cast(dict[str, JsonValue], raw)
        after = self._snapshot(ticker, document_id)
        if before != after:
            raise RuntimeError("读取期间财报原件或解析产物发生变化，请重试")
        if token is not None:
            token.raise_if_cancelled()
        return {"ticker": ticker, "document_id": document_id, "statement_type": statement_type,
                "table_ref": table_ref, "accessed_at": datetime.now(timezone.utc).isoformat(), "snapshot": before, "result": result}
