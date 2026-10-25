"""真实 BABA XBRL 列名的期间提取回归。"""

import pandas as pd

from alpha.fins.processors.sec_xbrl_query import _build_period_summary, _build_statement_rows, _extract_period_columns


def test_annotated_periods_keep_values_and_period_identity() -> None:
    """年度和季度标签不能导致数值消失。参数：无。返回：无。异常：断言失败。"""
    columns = ["concept", "label", "2026-03-31 (FY)", "2025-03-31 (FY)", "2026-06-30 (Q1)"]
    frame = pd.DataFrame([["us-gaap_Revenues", "Revenue", 100, 90, 25]], columns=columns)
    periods = _extract_period_columns(frame.columns)
    assert periods == columns[2:]
    assert _build_statement_rows(frame, periods)[0]["values"] == [100.0, 90.0, 25.0]
    assert _build_period_summary(periods[0]) == {"period_end": "2026-03-31", "fiscal_year": 2026, "fiscal_period": "FY"}
    assert _build_period_summary(periods[2])["fiscal_period"] == "Q1"


def test_instant_period_and_unrelated_columns() -> None:
    """期点列保持原值且不误读普通文本。参数：无。返回：无。异常：断言失败。"""
    assert _extract_period_columns(["2026-03-31", "2026/03/31", "note 2026-03-31"]) == ["2026-03-31"]
    assert _build_period_summary("2026-03-31")["period_end"] == "2026-03-31"
