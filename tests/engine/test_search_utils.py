"""搜索后处理工具测试。"""

from __future__ import annotations

import pytest

from alpha.engine.processors.base import SearchHit
from alpha.engine.processors.search_utils import (
    dedup_snippets,
    enrich_hits_by_section,
    extract_query_anchored_snippets,
    split_sentences,
)


def _search_hits(items: list[SearchHit]) -> list[SearchHit]:
    """把测试输入显式收窄为 SearchHit 列表。"""

    return items


def _hit_section_ref(hit: SearchHit) -> str | None:
    """读取 hit 的可选 section_ref。"""

    return hit.get("section_ref")


def _hit_page_no(hit: SearchHit) -> int | None:
    """读取 hit 的可选 page_no。"""

    return hit.get("page_no")


def _hit_snippet(hit: SearchHit) -> str | None:
    """读取 hit 的可选 snippet。"""

    return hit.get("snippet")


@pytest.mark.unit
def test_split_sentences_supports_cn_en_punctuation() -> None:
    """验证中英文标点句子切分。"""

    text = "第一句包含回购。Second sentence mentions repurchase! 第三句；Fourth?"
    sentences = split_sentences(text)

    assert len(sentences) == 4
    assert sentences[0].endswith("。")
    assert sentences[1].endswith("!")
    assert sentences[2].endswith("；")
    assert sentences[3].endswith("?")


@pytest.mark.unit
def test_extract_query_anchored_snippets_dedup_and_cap() -> None:
    """验证抽取片段会去重并按 section 限流。"""

    content = (
        "The company entered into a Share Repurchase Agreement on June 16, 2025. "
        "This repurchase agreement was signed by both parties. "
        "The REPURCHASE agreement includes customary closing conditions. "
        "Additional disclosure states that the repurchase agreement may be amended."
    )

    snippets = extract_query_anchored_snippets(
        content=content,
        query="repurchase",
        max_chars=360,
        max_per_section=2,
    )

    assert 1 <= len(snippets) <= 2
    assert all("repurchase" in item.lower() for item in snippets)
    assert all(len(item) <= 360 for item in snippets)


@pytest.mark.unit
def test_extract_query_anchored_snippets_respects_length_limit() -> None:
    """验证超长文本会被截断到最大长度。"""

    long_prefix = "A" * 400
    content = f"{long_prefix} repurchase agreement details and obligations continue with long appendix text"
    snippets = extract_query_anchored_snippets(
        content=content,
        query="repurchase",
        max_chars=360,
        max_per_section=2,
    )

    assert snippets
    assert len(snippets[0]) <= 360
    assert "repurchase" in snippets[0].lower()


@pytest.mark.unit
def test_dedup_snippets_uses_normalized_containment() -> None:
    """验证去重会处理规范化后包含关系。"""

    raw = [
        "Repurchase agreement was signed.",
        "repurchase agreement was signed",
        "The repurchase agreement was signed by both parties.",
    ]
    deduped = dedup_snippets(raw)

    assert len(deduped) == 1
    assert "both parties" in deduped[0]


@pytest.mark.unit
def test_enrich_hits_by_section_preserves_order_and_page_no() -> None:
    """验证按 section 聚合增强后保持顺序与页码。"""

    hits_raw = _search_hits([
        {"section_ref": "s_0002", "section_title": "B", "snippet": "repurchase", "page_no": 9},
        {"section_ref": "s_0001", "section_title": "A", "snippet": "repurchase", "page_no": 3},
    ])
    section_content_map = {
        "s_0002": "Repurchase agreement for section B. Additional repurchase detail.",
        "s_0001": "Repurchase agreement for section A.",
    }

    enriched = enrich_hits_by_section(
        hits_raw=hits_raw,
        section_content_map=section_content_map,
        query="repurchase",
    )

    assert enriched
    assert _hit_section_ref(enriched[0]) == "s_0002"
    assert _hit_page_no(enriched[0]) == 9
    assert all("repurchase" in str(_hit_snippet(item) or "").lower() for item in enriched)


@pytest.mark.unit
def test_extract_query_anchored_snippets_with_empty_inputs() -> None:
    """验证空输入时返回空列表。"""

    from alpha.engine.processors.search_utils import extract_query_anchored_snippets

    # 空content
    assert extract_query_anchored_snippets("", "query", 100, 2) == []

    # 空query
    assert extract_query_anchored_snippets("content", "", 100, 2) == []

    # 都为空
    assert extract_query_anchored_snippets("", "", 100, 2) == []

    # None query
    assert extract_query_anchored_snippets("content", None, 100, 2) == []  # type: ignore


@pytest.mark.unit
def test_extract_query_anchored_snippets_no_sentence_delimiters() -> None:
    """验证无句子分隔符时回退到字符窗口。"""

    from alpha.engine.processors.search_utils import extract_query_anchored_snippets

    content = "keyword appears here multiple times keyword again"
    snippets = extract_query_anchored_snippets(content, "keyword", 30, 2)

    assert len(snippets) <= 2
    assert all("keyword" in s.lower() for s in snippets)


@pytest.mark.unit
def test_extract_query_anchored_snippets_query_not_found() -> None:
    """验证查询词不存在时返回空列表。"""

    from alpha.engine.processors.search_utils import extract_query_anchored_snippets

    content = "This is some text. Another sentence here."
    snippets = extract_query_anchored_snippets(content, "nonexistent", 100, 2)

    assert snippets == []


@pytest.mark.unit
def test_build_snippet_from_sentence_window_edge_cases() -> None:
    """验证 build_snippet_from_sentence_window 边界情况。"""

    from alpha.engine.processors.search_utils import build_snippet_from_sentence_window

    sentences = ["First sentence.", "Second sentence.", "Third sentence."]

    # 空句子列表
    assert build_snippet_from_sentence_window([], 0, "query", 100) == ""

    # 非法索引
    assert build_snippet_from_sentence_window(sentences, -1, "query", 100) == ""
    assert build_snippet_from_sentence_window(sentences, 10, "query", 100) == ""

    # max_chars <= 0
    assert build_snippet_from_sentence_window(sentences, 0, "query", 0) == ""
    assert build_snippet_from_sentence_window(sentences, 0, "query", -1) == ""

    # 单句超长需要截断
    long_sentence = ["A" * 500 + " keyword " + "B" * 500]
    snippet = build_snippet_from_sentence_window(long_sentence, 0, "keyword", 100)
    assert len(snippet) <= 100
    assert "keyword" in snippet.lower()


@pytest.mark.unit
def test_enrich_hits_by_section_fallback_to_raw_snippets() -> None:
    """验证当无法从 section_content 提取时回退到原始 snippet。"""

    from alpha.engine.processors.search_utils import enrich_hits_by_section

    hits_raw = _search_hits([
        {"section_ref": "sec_001", "section_title": "Title", "snippet": "original snippet"},
    ])
    # section_content 不存在或为空
    section_content_map = {"sec_001": ""}

    enriched = enrich_hits_by_section(
        hits_raw=hits_raw,
        section_content_map=section_content_map,
        query="nonexistent",
    )

    assert len(enriched) == 1
    assert _hit_snippet(enriched[0]) == "original snippet"


@pytest.mark.unit
def test_enrich_hits_by_section_missing_section_ref() -> None:
    """验证缺少 section_ref 的 hit 会被忽略。"""

    from alpha.engine.processors.search_utils import enrich_hits_by_section

    hits_raw = _search_hits([
        {"section_title": "Title", "snippet": "snippet"},  # 缺少 section_ref
        {"section_ref": "", "snippet": "empty ref"},  # 空 section_ref
    ])
    section_content_map = {}

    enriched = enrich_hits_by_section(
        hits_raw=hits_raw,
        section_content_map=section_content_map,
        query="query",
    )

    assert enriched == []


@pytest.mark.unit
def test_enrich_hits_by_section_without_page_no() -> None:
    """验证缺少有效 page_no 时不包含该字段。"""

    from alpha.engine.processors.search_utils import enrich_hits_by_section

    hits_raw = _search_hits([
        {"section_ref": "sec_001", "section_title": "Title", "snippet": "keyword"},
    ])
    section_content_map = {"sec_001": "This is a test with keyword inside."}

    enriched = enrich_hits_by_section(
        hits_raw=hits_raw,
        section_content_map=section_content_map,
        query="keyword",
        per_section_limit=1,
        snippet_max_chars=100,
    )

    assert len(enriched) >= 1
    # page_no 不应该存在
    assert "page_no" not in enriched[0] or enriched[0].get("page_no") is None


@pytest.mark.unit
def test_normalize_for_dedup_removes_special_chars() -> None:
    """验证 normalize_for_dedup 移除特殊字符用于去重。"""

    from alpha.engine.processors.search_utils import normalize_for_dedup

    text1 = "Re-purchase  Agreement!"
    text2 = "repurchase agreement"

    assert normalize_for_dedup(text1) == normalize_for_dedup(text2)


@pytest.mark.unit
def test_cap_per_section_with_zero_or_negative_limit() -> None:
    """验证 cap_per_section 的边界情况。"""

    from alpha.engine.processors.search_utils import cap_per_section

    snippets = ["a", "b", "c"]

    # 限制为 0
    assert cap_per_section(snippets, 0) == []

    # 负数限制
    assert cap_per_section(snippets, -1) == []


@pytest.mark.unit
def test_dedup_snippets_empty_after_normalization() -> None:
    """验证规范化后为空的片段被过滤掉。"""

    from alpha.engine.processors.search_utils import dedup_snippets

    snippets = ["   ", "\t\n", "valid snippet"]
    deduped = dedup_snippets(snippets)

    assert len(deduped) == 1
    assert deduped[0] == "valid snippet"


@pytest.mark.unit
def test_extract_snippets_fallback_when_no_sentences() -> None:
    """验证没有句子分隔符时触发回退逻辑。"""

    from alpha.engine.processors.search_utils import extract_query_anchored_snippets

    # 构造一个只有空白字符的文本，导致无法切分句子，但有 query 匹配
    content = "keyword"  # 没有句子分隔符
    snippets = extract_query_anchored_snippets(content, "keyword", 100, 2)

    # 应该触发回退逻辑
    assert len(snippets) > 0


@pytest.mark.unit
def test_split_sentence_spans_with_empty_sentences() -> None:
    """验证句子切分时跳过空句子。"""

    from alpha.engine.processors.search_utils import split_sentences

    # 连续的标点符号会产生空句子
    text = "。。First sentence。"
    sentences = split_sentences(text)

    # 空句子应该被过滤掉
    assert all(s.strip() for s in sentences)


@pytest.mark.unit
def test_locate_sentence_index_no_match() -> None:
    """验证定位句子索引失败时的行为。"""

    from alpha.engine.processors.search_utils import (
        extract_query_anchored_snippets,
    )

    # 创建一个场景：query 在句子边界外（理论上不太可能，但需要测试）
    # 通过构造特殊文本来测试这个边界情况
    content = "First。Second。Third。"
    
    # 即使 query 不在标准位置，也应该能处理
    snippets = extract_query_anchored_snippets(content, "First", 50, 2)
    assert len(snippets) > 0


@pytest.mark.unit
def test_build_snippet_query_lost_in_window() -> None:
    """验证 snippet 构建时 query 丢失的情况。"""

    from alpha.engine.processors.search_utils import build_snippet_from_sentence_window

    # 构造一个场景：query 不在命中句中（模拟分句异常）
    sentences = ["This is first.", "This is second.", "This is third."]
    
    # 指定索引1但 query 不在该句中
    snippet = build_snippet_from_sentence_window(sentences, 1, "nonexistent", 50)
    
    # 应该触发截断逻辑
    assert len(snippet) <= 50


@pytest.mark.unit
def test_join_sentence_window_invalid_ranges() -> None:
    """验证 _join_sentence_window 的边界检查。"""

    from alpha.engine.processors.search_utils import build_snippet_from_sentence_window

    sentences = ["First.", "Second.", "Third."]
    
    # 通过构造超长的单句来测试窗口扩展逻辑
    long_sentences = ["A" * 100 + ".",  "B" * 100 + " keyword " + "C" * 100 + "."]
    snippet = build_snippet_from_sentence_window(long_sentences, 1, "keyword", 150)
    
    # 应该能正确截断
    assert len(snippet) <= 150
    assert "keyword" in snippet.lower()


@pytest.mark.unit
def test_truncate_around_query_edge_cases() -> None:
    """验证 _truncate_around_query 的各种边界情况。"""

    from alpha.engine.processors.search_utils import extract_query_anchored_snippets

    # 测试 query 在文本开头
    content = "keyword at start followed by long text " + "A" * 500
    snippets = extract_query_anchored_snippets(content, "keyword", 100, 1)
    assert len(snippets) > 0
    assert len(snippets[0]) <= 100

    # 测试 query 在文本末尾  
    content = "A" * 500 + " keyword at end"
    snippets = extract_query_anchored_snippets(content, "keyword", 100, 1)
    assert len(snippets) > 0
    assert "keyword" in snippets[0].lower()


@pytest.mark.unit
def test_dedup_snippets_with_special_chars_normalization() -> None:
    """验证去重时特殊字符的规范化。"""

    from alpha.engine.processors.search_utils import dedup_snippets

    # 包含各种特殊字符和空白的片段
    snippets = [
        "!!!keyword###",
        "___keyword___",
        "   keyword   ",
    ]
    deduped = dedup_snippets(snippets)

    # 规范化后这些都应该被视为重复
    assert len(deduped) == 1


@pytest.mark.unit
def test_pick_first_positive_page_no_edge_cases() -> None:
    """验证选择首个有效页码的边界情况。"""

    from alpha.engine.processors.search_utils import enrich_hits_by_section

    # 测试多个 hit 中只有一个有效页码
    hits_raw = _search_hits([
        {"section_ref": "sec_001", "snippet": "text", "page_no": 0},  # 无效
        {"section_ref": "sec_001", "snippet": "text", "page_no": -1},  # 无效
        {"section_ref": "sec_001", "snippet": "text", "page_no": 5},  # 有效
    ])
    section_content_map = {"sec_001": "This is text content."}

    enriched = enrich_hits_by_section(
        hits_raw=hits_raw,
        section_content_map=section_content_map,
        query="text",
        per_section_limit=5,
        snippet_max_chars=100,
    )

    # 应该使用第一个正整数页码
    assert any(hit.get("page_no") == 5 for hit in enriched)


@pytest.mark.unit
def test_fallback_char_window_multiple_matches() -> None:
    """验证字符窗口回退时处理多个匹配。"""

    from alpha.engine.processors.search_utils import extract_query_anchored_snippets

    # 没有句子标点，多次出现 keyword
    content = "keyword here and keyword there and keyword everywhere"
    snippets = extract_query_anchored_snippets(content, "keyword", 30, 5)

    # 应该返回多个片段但受限于 max_per_section
    assert 1 <= len(snippets) <= 5
    assert all("keyword" in s.lower() for s in snippets)


@pytest.mark.unit
def test_normalize_whitespace_only_input() -> None:
    """验证只包含空白字符的输入。"""

    from alpha.engine.processors.search_utils import extract_query_anchored_snippets

    # 只有空白字符
    assert extract_query_anchored_snippets("   \n\t  ", "query", 100, 2) == []


@pytest.mark.unit
def test_text_without_any_sentence_endings() -> None:
    """验证完全没有句子结束符的文本。"""

    from alpha.engine.processors.search_utils import extract_query_anchored_snippets

    # 没有任何句子结束符，应该回退到字符窗口
    content = "keyword text without punctuation"
    snippets = extract_query_anchored_snippets(content, "keyword", 100, 2)
    
    assert len(snippets) > 0
    assert "keyword" in snippets[0].lower()


@pytest.mark.unit
def test_query_not_in_matched_sentence() -> None:
    """验证 query 不在匹配句子中时的截断逻辑。"""

    from alpha.engine.processors.search_utils import build_snippet_from_sentence_window

    # 创建场景：sentence_index指向的句子不包含query
    sentences = ["First long sentence without target word。", 
                 "Second sentence also without target。",
                 "Third sentence here。"]
    
    # 尝试从不包含 query 的句子构建 snippet
    snippet = build_snippet_from_sentence_window(sentences, 0, "nonexist", 50)
    
    # 应该返回截断后的结果
    assert len(snippet) <= 50


@pytest.mark.unit
def test_sentence_window_expansion_both_sides() -> None:
    """验证句子窗口向两侧扩展的逻辑。"""

    from alpha.engine.processors.search_utils import build_snippet_from_sentence_window

    # 短句子，应该能扩展多个
    sentences = ["A。", "B keyword。", "C。", "D。", "E。"]
    
    # 从索引1开始，应该能向两侧扩展
    snippet = build_snippet_from_sentence_window(sentences, 1, "keyword", 100)
    
    # 应该包含多个句子
    assert "A" in snippet or "C" in snippet  # 至少扩展了一侧


@pytest.mark.unit
def test_dedup_with_longer_replaces_shorter() -> None:
    """验证去重时更长的片段替换更短的片段。"""

    from alpha.engine.processors.search_utils import dedup_snippets

    # 第一个片段较长，第二个是其子串
    snippets = [
        "short text",
        "This is a much longer piece of text that contains short text inside it",
    ]
    deduped = dedup_snippets(snippets)

    # 应该保留更长的那个
    assert len(deduped) == 1
    assert "longer" in deduped[0]


@pytest.mark.unit
def test_dedup_with_only_special_chars() -> None:
    """验证只包含特殊字符规范化后为空的情况。"""

    from alpha.engine.processors.search_utils import dedup_snippets

    snippets = ["!!!###", "@@@$$$", "valid text"]
    deduped = dedup_snippets(snippets)

    # 只有特殊字符的应该被过滤
    assert len(deduped) == 1
    assert deduped[0] == "valid text"


@pytest.mark.unit
def test_truncate_with_zero_or_negative_max_chars() -> None:
    """验证 max_chars 为 0 或负数时的截断行为。"""

    from alpha.engine.processors.search_utils import build_snippet_from_sentence_window

    sentences = ["Some text。", "More text。"]
    
    # max_chars = 0
    assert build_snippet_from_sentence_window(sentences, 0, "query", 0) == ""
    
    # max_chars < 0
    assert build_snippet_from_sentence_window(sentences, 0, "query", -10) == ""


@pytest.mark.unit
def test_truncate_when_query_is_empty() -> None:
    """验证 query 为空时的截断行为。"""

    from alpha.engine.processors.search_utils import build_snippet_from_sentence_window

    # 构造超长单句，query 为空
    long_sentence = ["A" * 200]
    snippet = build_snippet_from_sentence_window(long_sentence, 0, "", 50)
    
    # 应该直接截断前 50 个字符
    assert len(snippet) <= 50


@pytest.mark.unit
def test_truncate_when_query_not_in_text() -> None:
    """验证文本中不包含 query 时的截断行为。"""

    from alpha.engine.processors.search_utils import build_snippet_from_sentence_window

    # query 完全不存在于文本中
    long_sentence = ["B" * 200]
    snippet = build_snippet_from_sentence_window(long_sentence, 0, "nonexistent", 50)
    
    # 应该直接截断前 50 个字符
    assert len(snippet) <= 50


@pytest.mark.unit
def test_split_sentences_consecutive_punctuation() -> None:
    """验证连续标点符号产生空句子的情况。"""

    from alpha.engine.processors.search_utils import split_sentences

    # 连续标点
    text = "。。。Real content。！？"
    sentences = split_sentences(text)
    
    # 空句子应该被过滤掉
    assert all(s.strip() for s in sentences)
    assert any("Real content" in s for s in sentences)


@pytest.mark.unit 
def test_extract_with_whitespace_only_content() -> None:
    """验证只有空白字符的 content。"""

    from alpha.engine.processors.search_utils import extract_query_anchored_snippets

    # normalized_content 会是空字符串
    snippets = extract_query_anchored_snippets("   \n\n\t\t   ", "query", 100, 2)
    assert snippets == []


@pytest.mark.unit
def test_extract_with_none_query() -> None:
    """验证 query 为 None 的情况。"""

    from alpha.engine.processors.search_utils import extract_query_anchored_snippets

    # query=None should be handled
    snippets = extract_query_anchored_snippets("some content", None, 100, 2)  # type: ignore
    assert snippets == []


@pytest.mark.unit
def test_sentence_window_when_hit_not_in_sentence() -> None:
    """验证命中位置无法定位到句子时的情况。"""

    from alpha.engine.processors.search_utils import extract_query_anchored_snippets

    # 构造一个特殊场景：在句子切分边界附近的匹配
    # 这种情况下 _locate_sentence_index 可能返回 None
    content = "Test。"  # 极短，可能导致边界问题
    snippets = extract_query_anchored_snippets(content, "T", 100, 2)
    
    # 应该能处理，即使遇到边界情况
    assert isinstance(snippets, list)
