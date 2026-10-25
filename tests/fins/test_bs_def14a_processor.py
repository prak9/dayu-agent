"""bs_def14a_processor 模块单元测试。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import pytest

from alpha.fins.processors import bs_def14a_processor as module


@pytest.mark.unit
def test_detect_leading_toc_cluster_basic_branches() -> None:
    """验证 TOC 聚簇检测的命中与非命中分支。"""

    assert module._detect_leading_toc_cluster([], text_len=1000) == 0
    assert module._detect_leading_toc_cluster([(10, "A"), (20, "B")], text_len=1000) == 0

    markers: list[tuple[int, str | None]] = [(100, "A"), (180, "B"), (260, "C"), (4000, "D")]
    cluster_end = module._detect_leading_toc_cluster(markers, text_len=100000)
    assert cluster_end == 260


@pytest.mark.unit
def test_append_supplementary_markers_adds_and_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证补充 marker 追加与去重。"""

    monkeypatch.setattr(
        module,
        "_SUPPLEMENTARY_MARKERS",
        (
            ("M1", re.compile(r"m1")),
            ("M2", re.compile(r"m2")),
        ),
    )
    monkeypatch.setattr(module, "_dedupe_markers", lambda markers: sorted(set(markers)))

    markers = module._append_supplementary_markers([(5, "base")], "x m1 y m2 z")
    assert (5, "base") in markers
    assert any(title == "M1" for _, title in markers)
    assert any(title == "M2" for _, title in markers)


@pytest.mark.unit
def test_rebuild_markers_after_toc_with_voting_enhanced_and_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 TOC 后重扫可补充 Voting 与尾段 marker。"""

    monkeypatch.setattr(module, "_TOC_CLUSTER_MIN_SIZE", 3)
    monkeypatch.setattr(module, "_select_def14a_proposal_markers", lambda text: [(1, 10)])
    monkeypatch.setattr(
        module,
        "_DEF14A_SECTION_MARKERS",
        (
            ("Executive Compensation", re.compile(r"exec")),
        ),
    )
    monkeypatch.setattr(
        module,
        "_SUPPLEMENTARY_MARKERS",
        (
            ("Supplement", re.compile(r"supp")),
        ),
    )
    monkeypatch.setattr(module, "_VOTING_ENHANCED_PATTERN", re.compile(r"voting matters"))
    monkeypatch.setattr(module, "_find_lettered_marker_after", lambda *args: (200, "Annex"))
    monkeypatch.setattr(module, "_find_marker_after", lambda *args: (250, "SIGNATURE"))
    monkeypatch.setattr(module, "_dedupe_markers", lambda markers: sorted(set(markers)))

    text = "prefix exec and supp and voting matters and tail"
    actual = module._rebuild_markers_after_toc(text, body_start=0)

    titles = [title for _, title in actual]
    assert "Proposal No. 1" in titles
    assert "Executive Compensation" in titles
    assert "Supplement" in titles
    assert "Voting Procedures" in titles
    assert "Annex" in titles
    assert "SIGNATURE" in titles


@pytest.mark.unit
def test_rebuild_markers_after_toc_returns_empty_when_too_few(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证重扫 marker 不足时返回空列表。"""

    monkeypatch.setattr(module, "_TOC_CLUSTER_MIN_SIZE", 3)
    monkeypatch.setattr(module, "_select_def14a_proposal_markers", lambda text: [])
    monkeypatch.setattr(module, "_DEF14A_SECTION_MARKERS", ())
    monkeypatch.setattr(module, "_SUPPLEMENTARY_MARKERS", ())
    monkeypatch.setattr(module, "_find_lettered_marker_after", lambda *args: None)
    monkeypatch.setattr(module, "_find_marker_after", lambda *args: None)
    monkeypatch.setattr(module, "_dedupe_markers", lambda markers: markers)

    assert module._rebuild_markers_after_toc("plain text", body_start=10) == []


@pytest.mark.unit
def test_find_adequate_keyword_match_selects_valid_candidate() -> None:
    """验证关键词重扫会跳过过短候选并选择合格匹配。"""

    pattern = re.compile(r"keyword")
    text = "keyword xx keyword " + ("a" * 200) + " keyword " + ("b" * 800)
    all_positions = [0, 10, 220, 4000]

    actual = module._find_adequate_keyword_match(
        pattern=pattern,
        full_text=text,
        current_pos=0,
        all_marker_positions=all_positions,
        min_section=100,
    )

    assert actual is not None
    assert actual >= 10


@pytest.mark.unit
def test_rescan_undersized_keyword_markers_replaces_position(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证过小 section 的关键词 marker 会被后续匹配替换。"""

    monkeypatch.setattr(module, "_KEYWORD_MARKER_TITLES", frozenset({"K"}))
    monkeypatch.setattr(module, "_SECTION_PATTERN_MAP", {"K": re.compile(r"k")})
    monkeypatch.setattr(module, "_DEFAULT_RESCAN_THRESHOLD", 50)
    monkeypatch.setattr(module, "_RESCAN_THRESHOLDS", {})
    monkeypatch.setattr(module, "_dedupe_markers", lambda markers: sorted(set(markers)))
    monkeypatch.setattr(module, "_find_adequate_keyword_match", lambda *args, **kwargs: 120)

    markers: list[tuple[int, str | None]] = [(10, "K"), (30, "Other")]
    updated = module._rescan_undersized_keyword_markers(markers, "k" * 500)

    assert (120, "K") in updated


@pytest.mark.unit
def test_build_bs_def14a_markers_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证主流程在不同 TOC 识别路径的行为。"""

    monkeypatch.setattr(module, "_TOC_CLUSTER_MIN_SIZE", 3)
    monkeypatch.setattr(module, "_TOC_CLUSTER_SKIP_CHARS", 50)
    monkeypatch.setattr(module, "_MAX_CLUSTER_ITERATIONS", 2)

    monkeypatch.setattr(module, "_build_def14a_markers", lambda text: [(1, "A"), (2, "B")])
    monkeypatch.setattr(module, "_append_supplementary_markers", lambda markers, text: markers)
    short_result = module._build_bs_def14a_markers("text")
    assert short_result == [(1, "A"), (2, "B")]

    monkeypatch.setattr(module, "_build_def14a_markers", lambda text: [(1, "A"), (10, "B"), (20, "C")])
    monkeypatch.setattr(module, "_detect_leading_toc_cluster", lambda markers, text_len: 0)
    monkeypatch.setattr(module, "_rescan_undersized_keyword_markers", lambda markers, text: markers + [(99, "R")])
    no_toc_result = module._build_bs_def14a_markers("text")
    assert (99, "R") in no_toc_result

    sequence = iter([100, 0])
    monkeypatch.setattr(module, "_detect_leading_toc_cluster", lambda markers, text_len: next(sequence))
    monkeypatch.setattr(module, "_rebuild_markers_after_toc", lambda text, start: [(300, "X"), (400, "Y"), (500, "Z")])
    monkeypatch.setattr(module, "_rescan_undersized_keyword_markers", lambda markers, text: markers)
    toc_result = module._build_bs_def14a_markers("t" * 2000)
    assert toc_result == [(300, "X"), (400, "Y"), (500, "Z")]


@pytest.mark.unit
def test_bs_def14a_supports_and_build_markers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """验证类方法 supports 与实例 _build_markers 代理行为。"""

    class _SourceStub:
        """最小 source 桩。"""

        uri = "local://x.html"
        media_type = "text/html"
        content_length = 0
        etag = None

        def open(self) -> Any:
            """打开资源。

            Args:
                无。

            Returns:
                无。

            Raises:
                OSError: 固定抛错。
            """

            raise OSError("not used")

        def materialize(self, suffix: Optional[str] = None) -> Path:
            """物化文件路径。

            Args:
                suffix: 可选后缀。

            Returns:
                临时文件路径。

            Raises:
                OSError: 文件不存在时抛出。
            """

            del suffix
            return tmp_path / "a.html"

    monkeypatch.setattr(module, "_check_special_form_support", lambda *args, **kwargs: True)
    assert module.BsDef14AFormProcessor.supports(_SourceStub(), form_type="DEF 14A") is True

    monkeypatch.setattr(module.FinsBSProcessor, "__init__", lambda self, **kwargs: None)
    monkeypatch.setattr(module.BsDef14AFormProcessor, "_initialize_virtual_sections", lambda self, **kwargs: None)
    monkeypatch.setattr(module, "_build_bs_def14a_markers", lambda text: [(1, "A")])

    processor = module.BsDef14AFormProcessor(_SourceStub(), form_type="DEF 14A", media_type="text/html")
    assert processor._build_markers("hello") == [(1, "A")]
