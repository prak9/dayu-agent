"""`sec_safe_meta_access` 真源模块测试。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, cast

import pytest

from alpha.fins.domain.document_models import CompanyMeta
from alpha.fins.domain.enums import SourceKind
from alpha.fins.pipelines import sec_safe_meta_access
from alpha.fins.storage import (
    CompanyMetaRepositoryProtocol,
    ProcessedDocumentRepositoryProtocol,
    SourceDocumentRepositoryProtocol,
)


class _SpyCompanyRepository:
    """公司仓储桩。"""

    def __init__(self, meta: Optional[CompanyMeta]) -> None:
        """初始化仓储桩。"""

        self.meta = meta

    def get_company_meta(self, ticker: str) -> CompanyMeta:
        """按 ticker 返回公司元数据。"""

        if self.meta is None:
            raise FileNotFoundError(ticker)
        return self.meta


class _SpySourceRepository:
    """source 仓储桩。"""

    def __init__(
        self,
        *,
        source_meta: Optional[dict[str, object]] = None,
        source_error: Optional[type[Exception]] = None,
    ) -> None:
        """初始化 source 仓储桩。"""

        self.source_meta = source_meta
        self.source_error = source_error

    def get_source_meta(
        self,
        ticker: str,
        document_id: str,
        source_kind: SourceKind,
    ) -> dict[str, object]:
        """按需返回 source meta 或抛出异常。"""

        del ticker, document_id, source_kind
        if self.source_error is not None:
            raise self.source_error("boom")
        if self.source_meta is None:
            raise FileNotFoundError("missing")
        return self.source_meta


class _SpyProcessedRepository:
    """processed 仓储桩。"""

    def __init__(self, meta: Optional[dict[str, object]]) -> None:
        """初始化 processed 仓储桩。"""

        self.meta = meta

    def get_processed_meta(self, ticker: str, document_id: str) -> dict[str, object]:
        """按需返回 processed meta。"""

        del ticker, document_id
        if self.meta is None:
            raise FileNotFoundError("missing")
        return self.meta


@dataclass(frozen=True)
class _DummyCompanyMeta:
    """用于测试的 CompanyMeta 兼容桩。"""

    ticker: str
    company_id: str
    company_name: str
    market: str


@pytest.mark.unit
def test_safe_get_company_meta_returns_none_when_missing() -> None:
    """验证缺失公司元数据时返回 `None`。"""

    repository = cast(CompanyMetaRepositoryProtocol, _SpyCompanyRepository(meta=None))
    assert sec_safe_meta_access.safe_get_company_meta(repository, ticker="AAPL") is None


@pytest.mark.unit
def test_safe_get_filing_source_meta_swallows_value_error_and_os_error() -> None:
    """验证 filing source meta 读取会吞掉 staging 视图常见读取失败。"""

    value_error_repository = cast(
        SourceDocumentRepositoryProtocol,
        _SpySourceRepository(source_error=ValueError),
    )
    os_error_repository = cast(
        SourceDocumentRepositoryProtocol,
        _SpySourceRepository(source_error=OSError),
    )

    assert (
        sec_safe_meta_access.safe_get_filing_source_meta(
            value_error_repository,
            ticker="AAPL",
            document_id="fil_1",
        )
        is None
    )
    assert (
        sec_safe_meta_access.safe_get_filing_source_meta(
            os_error_repository,
            ticker="AAPL",
            document_id="fil_1",
        )
        is None
    )


@pytest.mark.unit
def test_safe_get_document_and_processed_meta_return_none_when_missing() -> None:
    """验证普通 source/processed meta 缺失时返回 `None`。"""

    source_repository = cast(SourceDocumentRepositoryProtocol, _SpySourceRepository(source_meta=None))
    processed_repository = cast(ProcessedDocumentRepositoryProtocol, _SpyProcessedRepository(meta=None))

    assert (
        sec_safe_meta_access.safe_get_document_meta(
            source_repository,
            ticker="AAPL",
            document_id="fil_1",
            source_kind=SourceKind.FILING,
        )
        is None
    )
    assert (
        sec_safe_meta_access.safe_get_processed_meta(
            processed_repository,
            ticker="AAPL",
            document_id="fil_1",
        )
        is None
    )


@pytest.mark.unit
def test_resolve_document_version_uses_increment_only_when_fingerprint_changes() -> None:
    """验证 document version 只在历史指纹变化时递增。"""

    increment_calls: list[str] = []

    def _increment(version: str) -> str:
        increment_calls.append(version)
        return "v9"

    assert (
        sec_safe_meta_access.resolve_document_version(
            None,
            "fp-1",
            increment_document_version=_increment,
        )
        == "v1"
    )
    assert increment_calls == []
    assert (
        sec_safe_meta_access.resolve_document_version(
            {"document_version": "v3", "source_fingerprint": "fp-1"},
            "fp-1",
            increment_document_version=_increment,
        )
        == "v3"
    )
    assert increment_calls == []
    assert (
        sec_safe_meta_access.resolve_document_version(
            {"document_version": "v3", "source_fingerprint": "fp-1"},
            "fp-2",
            increment_document_version=_increment,
        )
        == "v9"
    )
    assert increment_calls == ["v3"]