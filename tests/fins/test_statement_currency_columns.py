"""BABA 同表人民币和美元列的币种及单位回归。"""

from alpha.fins.processors.html_financial_statement_common import _extract_currency_for_column, _infer_scale_from_caption


def test_column_currency_precedes_other_currency_in_table_scope() -> None:
    """人民币数值不能因同表美元列被标成美元。参数：无。返回：无。异常：断言失败。"""
    assert _extract_currency_for_column(scope_text="Three months ended June 30 RMB RMB US$", column_header_text="2026 RMB") == "RMB"
    assert _extract_currency_for_column(scope_text="RMB RMB US$", column_header_text="2026 US$") == "US$"


def test_ambiguous_table_currency_is_not_guessed() -> None:
    """列头缺失且表内多币种时保留未知。参数：无。返回：无。异常：断言失败。"""
    assert _extract_currency_for_column(scope_text="RMB US$", column_header_text="2026") is None


def test_scale_can_be_read_from_header_scope_and_ambiguous_scales_stay_unknown() -> None:
    """百万单位不要求恰好出现在 caption，冲突不猜测。参数：无。返回：无。异常：断言失败。"""
    assert _infer_scale_from_caption("Three months ended June 30 (in millions, except per share data)") == "millions"
    assert _infer_scale_from_caption("In millions of KRW and thousands of US$") is None
