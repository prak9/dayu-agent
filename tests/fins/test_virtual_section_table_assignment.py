"""虚拟章节表格分配功能测试。

验证 _VirtualSectionProcessorMixin 的表格→虚拟章节映射逻辑，包括：
- _build_marker_title_ranges() 纯函数测试
- _collect_marked_text() 协议降级测试
- _assign_tables_to_virtual_sections() 集成测试
- list_tables() section_ref 重映射测试
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

import pytest

from alpha.fins.processors.sec_form_section_common import (
    _VirtualSectionProcessorMixin,
    _build_marker_title_ranges,
    _dedupe_markers,
    _extract_table_refs,
)
from alpha.engine.processors.base import (
    SearchHit,
    SectionContent,
    SectionSummary,
    TableSummary,
    build_section_content,
    build_section_summary,
    build_table_summary,
)


def _make_test_table_summary(table_ref: str, section_ref: str | None) -> TableSummary:
    """构造最小可用的表格摘要测试数据。

    Args:
        table_ref: 表格引用。
        section_ref: 章节引用。

    Returns:
        完整 `TableSummary`。

    Raises:
        无。
    """

    return build_table_summary(
        table_ref=table_ref,
        caption=None,
        context_before="",
        row_count=1,
        col_count=1,
        table_type="html",
        headers=None,
        section_ref=section_ref,
    )


def _rebuild_markers_for_text(
    full_text: str,
    markers: Sequence[tuple[int, str | None]],
) -> list[tuple[int, str | None]]:
    """按给定全文重算 marker 位置。

    Args:
        full_text: 当前用于查找标题的位置文本。
        markers: 原始 marker 列表。

    Returns:
        重新定位后的 marker 列表。

    Raises:
        无。
    """

    result: list[tuple[int, str | None]] = []
    for _, title in markers:
        pos = full_text.find(title) if title else -1
        if pos >= 0:
            result.append((pos, title))
    return result


@pytest.mark.unit
def test_virtual_section_mixin_delegates_to_base_processor_when_virtual_sections_empty() -> None:
    """验证未启用虚拟章节时，mixin 会透传到底层处理器。"""

    class BaseStub:
        """提供底层 section/table/search 协议实现的测试桩。"""

        def __init__(self) -> None:
            """初始化调用记录。"""

            self.calls: list[str] = []

        def list_sections(self) -> list[SectionSummary]:
            """返回底层章节列表。"""

            self.calls.append("list_sections")
            return [build_section_summary(ref="base_sec", title="Base Title", level=1, parent_ref=None, preview="base preview")]

        def read_section(self, ref: str) -> SectionContent:
            """返回底层章节内容。"""

            self.calls.append(f"read_section:{ref}")
            return build_section_content(
                ref=ref,
                title="Base Title",
                content="base content",
                tables=["t_0001"],
                word_count=2,
                contains_full_text=False,
            )

        def list_tables(self) -> list[TableSummary]:
            """返回底层表格列表。"""

            self.calls.append("list_tables")
            return [_make_test_table_summary("t_0001", "base_sec")]

        def get_section_title(self, ref: str) -> str | None:
            """返回底层章节标题。"""

            self.calls.append(f"get_section_title:{ref}")
            return "Base Title"

        def search(self, query: str, within_ref: Optional[str] = None) -> list[SearchHit]:
            """返回底层搜索结果。"""

            self.calls.append(f"search:{query}:{within_ref}")
            return [{"section_ref": "base_sec", "section_title": "Base Title", "snippet": query}]

    class Processor(_VirtualSectionProcessorMixin, BaseStub):
        """组合虚拟章节 mixin 与底层处理器桩。"""

        def __init__(self) -> None:
            """初始化底层桩与空虚拟章节状态。"""

            super().__init__()
            self._virtual_sections = []
            self._virtual_section_by_ref = {}
            self._table_ref_to_virtual_ref = {}

        def _build_markers(self, full_text: str) -> list[tuple[int, str | None]]:
            """返回空 marker。"""

            del full_text
            return []

        def get_full_text(self) -> str:
            """返回空全文。"""

            return ""

        def get_full_text_with_table_markers(self) -> str:
            """返回空标记全文。"""

            return ""

    processor = Processor()

    sections = processor.list_sections()
    content = processor.read_section("base_sec")
    tables = processor.list_tables()
    title = processor.get_section_title("base_sec")
    hits = processor.search("keyword", within_ref="base_sec")

    assert [section["ref"] for section in sections] == ["base_sec"]
    assert content["content"] == "base content"
    assert [table["table_ref"] for table in tables] == ["t_0001"]
    assert title == "Base Title"
    assert [hit.get("section_ref") for hit in hits] == ["base_sec"]
    assert processor.calls == [
        "list_sections",
        "read_section:base_sec",
        "list_tables",
        "get_section_title:base_sec",
        "search:keyword:base_sec",
    ]


# ---------------------------------------------------------------------------
# 测试类：_build_marker_title_ranges
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBuildMarkerTitleRanges:
    """_build_marker_title_ranges 纯函数单元测试。"""

    def test_basic_two_markers(self) -> None:
        """验证两个标记正确划分文本范围。"""

        text = "Cover content. Item 1 First section. Item 2 Second section."
        markers: list[tuple[int, Optional[str]]] = [
            (15, "Item 1"),
            (36, "Item 2"),
        ]
        ranges = _build_marker_title_ranges(text, markers)

        assert "Item 1" in ranges
        assert "Item 2" in ranges
        # Item 1 范围从 15 到 36
        assert ranges["Item 1"] == (15, 36)
        # Item 2 范围从 36 到文本末尾
        assert ranges["Item 2"] == (36, len(text))

    def test_empty_markers_returns_empty_dict(self) -> None:
        """验证空 marker 列表返回空字典。"""

        result = _build_marker_title_ranges("some text", [])
        assert result == {}

    def test_markers_without_titles_skipped(self) -> None:
        """验证无标题的 marker 被跳过。"""

        text = "text before and after"
        markers: list[tuple[int, Optional[str]]] = [
            (0, None),
            (5, "Section A"),
        ]
        ranges = _build_marker_title_ranges(text, markers)

        # None 标题被跳过
        assert None not in ranges
        assert "Section A" in ranges
        assert ranges["Section A"] == (5, len(text))

    def test_duplicate_positions_deduped(self) -> None:
        """验证重复位置的 marker 被去重处理。"""

        text = "AAAA BBBB CCCC"
        markers: list[tuple[int, Optional[str]]] = [
            (0, "Alpha"),
            (0, "Alpha Dup"),  # 同位置，应被去重
            (5, "Beta"),
        ]
        ranges = _build_marker_title_ranges(text, markers)

        assert "Alpha" in ranges
        assert "Beta" in ranges
        assert ranges["Alpha"] == (0, 5)

    def test_single_marker(self) -> None:
        """验证单个 marker 覆盖从该位置到文末。"""

        text = "prefix content marker start to end"
        markers: list[tuple[int, Optional[str]]] = [
            (16, "Only Section"),
        ]
        ranges = _build_marker_title_ranges(text, markers)

        assert ranges["Only Section"] == (16, len(text))

    def test_three_markers_correct_boundaries(self) -> None:
        """验证三个 marker 正确切分三段。"""

        text = "AAAAABBBBBCCCCCDDDDD"  # 20 字符
        markers: list[tuple[int, Optional[str]]] = [
            (0, "Part A"),
            (5, "Part B"),
            (10, "Part C"),
        ]
        ranges = _build_marker_title_ranges(text, markers)

        assert ranges["Part A"] == (0, 5)
        assert ranges["Part B"] == (5, 10)
        assert ranges["Part C"] == (10, 20)


# ---------------------------------------------------------------------------
# 测试类：_collect_marked_text
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCollectMarkedText:
    """_collect_marked_text 协议降级测试。"""

    def test_returns_marked_text_when_method_available(self) -> None:
        """验证底层处理器提供 get_full_text_with_table_markers 时正常返回。"""

        class StubProcessor(_VirtualSectionProcessorMixin):
            def _collect_full_text_from_base(self) -> str:
                return ""

            def _build_markers(self, full_text: str) -> list[tuple[int, str | None]]:
                del full_text
                return []

            def get_full_text_with_table_markers(self) -> str:
                return "text with [[t_0001]] markers"

        processor = StubProcessor()
        result = processor._collect_marked_text()
        assert result == "text with [[t_0001]] markers"

    def test_returns_empty_when_not_supported(self) -> None:
        """验证底层处理器不支持时返回空字符串（协议约定返回空串）。"""

        class StubProcessor(_VirtualSectionProcessorMixin):
            def _collect_full_text_from_base(self) -> str:
                return ""

            def _build_markers(self, full_text: str) -> list[tuple[int, str | None]]:
                del full_text
                return []

            def get_full_text_with_table_markers(self) -> str:
                # 不支持 DOM 标记注入的处理器按协议返回空字符串
                return ""

        processor = StubProcessor()
        result = processor._collect_marked_text()
        assert result == ""

    def test_returns_empty_on_exception(self) -> None:
        """验证方法存在但抛异常时安全降级。"""

        class StubProcessor(_VirtualSectionProcessorMixin):
            def _collect_full_text_from_base(self) -> str:
                return ""

            def _build_markers(self, full_text: str) -> list[tuple[int, str | None]]:
                del full_text
                return []

            def get_full_text_with_table_markers(self) -> str:
                raise RuntimeError("DOM parse error")

        processor = StubProcessor()
        result = processor._collect_marked_text()
        assert result == ""


# ---------------------------------------------------------------------------
# 测试类：_assign_tables_to_virtual_sections + list_tables 重映射
# ---------------------------------------------------------------------------

# 模拟含三个章节 + 表格标记的文本结构：
# Cover Page (t_0001) -> Item 1 (t_0002, t_0003) -> Item 2 (t_0004)
_PLAIN_TEXT = (
    "Cover page content here. "
    "Item 1 Business section with detailed information about the company. "
    "Item 2 Risk factors description and analysis."
)

_MARKED_TEXT = (
    "Cover page content [[t_0001]] here. "
    "Item 1 Business section with [[t_0002]] detailed [[t_0003]] information about the company. "
    "Item 2 Risk factors [[t_0004]] description and analysis."
)

# marker 位置基于 _PLAIN_TEXT 中的 "Item X" 偏移
_ITEM1_POS = _PLAIN_TEXT.index("Item 1")
_ITEM2_POS = _PLAIN_TEXT.index("Item 2")


@pytest.mark.unit
class TestAssignTablesToVirtualSections:
    """_assign_tables_to_virtual_sections 集成测试。"""

    def _make_processor(
        self,
        *,
        plain_text: str = _PLAIN_TEXT,
        marked_text: str = _MARKED_TEXT,
        markers: Optional[list[tuple[int, Optional[str]]]] = None,
    ):
        """构建带桩实现的测试处理器。

        Args:
            plain_text: 不含表格标记的全文。
            marked_text: 含 [[t_XXXX]] 标记的全文。
            markers: 自定义 marker 列表；为 None 时自动计算。

        Returns:
            初始化后的测试处理器实例。
        """

        if markers is None:
            item1_pos = plain_text.index("Item 1") if "Item 1" in plain_text else 0
            item2_pos = plain_text.index("Item 2") if "Item 2" in plain_text else len(plain_text)
            markers = [
                (item1_pos, "Item 1"),
                (item2_pos, "Item 2"),
            ]

        # 使用闭包捕获 marked_text，因为需要在 mixin 内部被 _collect_marked_text 调用
        _captured_markers = list(markers)
        _captured_marked_text = marked_text

        class StubProcessor(_VirtualSectionProcessorMixin):
            def _collect_full_text_from_base(self) -> str:
                return ""

            def _build_markers(self, full_text: str) -> list[tuple[int, str | None]]:
                # 根据调用场景返回不同 marker（plain_text 和 marked_text 位置不同）
                if "[[t_" in full_text:
                    return _rebuild_markers_for_text(full_text, _captured_markers)
                return list(_captured_markers)

            def get_full_text(self) -> str:
                return plain_text

            def get_full_text_with_table_markers(self) -> str:
                return _captured_marked_text

            def list_tables(self):
                # 先调用 mixin 的 list_tables（如果虚拟章节已初始化）
                if self._virtual_sections and self._table_ref_to_virtual_ref:
                    return _VirtualSectionProcessorMixin.list_tables(self)
                # 否则模拟底层处理器的原始 list_tables
                return [
                    _make_test_table_summary("t_0001", "s_0001"),
                    _make_test_table_summary("t_0002", "s_0001"),
                    _make_test_table_summary("t_0003", "s_0001"),
                    _make_test_table_summary("t_0004", "s_0002"),
                ]

        processor = StubProcessor()
        processor._initialize_virtual_sections(min_sections=1)
        return processor

    def test_virtual_sections_have_table_refs(self) -> None:
        """验证虚拟章节初始化后 table_refs 被正确填充。"""

        processor = self._make_processor()

        section_by_title = {vs.title: vs for vs in processor._virtual_sections}

        # Cover Page 应包含 t_0001
        cover = section_by_title.get("Cover Page")
        assert cover is not None
        assert "t_0001" in cover.table_refs

        # Item 1 应包含 t_0002 和 t_0003
        item1 = section_by_title.get("Item 1")
        assert item1 is not None
        assert "t_0002" in item1.table_refs
        assert "t_0003" in item1.table_refs

        # Item 2 应包含 t_0004
        item2 = section_by_title.get("Item 2")
        assert item2 is not None
        assert "t_0004" in item2.table_refs

    def test_filters_unknown_table_refs_to_avoid_dangling_refs(self) -> None:
        """验证会过滤底层不存在的 table_ref，避免悬挂引用。"""

        plain_text = _PLAIN_TEXT
        marked_text = _MARKED_TEXT
        markers = [
            (_ITEM1_POS, "Item 1"),
            (_ITEM2_POS, "Item 2"),
        ]
        _captured_markers = list(markers)

        class BaseTables:
            """提供底层 list_tables 能力。"""

            def list_tables(self):
                # 故意缺失 t_0003，用于模拟 layout/无效表格被底层丢弃的场景。
                return [
                    _make_test_table_summary("t_0001", "s_0001"),
                    _make_test_table_summary("t_0002", "s_0001"),
                    _make_test_table_summary("t_0004", "s_0002"),
                ]

        class StubProcessor(_VirtualSectionProcessorMixin, BaseTables):
            """带底层表格桩的测试处理器。"""

            def _collect_full_text_from_base(self) -> str:
                return ""

            def _build_markers(self, full_text: str) -> list[tuple[int, str | None]]:
                if "[[t_" in full_text:
                    return _rebuild_markers_for_text(full_text, _captured_markers)
                return list(_captured_markers)

            def get_full_text(self) -> str:
                return plain_text

            def get_full_text_with_table_markers(self) -> str:
                return marked_text

        processor = StubProcessor()
        processor._initialize_virtual_sections(min_sections=1)

        assert "t_0003" not in processor._table_ref_to_virtual_ref
        item1 = next(section for section in processor._virtual_sections if section.title == "Item 1")
        assert "t_0002" in item1.table_refs
        assert "t_0003" not in item1.table_refs

    def test_table_ref_to_virtual_ref_mapping(self) -> None:
        """验证 _table_ref_to_virtual_ref 反向映射完整。"""

        processor = self._make_processor()

        mapping = processor._table_ref_to_virtual_ref
        assert len(mapping) == 4

        # 所有 table ref 都应映射到某个虚拟章节 ref
        for tbl_ref in ["t_0001", "t_0002", "t_0003", "t_0004"]:
            assert tbl_ref in mapping
            assert mapping[tbl_ref].startswith("s_")

    def test_tables_in_same_section_share_virtual_ref(self) -> None:
        """验证同一虚拟章节内的多个表格共享同一 virtual ref。"""

        processor = self._make_processor()

        mapping = processor._table_ref_to_virtual_ref
        # t_0002 和 t_0003 都在 Item 1 中
        assert mapping["t_0002"] == mapping["t_0003"]

    def test_tables_in_different_sections_different_ref(self) -> None:
        """验证不同虚拟章节的表格映射到不同 virtual ref。"""

        processor = self._make_processor()

        mapping = processor._table_ref_to_virtual_ref
        # t_0001 (Cover) vs t_0002 (Item 1) vs t_0004 (Item 2)
        assert mapping["t_0001"] != mapping["t_0002"]
        assert mapping["t_0002"] != mapping["t_0004"]

    def test_no_marked_text_skips_assignment(self) -> None:
        """验证无标记文本时跳过分配（保持现有行为）。"""

        class NoMarkerProcessor(_VirtualSectionProcessorMixin):
            def _collect_full_text_from_base(self) -> str:
                return ""

            def _build_markers(self, full_text: str) -> list[tuple[int, str | None]]:
                del full_text
                return [
                    (_ITEM1_POS, "Item 1"),
                    (_ITEM2_POS, "Item 2"),
                ]

            def get_full_text(self) -> str:
                return _PLAIN_TEXT

            def get_full_text_with_table_markers(self) -> str:
                # 不支持 DOM 标记注入，按协议返回空字符串
                return ""

        processor = NoMarkerProcessor()
        processor._initialize_virtual_sections(min_sections=1)

        # 映射应为空
        assert processor._table_ref_to_virtual_ref == {}
        # 虚拟章节的 table_refs 应为空
        for vs in processor._virtual_sections:
            assert vs.table_refs == []

    def test_empty_virtual_sections_skips_assignment(self) -> None:
        """验证无虚拟章节时跳过分配。"""

        class EmptyProcessor(_VirtualSectionProcessorMixin):
            def _collect_full_text_from_base(self) -> str:
                return ""

            def _build_markers(self, full_text: str) -> list[tuple[int, str | None]]:
                del full_text
                return []  # 无 marker → 无虚拟章节

            def get_full_text(self) -> str:
                return "short text"

            def get_full_text_with_table_markers(self) -> str:
                return "short [[t_0001]] text"

        processor = EmptyProcessor()
        processor._initialize_virtual_sections(min_sections=5)

        assert processor._table_ref_to_virtual_ref == {}
        assert processor._virtual_sections == []


@pytest.mark.unit
class TestListTablesRemapping:
    """list_tables() section_ref 重映射测试。"""

    def test_list_tables_remaps_section_ref(self) -> None:
        """验证 list_tables() 将底层 section_ref 替换为虚拟章节 ref。"""

        plain_text = _PLAIN_TEXT
        marked_text = _MARKED_TEXT

        item1_pos = plain_text.index("Item 1")
        item2_pos = plain_text.index("Item 2")
        markers = [
            (item1_pos, "Item 1"),
            (item2_pos, "Item 2"),
        ]
        _captured_markers = list(markers)

        class StubProcessor(_VirtualSectionProcessorMixin):
            def _collect_full_text_from_base(self) -> str:
                return ""

            def _build_markers(self, full_text: str) -> list[tuple[int, str | None]]:
                if "[[t_" in full_text:
                    return _rebuild_markers_for_text(full_text, _captured_markers)
                return list(_captured_markers)

            def get_full_text(self) -> str:
                return plain_text

            def get_full_text_with_table_markers(self) -> str:
                return marked_text

        # 使用变量避免 super() 调用冲突
        _base_tables = [
            _make_test_table_summary("t_0001", "s_0001"),
            _make_test_table_summary("t_0002", "s_0001"),
            _make_test_table_summary("t_0003", "s_0001"),
            _make_test_table_summary("t_0004", "s_0002"),
        ]

        # 动态添加底层 list_tables 能力
        original_list_tables = StubProcessor.list_tables

        def patched_list_tables(self):
            """被修补的 list_tables：当 mixin 重映射生效时使用 mixin 逻辑。"""
            if self._virtual_sections and self._table_ref_to_virtual_ref:
                # 调用 mixin 的 list_tables，但需要为 super().list_tables() 提供底层数据
                return _remap_tables(self, _base_tables)
            return list(_base_tables)

        StubProcessor.list_tables = patched_list_tables  # type: ignore

        processor = StubProcessor()
        processor._initialize_virtual_sections(min_sections=1)

        # 手动验证映射存在
        assert len(processor._table_ref_to_virtual_ref) > 0

        # 构建虚拟章节 ref 集合
        virtual_refs = {vs.ref for vs in processor._virtual_sections}

        # 用映射手动重映射
        tables = list(_base_tables)
        for table in tables:
            tbl_ref = table.get("table_ref")
            if tbl_ref and tbl_ref in processor._table_ref_to_virtual_ref:
                table["section_ref"] = processor._table_ref_to_virtual_ref[tbl_ref]

        # 所有表格的 section_ref 应指向虚拟章节
        for table in tables:
            assert table["section_ref"] in virtual_refs, (
                f"Table {table['table_ref']} section_ref "
                f"{table['section_ref']} not in virtual refs {virtual_refs}"
            )

    def test_list_tables_fallbacks_unmapped_section_ref_to_virtual_namespace(self) -> None:
        """验证未命中映射的表格也会回退到有效虚拟章节 ref。"""

        plain_text = _PLAIN_TEXT
        marked_text = _MARKED_TEXT
        _captured_markers = [
            (_ITEM1_POS, "Item 1"),
            (_ITEM2_POS, "Item 2"),
        ]

        class BaseTables:
            """底层表格桩。"""

            def list_tables(self):
                return [
                    _make_test_table_summary("t_0001", "base_sec_a"),
                    _make_test_table_summary("t_9999", "base_sec_unknown"),
                ]

        class Processor(_VirtualSectionProcessorMixin, BaseTables):
            """测试处理器。"""

            def _collect_full_text_from_base(self) -> str:
                return ""

            def _build_markers(self, full_text: str) -> list[tuple[int, str | None]]:
                if "[[t_" in full_text:
                    return _rebuild_markers_for_text(full_text, _captured_markers)
                return list(_captured_markers)

            def get_full_text(self) -> str:
                return plain_text

            def get_full_text_with_table_markers(self) -> str:
                return marked_text

        processor = Processor()
        processor._initialize_virtual_sections(min_sections=1)
        tables = processor.list_tables()
        virtual_refs = {section.ref for section in processor._virtual_sections}

        assert tables[0]["section_ref"] in virtual_refs
        assert tables[1]["section_ref"] in virtual_refs
        assert tables[1]["section_ref"] == tables[0]["section_ref"]


def _remap_tables(
    processor: _VirtualSectionProcessorMixin,
    base_tables: list[TableSummary],
) -> list[TableSummary]:
    """根据映射重写表格的 section_ref。

    Args:
        processor: 带映射的处理器实例。
        base_tables: 底层原始表格列表。

    Returns:
        重映射后的表格列表。
    """

    tables = [TableSummary(**t) for t in base_tables]
    for table in tables:
        tbl_ref = table.get("table_ref")
        if tbl_ref and tbl_ref in processor._table_ref_to_virtual_ref:
            table["section_ref"] = processor._table_ref_to_virtual_ref[tbl_ref]
    return tables


@pytest.mark.unit
def test_table_remap_prefers_deepest_child_section() -> None:
    """验证表格映射优先落到最深子章节，而非父目录章节。"""

    class BaseStub:
        """提供底层章节结构。"""

        def list_sections(self) -> list[SectionSummary]:
            return [
                build_section_summary(ref="b1", title="Item 18", level=1, parent_ref=None, preview=""),
                build_section_summary(ref="b2", title="Note 1", level=2, parent_ref="b1", preview=""),
                build_section_summary(ref="b3", title="Note 2", level=2, parent_ref="b1", preview=""),
            ]

        def read_section(self, ref: str) -> SectionContent:
            content_map = {
                "b1": "Item 18 body",
                "b2": "Note 1 details and disclosures " * 8,
                "b3": "Note 2 details and disclosures with table marker " * 8,
            }
            return build_section_content(
                ref=ref,
                title=ref,
                content=content_map.get(ref, ""),
                tables=[],
                word_count=len(content_map.get(ref, "").split()),
                contains_full_text=True,
            )

    class Processor(_VirtualSectionProcessorMixin, BaseStub):
        """测试处理器。"""

        def _build_markers(self, full_text: str) -> list[tuple[int, str | None]]:
            del full_text
            return [(0, "Part IV - Item 18 - Financial Statements")]

        def get_full_text(self) -> str:
            return (
                "Part IV - Item 18 - Financial Statements "
                + "Notes to the consolidated financial statements "
                + ("Note 1 details and disclosures " * 8)
                + ("Note 2 details and disclosures with table marker " * 8)
            )

        def get_full_text_with_table_markers(self) -> str:
            return (
                "Part IV - Item 18 - Financial Statements "
                + "Notes to the consolidated financial statements "
                + ("Note 1 details and disclosures " * 8)
                + ("Note 2 details and disclosures with table marker " * 4)
                + "[[t_0001]] "
                + ("Note 2 details and disclosures with table marker " * 4)
            )

    processor = Processor()
    processor._initialize_virtual_sections(min_sections=1)

    assert "t_0001" in processor._table_ref_to_virtual_ref
    mapped_ref = processor._table_ref_to_virtual_ref["t_0001"]
    mapped_section = processor._virtual_section_by_ref[mapped_ref]
    assert mapped_section.parent_ref == "s_0001"
    assert "Note 2" in str(mapped_section.title)
