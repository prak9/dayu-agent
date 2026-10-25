"""tool_models 数据模型测试。"""

from __future__ import annotations

import pytest

from alpha.fins.domain.tool_models import (
    Citation,
    NumericContext,
    SectionSemantic,
    SectionType,
    SourceType,
)


# ============================================================================
# SourceType 枚举
# ============================================================================


@pytest.mark.unit
class TestSourceType:
    """SourceType 枚举测试。"""

    def test_values(self) -> None:
        """验证枚举值完整。"""

        assert SourceType.SEC_EDGAR.value == "SEC_EDGAR"
        assert SourceType.UPLOADED.value == "UPLOADED"
        assert SourceType.SUPPLEMENTARY.value == "SUPPLEMENTARY"

    def test_all_members(self) -> None:
        """验证枚举成员数量。"""

        assert len(SourceType) == 3


# ============================================================================
# SectionType 枚举
# ============================================================================


@pytest.mark.unit
class TestSectionType:
    """SectionType 枚举测试。"""

    def test_common_values(self) -> None:
        """验证常用 section type 存在。"""

        assert SectionType.RISK_FACTORS.value == "risk_factors"
        assert SectionType.MDA.value == "mda"
        assert SectionType.FINANCIAL_STATEMENTS.value == "financial_statements"
        assert SectionType.BUSINESS.value == "business"
        assert SectionType.LEGAL_PROCEEDINGS.value == "legal_proceedings"

    def test_member_count_minimum(self) -> None:
        """验证至少有 20 种 section type。"""

        assert len(SectionType) >= 20


# ============================================================================
# Citation 数据类
# ============================================================================


@pytest.mark.unit
class TestCitation:
    """Citation 数据类测试。"""

    def test_to_dict_strips_none(self) -> None:
        """验证 to_dict 过滤 None 字段。"""

        c = Citation(
            source_type="SEC_EDGAR",
            document_id="fil_001",
            ticker="AAPL",
            form_type="10-K",
            filing_date="2024-11-01",
        )
        d = c.to_dict()
        assert d["source_type"] == "SEC_EDGAR"
        assert d["ticker"] == "AAPL"
        # None 字段不应出现
        assert "accession_no" not in d
        assert "fiscal_year" not in d
        assert "item" not in d

    def test_to_dict_full(self) -> None:
        """验证所有字段均有值时全部输出。"""

        c = Citation(
            source_type="SEC_EDGAR",
            document_id="fil_001",
            ticker="AAPL",
            form_type="10-K",
            filing_date="2024-11-01",
            accession_no="0000320193-24-000123",
            fiscal_year=2024,
            fiscal_period="FY",
            item="1A",
            heading="Risk Factors",
        )
        d = c.to_dict()
        assert d["accession_no"] == "0000320193-24-000123"
        assert d["fiscal_year"] == 2024
        assert d["item"] == "1A"
        assert d["heading"] == "Risk Factors"

    def test_with_section(self) -> None:
        """验证 with_section 返回新实例并保持 frozen。"""

        c = Citation(
            source_type="SEC_EDGAR",
            document_id="fil_001",
            ticker="AAPL",
            form_type="10-K",
        )
        c2 = c.with_section(item="1A", heading="Risk Factors")
        # 原实例不变
        assert c.item is None
        assert c.heading is None
        # 新实例带有 section 信息
        assert c2.item == "1A"
        assert c2.heading == "Risk Factors"
        # 其他字段保持
        assert c2.source_type == "SEC_EDGAR"
        assert c2.document_id == "fil_001"

    def test_frozen(self) -> None:
        """验证 Citation 为 frozen 不可变。"""

        c = Citation(source_type="SEC_EDGAR", document_id="fil_001", ticker="AAPL")
        with pytest.raises(AttributeError):
            c.ticker = "GOOG"  # type: ignore[misc]


# ============================================================================
# SectionSemantic 数据类
# ============================================================================


@pytest.mark.unit
class TestSectionSemantic:
    """SectionSemantic 数据类测试。"""

    def test_basic_creation(self) -> None:
        """验证基本创建。"""

        s = SectionSemantic(
            item="1A",
            item_title="Risk Factors",
            topic="risk_factors",
            path=["Part I", "Item 1A", "Risk Factors"],
        )
        assert s.item == "1A"
        assert s.topic == "risk_factors"
        assert len(s.path) == 3


# ============================================================================
# NumericContext 数据类
# ============================================================================


@pytest.mark.unit
class TestNumericContext:
    """NumericContext 数据类测试。"""

    def test_defaults(self) -> None:
        """验证默认值全 None。"""

        nc = NumericContext()
        assert nc.unit is None
        assert nc.scale is None
        assert nc.decimals is None
        assert nc.period_type is None
        assert nc.period_start is None
        assert nc.period_end is None

    def test_full(self) -> None:
        """验证全字段赋值。"""

        nc = NumericContext(
            unit="USD",
            scale="millions",
            decimals=-6,
            period_type="duration",
            period_start="2024-01-01",
            period_end="2024-12-31",
        )
        assert nc.unit == "USD"
        assert nc.scale == "millions"
        assert nc.decimals == -6
        assert nc.period_type == "duration"
