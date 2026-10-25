"""报告类表单财务表语义共享层测试。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import pytest

from alpha.fins.processors import report_form_financial_statement_common as module


@dataclass(frozen=True)
class _StubTable:
    """测试用表格桩对象。"""

    ref: str
    tag: object
    table_type: str
    is_financial: bool
    caption: Optional[str]
    headers: Optional[list[str]]
    context_before: str


@pytest.mark.unit
def test_classify_report_statement_type_for_table_recognizes_balance_sheet() -> None:
    """验证可按 caption/header 识别资产负债表。"""

    statement_type = module.classify_report_statement_type_for_table(
        caption="Consolidated Balance Sheets",
        headers=["December 31, 2024", "December 31, 2023"],
        context_before="",
    )
    assert statement_type == "balance_sheet"


@pytest.mark.unit
def test_classify_report_statement_type_for_table_skips_notes_table() -> None:
    """验证财务附注表不会误判为主报表。"""

    statement_type = module.classify_report_statement_type_for_table(
        caption="Notes to Consolidated Financial Statements",
        headers=["Revenue Recognition", "Inventory"],
        context_before="",
    )
    assert statement_type is None


@pytest.mark.unit
def test_select_report_statement_tables_prefers_financial_classification() -> None:
    """验证候选表优先使用 is_financial 表上的显式分类结果。"""

    matched_table = _StubTable(
        ref="tbl_1",
        tag=object(),
        table_type="financial",
        is_financial=True,
        caption="Consolidated Statements of Cash Flows",
        headers=["Year ended December 31, 2024"],
        context_before="",
    )
    noise_table = _StubTable(
        ref="tbl_2",
        tag=object(),
        table_type="financial",
        is_financial=True,
        caption="Notes to Consolidated Financial Statements",
        headers=["Cash", "Inventory"],
        context_before="",
    )

    selected = module.select_report_statement_tables(
        statement_type="cash_flow",
        tables=[noise_table, matched_table],
        parse_table_dataframe=lambda table: None,
    )
    assert selected == [matched_table]


@pytest.mark.unit
def test_select_report_statement_tables_fallbacks_to_row_signals_for_all_non_layout() -> None:
    """验证显式分类失败时会扩大到全部非 layout 表做 row-signal fallback。"""

    fallback_table = _StubTable(
        ref="tbl_1",
        tag=object(),
        table_type="data",
        is_financial=False,
        caption="Statement data",
        headers=["As of", "December 31, 2024", "December 31, 2023"],
        context_before="",
    )
    layout_table = _StubTable(
        ref="tbl_2",
        tag=object(),
        table_type="layout",
        is_financial=False,
        caption="layout",
        headers=None,
        context_before="",
    )
    dataframe = pd.DataFrame(
        [
            ["Statement of Financial Position", "December 31, 2024", "December 31, 2023"],
            ["Cash and cash equivalents", "100", "90"],
            ["Total assets", "300", "260"],
            ["Total liabilities", "180", "150"],
            ["Total equity", "120", "110"],
            ["Current assets", "150", "130"],
            ["Current liabilities", "70", "60"],
        ]
    )

    selected = module.select_report_statement_tables(
        statement_type="balance_sheet",
        tables=[layout_table, fallback_table],
        parse_table_dataframe=lambda table: dataframe.copy() if table is fallback_table else None,
    )
    assert selected == [fallback_table]


@pytest.mark.unit
def test_select_report_statement_tables_uses_relaxed_row_signals_for_combined_financial_info() -> None:
    """验证非标准合并财务信息表可通过宽松行标签信号进入候选。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    fallback_table = _StubTable(
        ref="tbl_relaxed_balance_sheet",
        tag=object(),
        table_type="data",
        is_financial=False,
        caption="Combined financial information of TopCo",
        headers=["As of December 31, 2021", "As of December 31, 2020"],
        context_before="",
    )
    dataframe = pd.DataFrame(
        [
            ["Combined financial information of TopCo", "December 31, 2021", "December 31, 2020"],
            ["Cash and cash equivalents", "100", "90"],
            ["Restricted cash", "20", "18"],
            ["Borrowings", "55", "48"],
            ["Net debt", "35", "30"],
            ["Total equity", "140", "130"],
            ["Other liabilities", "30", "22"],
        ]
    )

    selected = module.select_report_statement_tables(
        statement_type="balance_sheet",
        tables=[fallback_table],
        parse_table_dataframe=lambda table: dataframe.copy() if table is fallback_table else None,
    )
    assert selected == [fallback_table]


@pytest.mark.unit
def test_should_apply_report_statement_html_fallback_only_for_allowed_reasons() -> None:
    """验证 HTML fallback 仅对允许的 XBRL 失败原因生效。"""

    assert module.should_apply_report_statement_html_fallback("xbrl_not_available") is True
    assert module.should_apply_report_statement_html_fallback("statement_empty") is True
    assert module.should_apply_report_statement_html_fallback("unsupported_statement_type") is False
    assert module.should_apply_report_statement_html_fallback(None) is False


@pytest.mark.unit
def test_row_signal_thresholds_cover_all_five_statements() -> None:
    """验证五大报表的 row-signal 配置可独立工作。"""

    row_map = {
        "income": [
            ["Consolidated Statements of Operations", "December 31, 2024", "December 31, 2023"],
            ["Revenue", "100", "90"],
            ["Cost of revenue", "40", "35"],
            ["Gross profit", "60", "55"],
            ["Operating income", "20", "18"],
            ["Net income", "15", "14"],
            ["Earnings per share", "1.5", "1.4"],
        ],
        "balance_sheet": [
            ["Consolidated Balance Sheets", "December 31, 2024", "December 31, 2023"],
            ["Cash and cash equivalents", "100", "90"],
            ["Current assets", "150", "130"],
            ["Total assets", "300", "260"],
            ["Current liabilities", "80", "70"],
            ["Total liabilities", "180", "150"],
            ["Total equity", "120", "110"],
        ],
        "cash_flow": [
            ["Consolidated Statements of Cash Flows", "December 31, 2024", "December 31, 2023"],
            ["Operating activities", "40", "35"],
            ["Investing activities", "-10", "-8"],
            ["Financing activities", "5", "4"],
            ["Net cash provided by operating activities", "40", "35"],
            ["Cash and cash equivalents", "100", "90"],
            ["Net cash provided", "35", "31"],
        ],
        "equity": [
            ["Consolidated Statements of Stockholders' Equity", "December 31, 2024", "December 31, 2023"],
            ["Common stock", "10", "10"],
            ["Additional paid-in capital", "80", "70"],
            ["Retained earnings", "40", "35"],
            ["Treasury stock", "-5", "-4"],
            ["Accumulated other comprehensive income", "3", "2"],
            ["Dividends", "-2", "-1"],
        ],
        "comprehensive_income": [
            ["Consolidated Statements of Comprehensive Income", "December 31, 2024", "December 31, 2023"],
            ["Net income", "15", "14"],
            ["Other comprehensive income", "3", "2"],
            ["Foreign currency translation", "1", "1"],
            ["Unrealized gain", "2", "1"],
            ["Comprehensive income", "18", "16"],
            ["Comprehensive income attributable to shareholders", "17", "15"],
        ],
    }
    for statement_type, rows in row_map.items():
        table = _StubTable(
            ref=statement_type,
            tag=object(),
            table_type="data",
            is_financial=False,
            caption="Fallback",
            headers=["2024", "2023"],
            context_before="",
        )
        selected = module.select_report_statement_tables(
            statement_type=statement_type,
            tables=[table],
            parse_table_dataframe=lambda table_obj, rows=rows, table=table: pd.DataFrame(rows).copy()
            if table_obj is table
            else None,
        )
        assert len(selected) == 1, statement_type
