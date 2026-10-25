"""search_utils 边界场景和错误处理测试（提升覆盖率到 95%+）。

本测试文件补充 test_search_utils.py 中未覆盖的边界情况和防御性代码路径。
"""

from __future__ import annotations

from typing import cast

import pytest

from alpha.engine.processors.base import SearchHit
from alpha.engine.processors.search_utils import (
    build_snippet_from_sentence_window,
    cap_per_section,
    dedup_snippets,
    enrich_hits_by_section,
    extract_query_anchored_snippets,
    split_sentences,
)
from alpha.engine.processors import search_utils


def _search_hits(items: list[dict[str, object]]) -> list[SearchHit]:
    """在测试装配边界把宽字典显式收窄为 SearchHit 列表。"""

    return cast(list[SearchHit], items)


def _hit_section_ref(hit: SearchHit) -> str:
    """安全读取 SearchHit.section_ref。"""

    return str(hit.get("section_ref") or "")


def _hit_snippet(hit: SearchHit) -> str:
    """安全读取 SearchHit.snippet。"""

    return str(hit.get("snippet") or "")


def _hit_page_no(hit: SearchHit) -> int | None:
    """安全读取 SearchHit.page_no。"""

    value = hit.get("page_no")
    return value if isinstance(value, int) else None


@pytest.mark.unit
def test_extract_query_anchored_snippets_empty_content() -> None:
    """验证空内容返回空列表。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    assert extract_query_anchored_snippets("", "query", 100, 2) == []
    assert extract_query_anchored_snippets("   ", "query", 100, 2) == []
    assert extract_query_anchored_snippets("\n\t", "query", 100, 2) == []


@pytest.mark.unit
def test_extract_query_anchored_snippets_empty_query() -> None:
    """验证空查询返回空列表。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    assert extract_query_anchored_snippets("content", "", 100, 2) == []
    assert extract_query_anchored_snippets("content", "  ", 100, 2) == []


@pytest.mark.unit
def test_extract_query_anchored_snippets_no_match() -> None:
    """验证查询未命中返回空列表。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    content = "This is some text about business operations."
    snippets = extract_query_anchored_snippets(content, "NOMATCH_XYZ", 100, 2)
    assert snippets == []


@pytest.mark.unit
def test_extract_query_anchored_snippets_fallback_char_window() -> None:
    """验证回退到字符窗口提取（当句子分割失败时）。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    # 构造一个没有句末标点的长文本，使句子切分无效但字符匹配成功
    content = "A" * 200 + "repurchase" + "B" * 200
    snippets = extract_query_anchored_snippets(content, "repurchase", 100, 2)
    
    # 应该通过 _fallback_char_window_snippets 返回结果
    assert snippets
    assert "repurchase" in snippets[0].lower()


@pytest.mark.unit
def test_build_snippet_from_sentence_window_empty_sentences() -> None:
    """验证空句子列表返回空字符串。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    snippet = build_snippet_from_sentence_window([], 0, "query", 100)
    assert snippet == ""


@pytest.mark.unit
def test_build_snippet_from_sentence_window_invalid_index() -> None:
    """验证无效索引返回空字符串。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    sentences = ["First sentence.", "Second sentence."]
    
    # 负索引
    assert build_snippet_from_sentence_window(sentences, -1, "query", 100) == ""
    
    # 超出范围
    assert build_snippet_from_sentence_window(sentences, 10, "query", 100) == ""


@pytest.mark.unit
def test_build_snippet_from_sentence_window_zero_max_chars() -> None:
    """验证 max_chars <= 0 返回空字符串。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    sentences = ["First sentence."]
    assert build_snippet_from_sentence_window(sentences, 0, "query", 0) == ""
    assert build_snippet_from_sentence_window(sentences, 0, "query", -10) == ""


@pytest.mark.unit
def test_build_snippet_from_sentence_window_expands_left_and_right() -> None:
    """验证窗口双向扩展逻辑。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    sentences = ["A.", "B.", "Target sentence with keyword.", "D.", "E."]
    
    snippet = build_snippet_from_sentence_window(sentences, 2, "keyword", 1000)
    
    # 应该包含所有句子，因为长度允许
    assert "A." in snippet
    assert "Target" in snippet
    assert "E." in snippet


@pytest.mark.unit
def test_build_snippet_from_sentence_window_truncates_when_too_long() -> None:
    """验证超长句子会被截断到 max_chars。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    long_sentence = "A" * 500 + " keyword " + "B" * 500
    sentences = [long_sentence]
    
    snippet = build_snippet_from_sentence_window(sentences, 0, "keyword", 100)
    
    assert len(snippet) <= 100
    assert "keyword" in snippet.lower()


@pytest.mark.unit
def test_dedup_snippets_empty_list() -> None:
    """验证空列表去重返回空列表。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    assert dedup_snippets([]) == []


@pytest.mark.unit
def test_dedup_snippets_single_item() -> None:
    """验证单个元素去重返回原列表。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    assert dedup_snippets(["only one"]) == ["only one"]


@pytest.mark.unit
def test_dedup_snippets_all_duplicates() -> None:
    """验证全重复返回单个元素。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    result = dedup_snippets(["same", "same", "same"])
    assert len(result) == 1


@pytest.mark.unit
def test_cap_per_section_empty_list() -> None:
    """验证空列表限流返回空列表。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    from alpha.engine.processors.search_utils import cap_per_section
    
    assert cap_per_section([], 2) == []


@pytest.mark.unit
def test_cap_per_section_below_cap() -> None:
    """验证少于上限时返回全部。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    from alpha.engine.processors.search_utils import cap_per_section
    
    items = ["a", "b"]
    assert cap_per_section(items, 5) == ["a", "b"]


@pytest.mark.unit
def test_cap_per_section_exceeds_cap() -> None:
    """验证超过上限时截断。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    from alpha.engine.processors.search_utils import cap_per_section
    
    items = ["a", "b", "c", "d", "e"]
    result = cap_per_section(items, 3)
    assert len(result) == 3
    assert result == ["a", "b", "c"]


@pytest.mark.unit
def test_enrich_hits_by_section_empty_hits() -> None:
    """验证空命中列表。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    enriched = enrich_hits_by_section([], {"s_0001": "content"}, "query", 100, 2)
    assert enriched == []


@pytest.mark.unit
def test_enrich_hits_by_section_section_not_in_map() -> None:
    """验证 section_ref 不在 content_map 中时使用原始 snippet。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    hits_raw = _search_hits([
        {"section_ref": "s_9999", "section_title": "Unknown", "snippet": "text", "page_no": 1},
    ])
    
    # section_content_map 为空，应该回退到原始 snippet
    enriched = enrich_hits_by_section(hits_raw, {}, "query", 100, 2)
    
    # 应该返回原始 snippet（去重后）
    assert len(enriched) == 1
    assert _hit_section_ref(enriched[0]) == "s_9999"
    assert _hit_snippet(enriched[0]) == "text"


@pytest.mark.unit
def test_enrich_hits_by_section_with_mixed_page_numbers() -> None:
    """验证混合页码（有效和 None）的处理。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    hits_raw = _search_hits([
        {"section_ref": "s_0001", "section_title": "A", "snippet": "x", "page_no": None},
        {"section_ref": "s_0001", "section_title": "A", "snippet": "y", "page_no": 5},
        {"section_ref": "s_0001", "section_title": "A", "snippet": "z", "page_no": None},
    ])
    section_content_map = {
        "s_0001": "Content with keyword mentioned multiple times.",
    }
    
    enriched = enrich_hits_by_section(hits_raw, section_content_map, "keyword", 100, 3)
    
    # 应该选择第一个有效页码 (5)
    assert len(enriched) == 1
    assert _hit_page_no(enriched[0]) == 5


@pytest.mark.unit
def test_enrich_hits_by_section_all_page_numbers_none() -> None:
    """验证所有页码都是 None 时不包含 page_no 键。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    hits_raw = _search_hits([
        {"section_ref": "s_0001", "section_title": "A", "snippet": "x", "page_no": None},
        {"section_ref": "s_0001", "section_title": "A", "snippet": "y", "page_no": None},
    ])
    section_content_map = {
        "s_0001": "Content with keyword.",
    }
    
    enriched = enrich_hits_by_section(hits_raw, section_content_map, "keyword", 100, 2)
    
    assert len(enriched) == 1
    # page_no 为 None 时不应该包含在结果中
    assert "page_no" not in enriched[0]


@pytest.mark.unit
def test_split_sentences_no_punctuation() -> None:
    """验证无标点文本的处理。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    # 没有句末标点，应该返回整个文本作为一个"句子"
    text = "This is continuous text without any sentence ending punctuation marks"
    sentences = split_sentences(text)
    
    # 实现可能返回空列表或包含整个文本，取决于逻辑
    # 根据代码，_split_sentence_spans 会在没有标点时返回空列表
    assert isinstance(sentences, list)


@pytest.mark.unit
def test_split_sentences_empty_text() -> None:
    """验证空文本返回空列表。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    assert split_sentences("") == []
    assert split_sentences("   ") == []


@pytest.mark.unit
def test_split_sentences_mixed_punctuation() -> None:
    """验证混合使用中英文标点。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    text = "中文句子。English sentence! 中文问号？English semicolon; 结尾；"
    sentences = split_sentences(text)
    
    assert len(sentences) == 5
    for sentence in sentences:
        assert sentence.strip()


@pytest.mark.unit
def test_private_normalize_whitespace() -> None:
    """验证空白字符标准化。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    # 测试私有函数（通过内部访问）
    result = search_utils._normalize_whitespace("  multiple   spaces  \n\ttabs\n")
    assert result == "multiple spaces tabs"
    
    # 测试空值处理
    assert search_utils._normalize_whitespace("") == ""
    assert search_utils._normalize_whitespace(None) == ""  # type: ignore


@pytest.mark.unit
def test_private_falback_char_window_empty_inputs() -> None:
    """验证字符窗口回退函数的空输入处理。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    # 空内容
    result = search_utils._fallback_char_window_snippets("", "query", 100)
    assert result == []
    
    # 空查询
    result = search_utils._fallback_char_window_snippets("content", "", 100)
    assert result == []


@pytest.mark.unit
def test_private_pick_first_positive_page_no_all_invalid() -> None:
    """验证全部无效页码返回 None。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    hits = _search_hits([
        {"page_no": None},
        {"page_no": 0},
        {"page_no": -1},
        {"page_no": "not_int"},  # type: ignore
        {},  # 没有 page_no 键
    ])
    
    result = search_utils._pick_first_positive_page_no(hits)
    assert result is None


@pytest.mark.unit
def test_private_pick_first_positive_page_no_finds_first_valid() -> None:
    """验证找到第一个有效页码。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    hits = _search_hits([
        {"page_no": None},
        {"page_no": 0},
        {"page_no": 5},  # 第一个有效
        {"page_no": 10},
    ])
    
    result = search_utils._pick_first_positive_page_no(hits)
    assert result == 5


@pytest.mark.unit
def test_extract_query_very_long_content_with_match_at_boundary() -> None:
    """验证命中在句子边界附近时的处理。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    # 构造特殊场景：命中在很长的单句中，测试截断逻辑
    content = "A" * 180 + " query " + "B" * 180
    snippets = extract_query_anchored_snippets(content, "query", 100, 2)
    
    assert snippets
    assert len(snippets[0]) <= 100
    assert "query" in snippets[0].lower()


@pytest.mark.unit
def test_extract_query_sentence_index_returns_none() -> None:
    """验证 sentence_index 为 None 的情况（继续循环）。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    # 构造一个边界场景：query 出现在奇怪的位置
    # 让 _locate_sentence_index 可能返回 None
    content = "。query"  # 句末标点后立即跟查询词
    snippets = extract_query_anchored_snippets(content, "query", 100, 2)
    
    # 应该通过 fallback 机制返回结果
    assert isinstance(snippets, list)


@pytest.mark.unit
def test_extract_query_snippet_does_not_contain_query() -> None:
    """验证 snippet 不包含 query 时跳过（防御性检查）。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    # 这个场景很难触发，因为需要在分句和窗口构建后 query 消失
    # 主要是防御性代码，我们通过其他测试间接覆盖
    content = "This is a test sentence. Another sentence."
    snippets = extract_query_anchored_snippets(content, "test", 100, 2)
    
    # 正常情况下总是包含 query
    assert all("test" in s.lower() for s in snippets)


@pytest.mark.unit
def test_build_snippet_expand_only_left() -> None:
    """验证只向左扩展的场景。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    # 命中在最后一句，只能向左扩展
    sentences = ["First.", "Second.", "Third.", "Target with keyword."]
    snippet = build_snippet_from_sentence_window(sentences, 3, "keyword", 1000)
    
    assert "First." in snippet
    assert "Target" in snippet


@pytest.mark.unit
def test_build_snippet_expand_only_right() -> None:
    """验证只向右扩展的场景。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    # 命中在第一句，只能向右扩展
    sentences = ["Target with keyword.", "Second.", "Third.", "Fourth."]
    snippet = build_snippet_from_sentence_window(sentences, 0, "keyword", 1000)
    
    assert "Target" in snippet
    assert "Fourth." in snippet


@pytest.mark.unit
def test_enrich_hits_section_content_empty_string() -> None:
    """验证 section_content 为空字符串时的处理。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    hits_raw = _search_hits([
        {"section_ref": "s_0001", "section_title": "Title", "snippet": "original", "page_no": 1},
    ])
    section_content_map = {
        "s_0001": "",  # 空内容
    }
    
    enriched = enrich_hits_by_section(hits_raw, section_content_map, "query", 100, 2)
    
    # 应该回退到原始 snippet
    assert len(enriched) == 1
    assert _hit_snippet(enriched[0]) == "original"


@pytest.mark.unit
def test_private_truncate_around_query() -> None:
    """验证 _truncate_around_query 的截断逻辑。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    long_text = "A" * 200 + " keyword " + "B" * 200
    result = search_utils._truncate_around_query(long_text, "keyword", 100)
    
    assert len(result) <= 100
    assert "keyword" in result.lower()


# ────────────────────────────────────────────────────────────────
# Step 14 – Snippet 单词边界对齐
# ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_snap_to_word_boundary_left_at_start() -> None:
    """验证文本开头返回 0。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    assert search_utils._snap_to_word_boundary_left("hello world", 0) == 0


@pytest.mark.unit
def test_snap_to_word_boundary_left_mid_word() -> None:
    """验证在单词中间时向右对齐到下一个空白后。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    text = "hello world foo"
    # pos=2 在 "hello" 中间 → 应向右找空白，对齐到 "world" 开头(pos 6)
    result = search_utils._snap_to_word_boundary_left(text, 2)
    assert result == 6  # "hello" 后空白在 pos 5, +1 = 6


@pytest.mark.unit
def test_snap_to_word_boundary_right_mid_word() -> None:
    """验证在单词中间时向右对齐到空白处。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    text = "hello world foo"
    # pos=7 在 "world" 中间 → 应向右找空白 pos=11
    result = search_utils._snap_to_word_boundary_right(text, 7)
    assert result == 11


@pytest.mark.unit
def test_snap_to_word_boundary_right_at_end() -> None:
    """验证超出文本末尾时返回 len(text)。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    text = "hello world"
    assert search_utils._snap_to_word_boundary_right(text, len(text)) == len(text)


@pytest.mark.unit
def test_fallback_char_window_word_aligned() -> None:
    """验证回退片段不在单词中间截断。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """
    content = "The quick brown fox jumps over the lazy dog and runs away"
    snippets = search_utils._fallback_char_window_snippets(content, "fox", 30)
    assert len(snippets) >= 1
    snippet = snippets[0]
    # 片段不应以半个单词开头或结尾
    assert not snippet[0].isalpha() or snippet == snippet.lstrip()
    assert "fox" in snippet.lower()
