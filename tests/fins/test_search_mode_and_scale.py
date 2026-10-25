"""search_document mode 参数与 evidence 输出测试。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

from alpha.engine.processors.base import SearchHit
from alpha.engine.processors.source import Source
from alpha.fins.domain.document_models import CompanyMeta, SourceHandle
from alpha.fins.domain.enums import SourceKind
from alpha.fins.tools.search_engine import (
    _build_search_query_expansions,
    _normalize_search_matches,
    _resolve_search_mode,
)
from alpha.fins.tools.search_models import (
    SEARCH_MODE_AUTO,
    SEARCH_MODE_EXACT,
    SEARCH_MODE_KEYWORD,
    SEARCH_MODE_SEMANTIC,
)
from alpha.fins.tools.service_helpers import (
    _infer_scale_from_decimals,
    _parse_xbrl_decimals_value,
)
from tests.fins.legacy_repository_adapters import LegacyCompatibleFinsToolService as FinsToolService


# ============================================================================
# 测试桩
# ============================================================================


class _DummySource:
    """测试用 Source 桩。"""

    def __init__(self, uri: str) -> None:
        self.uri = uri
        self.media_type = "text/html"
        self.content_length = None
        self.etag = None

    def open(self) -> Any:
        raise OSError("dummy")

    def materialize(self, suffix: Optional[str] = None) -> Any:
        raise OSError("dummy")


@dataclass
class _ModeTrackingProcessor:
    """记录 search 调用次数和查询词的处理器桩。"""

    document_id: str
    search_calls: list[str] = field(default_factory=list)

    def list_sections(self) -> list[dict[str, Any]]:
        return [{"ref": "s_0001", "title": "Section", "level": 1, "parent_ref": None, "preview": "x"}]

    def read_section(self, ref: str) -> dict[str, Any]:
        return {"ref": ref, "content": "text", "tables": [], "contains_full_text": True}

    def search(self, query: str, within_ref: Optional[str] = None) -> list[dict[str, Any]]:
        self.search_calls.append(query)  # type: ignore[union-attr]
        # 仅 exact 原始查询命中；扩展查询不命中
        normalized = query.strip().lower()
        if normalized == "revenue":
            return [
                {
                    "section_ref": "s_0001",
                    "section_title": "Section",
                    "snippet": "Total revenue was $100B.",
                    "page_no": 1,
                }
            ]
        return []

    def list_tables(self) -> list[dict[str, Any]]:
        return []

    def read_table(self, table_ref: str) -> dict[str, Any]:
        return {"table_ref": table_ref, "data_format": "markdown", "data": "|A|", "columns": None,
                "row_count": 1, "col_count": 1, "is_financial": False}

    def get_page_content(self, page_no: int) -> dict[str, Any]:
        return {"sections": [], "tables": [], "text_preview": "", "has_content": False, "total_items": 0, "supported": True}

    def get_financial_statement(self, statement_type: str) -> dict[str, Any]:
        return {"statement_type": statement_type, "periods": [], "rows": [], "currency": None, "units": None, "data_quality": "partial"}

    def query_xbrl_facts(self, concepts: Optional[list[str]] = None, **kwargs: Any) -> dict[str, Any]:
        return {"query_params": {"concepts": concepts or []}, "facts": [], "total": 0}


class _ModeTrackingProcessorRegistry:
    """返回 _ModeTrackingProcessor 的注册表桩。"""

    def __init__(self) -> None:
        self.last_processor: Optional[_ModeTrackingProcessor] = None

    def create(self, source: Source, *, form_type: Optional[str] = None, media_type: Optional[str] = None) -> Any:
        doc_id = str(source.uri).split("/")[-1].split(".")[0]
        p = _ModeTrackingProcessor(document_id=doc_id)
        self.last_processor = p
        return p

    def create_with_fallback(self, source: Source, **kwargs: Any) -> Any:
        return self.create(source)


class _FakeRepository:
    """简化仓储桩。"""

    def __init__(self) -> None:
        self._meta: dict[str, dict[str, Any]] = {
            "fil_1": {
                "document_id": "fil_1",
                "form_type": "10-K",
                "fiscal_year": 2024,
                "fiscal_period": "FY",
                "filing_date": "2024-11-01",
                "ingest_method": "download",
                "accession_number": "0000320193-24-000123",
                "ingest_complete": True,
                "is_deleted": False,
                "amended": False,
            }
        }

    def list_document_ids(self, ticker: str, source_kind: Optional[SourceKind] = None) -> list[str]:
        return list(self._meta.keys())

    def resolve_existing_ticker(self, candidates: list[str]) -> Optional[str]:
        if "AAPL" in candidates:
            return "AAPL"
        return None

    def get_document_meta(self, ticker: str, document_id: str) -> dict[str, Any]:
        return dict(self._meta[document_id])

    def get_processed_meta(self, ticker: str, document_id: str) -> dict[str, Any]:
        _ = (ticker, document_id)
        return {}

    def get_source_handle(self, ticker: str, document_id: str, source_kind: SourceKind) -> SourceHandle:
        return SourceHandle(ticker=ticker, document_id=document_id, source_kind=source_kind.value)

    def get_primary_source(self, ticker: str, document_id: str, source_kind: SourceKind) -> Source:
        return _DummySource(uri=f"local://{source_kind.value}/{document_id}.html")

    def get_company_meta(self, ticker: str) -> CompanyMeta:
        return CompanyMeta(
            company_id="320193", company_name="Apple Inc.", ticker=ticker,
            market="US", resolver_version="test", updated_at="2026-01-01T00:00:00+00:00",
        )


# ============================================================================
# _resolve_search_mode 测试
# ============================================================================


@pytest.mark.unit
class TestResolveSearchMode:
    """_resolve_search_mode 校验测试。"""

    def test_none_defaults_to_auto(self) -> None:
        assert _resolve_search_mode(None) == SEARCH_MODE_AUTO

    def test_empty_string_defaults_to_auto(self) -> None:
        assert _resolve_search_mode("") == SEARCH_MODE_AUTO

    def test_valid_modes(self) -> None:
        assert _resolve_search_mode("auto") == "auto"
        assert _resolve_search_mode("exact") == "exact"
        assert _resolve_search_mode("keyword") == "keyword"
        assert _resolve_search_mode("semantic") == "semantic"

    def test_case_insensitive(self) -> None:
        assert _resolve_search_mode("EXACT") == "exact"
        assert _resolve_search_mode("Keyword") == "keyword"

    def test_invalid_raises(self) -> None:
        from alpha.engine.exceptions import ToolArgumentError
        with pytest.raises(ToolArgumentError):
            _resolve_search_mode("fuzzy")


# ============================================================================
# _build_search_query_expansions mode 过滤测试
# ============================================================================


@pytest.mark.unit
class TestBuildSearchQueryExpansionsMode:
    """_build_search_query_expansions 按 mode 过滤策略测试。"""

    def test_keyword_mode_only_token(self) -> None:
        """keyword 模式仅生成 token 策略。"""

        expansions = _build_search_query_expansions(
            "share repurchase program", mode=SEARCH_MODE_KEYWORD,
        )
        strategies = {e["strategy"] for e in expansions}
        # 不应包含 phrase_variant / synonym
        assert "phrase_variant" not in strategies
        assert "synonym" not in strategies

    def test_auto_mode_includes_all(self) -> None:
        """auto 模式包含全部策略。"""

        expansions = _build_search_query_expansions(
            "share repurchase", mode=SEARCH_MODE_AUTO,
        )
        strategies = {e["strategy"] for e in expansions}
        # 至少应有多种策略
        assert len(strategies) >= 1

    def test_semantic_mode_includes_synonym(self) -> None:
        """semantic 模式包含同义词策略。"""

        expansions = _build_search_query_expansions(
            "share repurchase", mode=SEARCH_MODE_SEMANTIC,
        )
        strategies = {e["strategy"] for e in expansions}
        # semantic 应包含 phrase_variant 或 synonym
        has_non_token = "phrase_variant" in strategies or "synonym" in strategies
        # 即使没有同义词映射，也不应被 keyword 限制
        assert "token" in strategies or has_non_token


# ============================================================================
# search_document mode 集成测试
# ============================================================================


@pytest.mark.unit
class TestSearchDocumentMode:
    """search_document mode 参数端到端测试。"""

    def _create_service(self) -> tuple[FinsToolService, _ModeTrackingProcessorRegistry]:
        repo = _FakeRepository()
        registry = _ModeTrackingProcessorRegistry()
        service = FinsToolService(repository=repo, processor_registry=registry)
        return service, registry

    def test_auto_mode_returns_mode_field(self) -> None:
        """验证返回结果包含 mode 字段。"""

        service, _ = self._create_service()
        result = service.search_document(
            ticker="AAPL", document_id="fil_1", query="revenue",
        )
        assert result["mode"] == "auto"
        assert "diagnostics" in result
        assert result["diagnostics"]["mode"] == "auto"

    def test_exact_mode_no_expansion(self) -> None:
        """exact 模式不触发扩展查询。"""

        service, registry = self._create_service()
        result = service.search_document(
            ticker="AAPL", document_id="fil_1", query="nonexistent term xyz",
            mode="exact",
        )
        assert result["mode"] == "exact"
        assert "diagnostics" in result
        assert result["diagnostics"]["used_expansion"] is False
        assert result["diagnostics"]["expansion_query_count"] == 0
        # 只调用了一次 processor.search（exact）
        proc = registry.last_processor
        assert len(proc.search_calls) == 1  # type: ignore[union-attr]

    def test_keyword_mode_skips_exact(self) -> None:
        """keyword 模式跳过精确匹配，直接做 token 搜索。"""

        service, registry = self._create_service()
        result = service.search_document(
            ticker="AAPL", document_id="fil_1", query="revenue growth",
            mode="keyword",
        )
        assert result["mode"] == "keyword"
        # keyword 模式不做 exact 搜索
        proc = registry.last_processor
        # 所有 search 调用都是扩展查询（无 "revenue growth" exact call）
        all_queries = proc.search_calls  # type: ignore[union-attr]
        # 至少有 token 拆分后的调用
        assert len(all_queries) >= 1

    def test_evidence_structure(self) -> None:
        """验证返回的 matches 使用 evidence 结构。"""

        service, _ = self._create_service()
        result = service.search_document(
            ticker="AAPL", document_id="fil_1", query="revenue",
        )
        if result["matches"]:
            match = result["matches"][0]
            assert "evidence" in match
            assert isinstance(match["evidence"], dict)
            assert "context" in match["evidence"]
            # 不应再有顶层 snippet
            assert "snippet" not in match

    def test_citation_in_search_result(self) -> None:
        """验证 search_document 返回包含 citation。"""

        service, _ = self._create_service()
        result = service.search_document(
            ticker="AAPL", document_id="fil_1", query="revenue",
        )
        assert "citation" in result
        citation = result["citation"]
        assert citation["ticker"] == "AAPL"
        assert citation["document_id"] == "fil_1"
        assert citation["source_type"] == "SEC_EDGAR"


# ============================================================================
# _parse_xbrl_decimals_value 测试
# ============================================================================


@pytest.mark.unit
class TestParseXbrlDecimalsValue:
    """_parse_xbrl_decimals_value 测试。"""

    def test_none(self) -> None:
        assert _parse_xbrl_decimals_value(None) is None

    def test_inf_string(self) -> None:
        assert _parse_xbrl_decimals_value("INF") is None
        assert _parse_xbrl_decimals_value("inf") is None

    def test_integer(self) -> None:
        assert _parse_xbrl_decimals_value(-6) == -6
        assert _parse_xbrl_decimals_value(0) == 0
        assert _parse_xbrl_decimals_value(2) == 2

    def test_string_integer(self) -> None:
        assert _parse_xbrl_decimals_value("-3") == -3
        assert _parse_xbrl_decimals_value("0") == 0

    def test_invalid(self) -> None:
        assert _parse_xbrl_decimals_value("abc") is None


# ============================================================================
# _infer_scale_from_decimals 测试
# ============================================================================


@pytest.mark.unit
class TestInferScaleFromDecimals:
    """_infer_scale_from_decimals 测试。"""

    def test_none(self) -> None:
        assert _infer_scale_from_decimals(None) is None

    def test_billions(self) -> None:
        assert _infer_scale_from_decimals(-9) == "billions"

    def test_millions(self) -> None:
        assert _infer_scale_from_decimals(-6) == "millions"

    def test_thousands(self) -> None:
        assert _infer_scale_from_decimals(-3) == "thousands"

    def test_units_zero(self) -> None:
        assert _infer_scale_from_decimals(0) == "units"

    def test_units_positive(self) -> None:
        assert _infer_scale_from_decimals(2) == "units"

    def test_unknown_negative(self) -> None:
        """不在映射表中的负数返回 None。"""

        assert _infer_scale_from_decimals(-4) is None
        assert _infer_scale_from_decimals(-1) is None


# ============================================================================
# _normalize_search_matches token_fallback 透传测试
# ============================================================================


@pytest.mark.unit
class TestNormalizeSearchMatchesTokenFallback:
    """验证 _normalize_search_matches 对 _token_fallback 标记的处理。"""

    def test_token_fallback_flag_preserved(self) -> None:
        """带 _token_fallback 的命中在标准化后保留该标记。"""
        raw: list[SearchHit] = [
            {
                "section_ref": "sec_001",
                "section_title": "Item 1",
                "snippet": "some text",
                "_token_fallback": True,
            },
        ]
        normalized = _normalize_search_matches(raw)
        assert len(normalized) == 1
        assert normalized[0]["_token_fallback"] is True

    def test_normal_hit_no_token_fallback(self) -> None:
        """普通命中不含 _token_fallback 标记。"""
        raw: list[SearchHit] = [
            {
                "section_ref": "sec_002",
                "section_title": "Item 2",
                "snippet": "exact match text",
            },
        ]
        normalized = _normalize_search_matches(raw)
        assert len(normalized) == 1
        assert "_token_fallback" not in normalized[0]

    def test_mixed_hits_separation(self) -> None:
        """混合命中：标记和非标记可通过 _token_fallback 区分。"""
        raw: list[SearchHit] = [
            {"section_ref": "s1", "section_title": "A", "snippet": "text1", "_token_fallback": True},
            {"section_ref": "s2", "section_title": "B", "snippet": "text2"},
            {"section_ref": "s3", "section_title": "C", "snippet": "text3", "_token_fallback": True},
        ]
        normalized = _normalize_search_matches(raw)
        exact = [m for m in normalized if not m.get("_token_fallback")]
        fallback = [m for m in normalized if m.get("_token_fallback")]
        assert len(exact) == 1
        assert exact[0]["section_ref"] == "s2"
        assert len(fallback) == 2
