"""section_semantic 模块测试。"""

from __future__ import annotations

import pytest

from alpha.fins.tools.section_semantic import (
    build_section_path,
    extract_item_number,
    resolve_section_semantic,
)


# ============================================================================
# extract_item_number 测试
# ============================================================================


@pytest.mark.unit
class TestExtractItemNumber:
    """extract_item_number 测试。"""

    def test_standard_item(self) -> None:
        """标准 Item 编号。"""

        assert extract_item_number("Item 1") == "1"
        assert extract_item_number("Item 1A") == "1A"
        assert extract_item_number("Item 7A") == "7A"

    def test_dotted_item(self) -> None:
        """带句点的 Item 编号。"""

        assert extract_item_number("Item 1.") == "1"
        assert extract_item_number("Item 1A.") == "1A"

    def test_item_with_title(self) -> None:
        """Item 编号后跟标题。"""

        assert extract_item_number("Item 1A. Risk Factors") == "1A"
        assert extract_item_number("Item 7. MD&A") == "7"

    def test_case_insensitive(self) -> None:
        """大小写不敏感。"""

        assert extract_item_number("ITEM 1A") == "1A"
        assert extract_item_number("item 1a") == "1A"

    def test_part_prefix_format(self) -> None:
        """支持 "Part X - Item Y" 前缀格式（实际 SEC 章节标题格式）。"""

        assert extract_item_number("Part I - Item 1") == "1"
        assert extract_item_number("Part I - Item 1A") == "1A"
        assert extract_item_number("Part II - Item 7") == "7"
        assert extract_item_number("Part II - Item 7A") == "7A"
        assert extract_item_number("Part II - Item 9A") == "9A"

    def test_no_item(self) -> None:
        """无 Item 前缀。"""

        assert extract_item_number("Risk Factors") is None
        assert extract_item_number("Part I") is None
        assert extract_item_number("") is None

    def test_none_input(self) -> None:
        """None 输入。"""

        assert extract_item_number(None) is None


# ============================================================================
# resolve_section_semantic 测试
# ============================================================================


@pytest.mark.unit
class TestResolveSectionSemantic:
    """resolve_section_semantic 测试。"""

    def test_10k_item_1a(self) -> None:
        """10-K Item 1A → risk_factors。"""

        item, title, stype = resolve_section_semantic(
            title="Item 1A. Risk Factors",
            form_type="10-K",
        )
        assert item == "1A"
        assert stype == "risk_factors"
        assert title is not None
        assert "Risk" in title

    def test_10k_item_7(self) -> None:
        """10-K Item 7 → md_and_a。"""

        item, title, stype = resolve_section_semantic(
            title="Item 7. Management's Discussion",
            form_type="10-K",
        )
        assert item == "7"
        assert stype == "mda"

    def test_10q_item_1_part_i(self) -> None:
        """10-Q Item 1 Part I → financial_statements。"""

        item, title, stype = resolve_section_semantic(
            title="Item 1. Financial Statements",
            form_type="10-Q",
            parent_title="Part I",
        )
        assert item == "1"
        assert stype == "financial_statements"

    def test_10q_item_1_part_ii(self) -> None:
        """10-Q Item 1 Part II → legal_proceedings。"""

        item, title, stype = resolve_section_semantic(
            title="Item 1. Legal Proceedings",
            form_type="10-Q",
            parent_title="Part II – Other Information",
        )
        assert item == "1"
        assert stype == "legal_proceedings"

    def test_20f_item_3(self) -> None:
        """20-F Item 3 → key_information。"""

        item, title, stype = resolve_section_semantic(
            title="Item 3. Key Information",
            form_type="20-F",
        )
        assert item == "3"

    def test_unknown_form(self) -> None:
        """未知 form type 返回 None section_type。"""

        item, title, stype = resolve_section_semantic(
            title="Item 1A. Risk Factors",
            form_type="8-K",
        )
        assert item == "1A"
        assert stype is None

    def test_non_item_title(self) -> None:
        """非 Item 标题。"""

        item, title, stype = resolve_section_semantic(
            title="Risk Factors",
            form_type="10-K",
        )
        assert item is None
        assert stype is None

    def test_none_form_type(self) -> None:
        """form_type 为 None。"""

        item, title, stype = resolve_section_semantic(
            title="Item 1A. Risk Factors",
            form_type=None,
        )
        assert item == "1A"
        assert stype is None

    def test_10k_part_prefix_format(self) -> None:
        """10-K "Part X - Item Y" 格式（实际 SEC 章节标题）。"""

        item, title, stype = resolve_section_semantic(
            title="Part I - Item 1A",
            form_type="10-K",
        )
        assert item == "1A"
        assert stype == "risk_factors"

        item, title, stype = resolve_section_semantic(
            title="Part II - Item 7",
            form_type="10-K",
        )
        assert item == "7"
        assert stype == "mda"

        item, title, stype = resolve_section_semantic(
            title="Part II - Item 8",
            form_type="10-K",
        )
        assert item == "8"
        assert stype == "financial_statements"

    def test_10q_part_prefix_no_parent(self) -> None:
        """10-Q "Part X - Item Y" 格式且无 parent_title 时，从自身标题推断 Part。"""

        item, title, stype = resolve_section_semantic(
            title="Part I - Item 2",
            form_type="10-Q",
            parent_title=None,
        )
        assert item == "2"
        assert stype == "mda"

        item, title, stype = resolve_section_semantic(
            title="Part II - Item 1A",
            form_type="10-Q",
            parent_title=None,
        )
        assert item == "1A"
        assert stype == "risk_factors"


# ============================================================================
# build_section_path 测试
# ============================================================================


@pytest.mark.unit
class TestBuildSectionPath:
    """build_section_path 测试。"""

    def test_full_path(self) -> None:
        """完整路径构建。"""

        path = build_section_path(
            form_type="10-K",
            item_number="1A",
            canonical_title="Risk Factors",
            section_title="Item 1A. Risk Factors",
            parent_titles=["Part I"],
        )
        assert "Part I" in path
        assert any("1A" in p for p in path)

    def test_no_parent(self) -> None:
        """无父级标题。"""

        path = build_section_path(
            form_type="10-K",
            item_number="7",
            canonical_title="MD&A",
            section_title="Item 7. MD&A",
            parent_titles=[],
        )
        assert any("7" in p for p in path)

    def test_no_item(self) -> None:
        """无 Item 编号。"""

        path = build_section_path(
            form_type="10-K",
            item_number=None,
            canonical_title=None,
            section_title="Overview",
            parent_titles=["Part I"],
        )
        # 路径应包含 Parent 和原始标题
        assert isinstance(path, list)

    def test_all_none(self) -> None:
        """全部为空。"""

        path = build_section_path(
            form_type=None,
            item_number=None,
            canonical_title=None,
            section_title=None,
            parent_titles=[],
        )
        assert path == []
