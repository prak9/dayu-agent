"""sec_report_form_common 模块单元测试。"""

from __future__ import annotations

from typing import Any

import pytest

from alpha.fins.processors import sec_report_form_common as module
from alpha.fins.processors import sec_table_extraction as sec_table_module


def _make_processor_instance() -> module._BaseSecReportFormProcessor:
    """创建未执行构造函数的处理器实例。

    Args:
        无。

    Returns:
        可用于方法测试的实例。

    Raises:
        无。
    """

    processor = object.__new__(module._BaseSecReportFormProcessor)
    processor._tables = []
    return processor


def _table_block(
    *,
    ref: str,
    caption: str | None,
    headers: list[str] | None,
    context_before: str = "",
    table_type: str = "financial",
    is_financial: bool = True,
    dataframe: module.pd.DataFrame | None = None,
    table_obj: object | None = None,
) -> sec_table_module._TableBlock:
    """构造满足 sec report fallback 需求的表格块。"""

    return sec_table_module._TableBlock(
        ref=ref,
        table_obj=table_obj,
        text="",
        fingerprint=f"fp_{ref}",
        caption=caption,
        row_count=1,
        col_count=1,
        headers=headers,
        section_ref="s_0001",
        context_before=context_before,
        is_financial=is_financial,
        table_type=table_type,
        dataframe=dataframe,
    )


def _result_reason(result: module.FinancialStatementResult) -> str | None:
    """安全读取财务报表结果中的可选 reason。"""

    return result.get("reason")


@pytest.mark.unit
def test_get_financial_statement_fallbacks_to_html_in_sec_report_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证报告类 edgartools 回退链可使用 HTML 财务表 fallback。"""

    processor = _make_processor_instance()
    table = _table_block(
        ref="tbl_1",
        caption="Consolidated Statements of Operations",
        headers=["Year ended December 31, 2024"],
    )
    processor._tables = [table]

    monkeypatch.setattr(
        module.SecProcessor,
        "get_financial_statement",
        lambda self, statement_type, financials=None, meta=None: {
            "statement_type": statement_type,
            "periods": [],
            "rows": [],
            "currency": None,
            "units": None,
            "scale": None,
            "data_quality": "partial",
            "reason": "xbrl_not_available",
        },
    )
    monkeypatch.setattr(module, "_select_report_statement_tables", lambda **kwargs: [table])
    monkeypatch.setattr(
        module,
        "_build_html_statement_result_from_tables",
        lambda **kwargs: {
            "statement_type": "income",
            "periods": [{"period_end": "2024-12-31", "fiscal_year": 2024, "fiscal_period": "FY"}],
            "rows": [{"concept": "", "label": "Revenue", "values": [120.0]}],
            "currency": "USD",
            "units": "USD",
            "scale": None,
            "data_quality": "extracted",
            "statement_locator": {"statement_type": "income"},
        },
    )

    result = processor.get_financial_statement("income")
    assert result["data_quality"] == "extracted"
    assert result["rows"][0]["label"] == "Revenue"


@pytest.mark.unit
def test_get_financial_statement_fallbacks_to_html_when_statement_not_found_in_sec_report_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证报告类 edgartools 回退链在 statement_not_found 时也会走 HTML fallback。"""

    processor = _make_processor_instance()
    table = _table_block(
        ref="tbl_2",
        caption="Consolidated Balance Sheets",
        headers=["December 31, 2024"],
    )
    processor._tables = [table]

    monkeypatch.setattr(
        module.SecProcessor,
        "get_financial_statement",
        lambda self, statement_type, financials=None, meta=None: {
            "statement_type": statement_type,
            "periods": [],
            "rows": [],
            "currency": None,
            "units": None,
            "scale": None,
            "data_quality": "partial",
            "reason": "statement_not_found",
        },
    )
    monkeypatch.setattr(module, "_select_report_statement_tables", lambda **kwargs: [table])
    monkeypatch.setattr(
        module,
        "_build_html_statement_result_from_tables",
        lambda **kwargs: {
            "statement_type": "balance_sheet",
            "periods": [{"period_end": "2024-12-31", "fiscal_year": 2024, "fiscal_period": "FY"}],
            "rows": [{"concept": "", "label": "Assets", "values": [500.0]}],
            "currency": "USD",
            "units": "USD",
            "scale": None,
            "data_quality": "extracted",
            "statement_locator": {"statement_type": "balance_sheet"},
        },
    )

    result = processor.get_financial_statement("balance_sheet")
    assert result["data_quality"] == "extracted"
    assert result["rows"][0]["label"] == "Assets"


@pytest.mark.unit
def test_get_financial_statement_keeps_original_reason_without_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证找不到 HTML 候选表时保留原始 XBRL 失败原因。"""

    processor = _make_processor_instance()
    monkeypatch.setattr(
        module.SecProcessor,
        "get_financial_statement",
        lambda self, statement_type, financials=None, meta=None: {
            "statement_type": statement_type,
            "periods": [],
            "rows": [],
            "currency": None,
            "units": None,
            "scale": None,
            "data_quality": "partial",
            "reason": "statement_not_found",
        },
    )
    monkeypatch.setattr(module, "_select_report_statement_tables", lambda **kwargs: [])

    result = processor.get_financial_statement("income")
    assert _result_reason(result) == "statement_not_found"


@pytest.mark.unit
def test_get_financial_statement_marks_low_confidence_when_html_parse_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证存在候选表但 HTML 结构化失败时返回低置信原因。"""

    processor = _make_processor_instance()
    table = _table_block(
        ref="tbl_1",
        caption="Consolidated Statements of Stockholders' Equity",
        headers=["Year ended December 31, 2024"],
    )
    processor._tables = [table]
    monkeypatch.setattr(
        module.SecProcessor,
        "get_financial_statement",
        lambda self, statement_type, financials=None, meta=None: {
            "statement_type": statement_type,
            "periods": [],
            "rows": [],
            "currency": None,
            "units": None,
            "scale": None,
            "data_quality": "partial",
            "reason": "statement_empty",
        },
    )
    monkeypatch.setattr(module, "_select_report_statement_tables", lambda **kwargs: [table])
    monkeypatch.setattr(module, "_build_html_statement_result_from_tables", lambda **kwargs: None)

    result = processor.get_financial_statement("equity")
    assert _result_reason(result) == "low_confidence_extraction"


@pytest.mark.unit
def test_parse_report_table_dataframe_from_sec_prefers_precomputed_dataframe() -> None:
    """验证 Sec 路线优先使用预计算 dataframe。"""

    dataframe = module.pd.DataFrame([["A", "1"]])
    table = _table_block(
        ref="tbl_df",
        caption=None,
        headers=None,
        dataframe=dataframe,
        table_obj=None,
    )

    actual = module._parse_report_table_dataframe_from_sec(table)
    assert actual is not None
    assert actual.equals(dataframe)
    assert actual is not dataframe


@pytest.mark.unit
def test_parse_report_table_dataframe_from_sec_fallbacks_to_table_obj(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 Sec 路线在缺少预计算 dataframe 时回退到 table_obj。"""

    dataframe = module.pd.DataFrame([["A", "1"]])
    table_obj = object()
    table = _table_block(
        ref="tbl_obj",
        caption=None,
        headers=None,
        dataframe=None,
        table_obj=table_obj,
    )
    monkeypatch.setattr(module, "_safe_table_dataframe", lambda obj: dataframe if obj is table_obj else None)

    actual = module._parse_report_table_dataframe_from_sec(table)
    assert actual is not None
    assert actual.equals(dataframe)
