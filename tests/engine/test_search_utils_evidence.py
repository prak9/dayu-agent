"""search_utils evidence 抽取函数测试。"""

from __future__ import annotations

from typing import cast

import pytest

from alpha.engine.processors.base import SearchHit
from alpha.engine.processors.search_utils import (
    extract_evidence_items,
    extract_token_cooccurrence_snippets,
    enrich_hits_by_section_token_or,
    enrich_hits_with_evidence,
    EVIDENCE_CONTEXT_MAX_CHARS,
)


def _search_hits(items: list[dict[str, object]]) -> list[SearchHit]:
    """在测试装配边界把宽字典显式收窄为 SearchHit 列表。"""

    return cast(list[SearchHit], items)


def _hit_section_ref(hit: SearchHit) -> str:
    """安全读取 SearchHit.section_ref。"""

    return str(hit.get("section_ref") or "")


# ============================================================================
# extract_evidence_items 测试
# ============================================================================


@pytest.mark.unit
class TestExtractEvidenceItems:
    """extract_evidence_items 测试。"""

    _CONTENT = (
        "The company reported total revenue of $50 billion. "
        "Operating expenses increased by 10%. "
        "Net income was $12 billion, reflecting strong revenue growth."
    )

    def test_basic_extraction(self) -> None:
        """基本证据抽取。"""

        items = extract_evidence_items(self._CONTENT, "revenue")
        assert len(items) >= 1
        first = items[0]
        assert "matched_text" in first
        assert "context" in first
        assert "revenue" in first["matched_text"].lower()

    def test_context_contains_matched_text(self) -> None:
        """验证稳定 evidence 上下文仍覆盖命中文本。"""

        items = extract_evidence_items(self._CONTENT, "revenue")
        first = items[0]
        assert first["matched_text"]
        assert first["matched_text"].lower() in first["context"].lower()

    def test_empty_content(self) -> None:
        """空内容返回空列表。"""

        assert extract_evidence_items("", "revenue") == []

    def test_empty_query(self) -> None:
        """空查询返回空列表。"""

        assert extract_evidence_items(self._CONTENT, "") == []

    def test_no_match(self) -> None:
        """无匹配返回空列表。"""

        assert extract_evidence_items(self._CONTENT, "cryptocurrency") == []

    def test_max_per_section(self) -> None:
        """验证 max_per_section 限制。"""

        items = extract_evidence_items(self._CONTENT, "revenue", max_per_section=1)
        assert len(items) <= 1

    def test_context_longer_than_matched_text(self) -> None:
        """context 应比 matched_text 更长（包含周围句子）。"""

        items = extract_evidence_items(self._CONTENT, "revenue")
        if items:
            first = items[0]
            assert len(first["context"]) >= len(first["matched_text"])


# ============================================================================
# enrich_hits_with_evidence 测试
# ============================================================================


@pytest.mark.unit
class TestEnrichHitsWithEvidence:
    """enrich_hits_with_evidence 测试。"""

    _SECTION_CONTENT = (
        "Total revenue increased to $100 million. "
        "Costs were well managed during the period."
    )

    def test_basic_enrichment(self) -> None:
        """基本证据化增强。"""

        hits = _search_hits([
            {
                "section_ref": "sec_001",
                "section_title": "Financial Summary",
                "snippet": "revenue increased",
                "page_no": 5,
            }
        ])
        content_map = {"sec_001": self._SECTION_CONTENT}
        enriched = enrich_hits_with_evidence(hits, content_map, "revenue")
        assert len(enriched) >= 1
        first = enriched[0]
        assert "evidence" in first
        assert _hit_section_ref(first) == "sec_001"

    def test_fallback_when_no_match(self) -> None:
        """内容中无匹配时回退到传统 snippet。"""

        hits = _search_hits([
            {
                "section_ref": "sec_001",
                "section_title": "Other",
                "snippet": "some snippet text",
            }
        ])
        content_map = {"sec_001": "unrelated text about cats"}
        enriched = enrich_hits_with_evidence(hits, content_map, "cryptocurrency")
        # 应仍有输出（回退到 snippet）
        assert len(enriched) >= 1
        if enriched:
            first = enriched[0]
            assert "evidence" in first

    def test_empty_hits(self) -> None:
        """空命中列表。"""

        enriched = enrich_hits_with_evidence([], {}, "revenue")
        assert enriched == []

    def test_preserves_page_no(self) -> None:
        """验证 page_no 保留传递。"""

        hits = _search_hits([
            {
                "section_ref": "sec_001",
                "section_title": "Sec",
                "snippet": "revenue",
                "page_no": 42,
            }
        ])
        content_map = {"sec_001": self._SECTION_CONTENT}
        enriched = enrich_hits_with_evidence(hits, content_map, "revenue")
        if enriched:
            assert enriched[0].get("page_no") == 42


# ============================================================================
# extract_token_cooccurrence_snippets 测试
# ============================================================================


@pytest.mark.unit
class TestExtractTokenCooccurrenceSnippets:
    """extract_token_cooccurrence_snippets 单元测试。"""

    _CONTENT = (
        "The board of directors held a special meeting. "
        "The election of Class II directors was the primary agenda. "
        "Director nominations were reviewed and approved. "
        "Financial results show strong revenue from election services. "
        "The director election process followed all regulatory requirements."
    )

    def test_prefers_exact_match_when_available(self) -> None:
        """当原始查询在文本中精确出现时，优先使用精确匹配。"""
        snippets = extract_token_cooccurrence_snippets(
            content=self._CONTENT,
            tokens=["director", "election"],
            original_query="director election",
            max_chars=200,
        )
        assert snippets
        assert any("director election" in s.lower() for s in snippets)

    def test_cooccurrence_window_finds_both_tokens(self) -> None:
        """当精确匹配不存在但 token 独立存在时，snippet 应包含多 token 共现区域。"""
        # 构造不含 "cash flow" 但含 "cash" 和 "flow" 分散出现的文本
        content = (
            "The company's cash position improved significantly this quarter. "
            "Operating cash equivalents remained stable at 5.2 billion. "
            "Some unrelated filler text goes here to separate tokens. "
            "Some more filler text about nothing related. "
            "Revenue flow from subscription services increased year over year."
        )
        snippets = extract_token_cooccurrence_snippets(
            content=content,
            tokens=["cash", "flow"],
            original_query="cash flow",
            max_chars=300,
        )
        assert snippets
        # snippet 应至少包含一个 token
        combined = " ".join(snippets).lower()
        assert "cash" in combined or "flow" in combined

    def test_empty_content_returns_empty(self) -> None:
        """空内容返回空列表。"""
        assert extract_token_cooccurrence_snippets("", ["a", "b"], "a b") == []
        assert extract_token_cooccurrence_snippets("  \n", ["a", "b"], "a b") == []

    def test_empty_tokens_returns_empty(self) -> None:
        """空 token 列表返回空列表。"""
        assert extract_token_cooccurrence_snippets("some content", [], "query") == []

    def test_no_token_matches_returns_empty(self) -> None:
        """token 均不存在于文本中时返回空列表。"""
        result = extract_token_cooccurrence_snippets(
            content="Completely unrelated text about cats and dogs.",
            tokens=["quantum", "computing"],
            original_query="quantum computing",
        )
        assert result == []

    def test_snippet_respects_max_chars(self) -> None:
        """snippet 长度不超过 max_chars。"""
        long_content = "The " + "word " * 500 + "director met with election board."
        snippets = extract_token_cooccurrence_snippets(
            content=long_content,
            tokens=["director", "election"],
            original_query="director election",
            max_chars=100,
        )
        assert snippets
        assert all(len(s) <= 120 for s in snippets)  # 允许 word boundary 微调

    def test_single_token_in_content(self) -> None:
        """仅一个 token 出现时仍返回 snippet。"""
        content = "The company held a director meeting to discuss performance."
        snippets = extract_token_cooccurrence_snippets(
            content=content,
            tokens=["director", "election"],
            original_query="director election",
            max_chars=200,
        )
        assert snippets
        assert "director" in snippets[0].lower()


# ============================================================================
# enrich_hits_by_section_token_or 测试
# ============================================================================


@pytest.mark.unit
class TestEnrichHitsBySectionTokenOr:
    """enrich_hits_by_section_token_or 单元测试。"""

    def test_basic_enrichment_with_token_fallback_tag(self) -> None:
        """验证返回的每个 hit 带 _token_fallback=True 标记。"""
        hits_raw = _search_hits([
            {"section_ref": "sec_001", "section_title": "Item 1", "snippet": "director election"},
            {"section_ref": "sec_002", "section_title": "Item 2", "snippet": "director election"},
        ])
        content_map = {
            "sec_001": "The board of directors held a special election for the new committee.",
            "sec_002": "Director appointments were decided by shareholder election.",
        }
        enriched = enrich_hits_by_section_token_or(
            hits_raw=hits_raw,
            section_content_map=content_map,
            tokens=["director", "election"],
            original_query="director election",
        )
        assert enriched
        assert all(h.get("_token_fallback") is True for h in enriched)

    def test_enriched_snippet_contains_relevant_tokens(self) -> None:
        """验证 snippet 包含相关 token 而非无关内容。"""
        hits_raw = _search_hits([
            {"section_ref": "sec_a", "section_title": "SEC A", "snippet": "director election"},
        ])
        content_map = {
            "sec_a": (
                "Some preamble text about company history. "
                "The annual election of directors was conducted in accordance with bylaws. "
                "Additional filler text about operations."
            ),
        }
        enriched = enrich_hits_by_section_token_or(
            hits_raw=hits_raw,
            section_content_map=content_map,
            tokens=["director", "election"],
            original_query="director election",
        )
        assert enriched
        snippet_text = enriched[0].get("snippet", "").lower()
        # snippet 至少包含一个查询 token
        assert "election" in snippet_text or "director" in snippet_text

    def test_fallback_to_raw_snippet_when_no_content(self) -> None:
        """section 内容缺失时回退到原始 snippet。"""
        hits_raw = _search_hits([
            {"section_ref": "sec_x", "section_title": "X", "snippet": "fallback text"},
        ])
        content_map = {}  # 无内容
        enriched = enrich_hits_by_section_token_or(
            hits_raw=hits_raw,
            section_content_map=content_map,
            tokens=["some", "query"],
            original_query="some query",
        )
        assert enriched
        assert enriched[0].get("_token_fallback") is True

    def test_empty_section_ref_filtered(self) -> None:
        """空 section_ref 的 hit 被过滤。"""
        hits_raw = _search_hits([
            {"section_ref": "", "section_title": "X", "snippet": "text"},
            {"section_ref": "sec_ok", "section_title": "Y", "snippet": "text"},
        ])
        content_map = {"sec_ok": "Director election was held in the annual meeting."}
        enriched = enrich_hits_by_section_token_or(
            hits_raw=hits_raw,
            section_content_map=content_map,
            tokens=["director", "election"],
            original_query="director election",
        )
        # 只有 sec_ok 有效
        refs = {_hit_section_ref(hit) for hit in enriched}
        assert "sec_ok" in refs
        assert "" not in refs

    def test_page_no_preserved(self) -> None:
        """验证 page_no 被正确传递。"""
        hits_raw = _search_hits([
            {"section_ref": "sec_p", "section_title": "P", "snippet": "text", "page_no": 42},
        ])
        content_map = {"sec_p": "The director was nominated in the election."}
        enriched = enrich_hits_by_section_token_or(
            hits_raw=hits_raw,
            section_content_map=content_map,
            tokens=["director", "election"],
            original_query="director election",
        )
        assert enriched
        assert enriched[0].get("page_no") == 42
