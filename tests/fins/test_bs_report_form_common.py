"""bs_report_form_common 模块单元测试。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, BinaryIO, cast

import pytest
from bs4.element import Tag

from alpha.engine.processors.bs_processor import _TableBlock
from alpha.engine.processors.source import Source
from alpha.fins.processors import bs_report_form_common as module
from alpha.fins.processors.financial_base import FinancialStatementResult, XbrlFactsResult


class _DummySource:
    """最小 Source 测试桩。"""

    def __init__(self, *, uri: str = "memory://test.html", media_type: str | None = "text/html") -> None:
        """初始化测试 source。

        Args:
            uri: 资源 URI。
            media_type: 媒体类型。

        Returns:
            无。

        Raises:
            无。
        """

        self.uri = uri
        self.media_type = media_type
        self.content_length: int | None = 0
        self.etag: str | None = None

    def open(self) -> BinaryIO:
        """返回空字节流。"""

        return BytesIO(b"")

    def materialize(self, suffix: str | None = None) -> Path:
        """返回稳定临时路径。"""

        del suffix
        return Path("/tmp/test.html")


def _make_source() -> Source:
    """构造满足 Source 协议的测试对象。"""

    return _DummySource()


def _statement_reason(result: FinancialStatementResult) -> str:
    """安全读取财务报表结果里的 reason。"""

    return str(result.get("reason") or "")


def _statement_locator(result: FinancialStatementResult) -> dict[str, Any]:
    """安全读取财务报表结果里的 statement_locator。"""

    return cast(dict[str, Any], result.get("statement_locator") or {})


def _facts_reason(result: XbrlFactsResult) -> str:
    """安全读取 XBRL facts 结果里的 reason。"""

    return str(result.get("reason") or "")


def _facts_data_quality(result: XbrlFactsResult) -> str:
    """安全读取 XBRL facts 结果里的 data_quality。"""

    return str(result.get("data_quality") or "")


def _as_xbrl(value: object | None) -> module.XBRL | None:
    """在测试装配边界把桩对象显式收窄为 XBRL。"""

    return cast(module.XBRL | None, value)


def _make_table_block(*, caption: str, headers: list[str]) -> _TableBlock:
    """构造满足 `_TableBlock` 真源签名的测试表格。"""

    return _TableBlock(
        ref="tbl_1",
        tag=cast(Tag, object()),
        caption=caption,
        row_count=1,
        col_count=max(len(headers), 1),
        headers=headers,
        section_ref=None,
        context_before="",
        table_type="financial",
        has_spans=False,
    )


class _DummyDataFrame:
    """最小 DataFrame 桩。"""

    def __init__(self, *, columns: list[str], empty: bool) -> None:
        """初始化数据结构。

        Args:
            columns: 列名。
            empty: 是否空。

        Returns:
            无。

        Raises:
            无。
        """

        self.columns = columns
        self.empty = empty


def _make_processor_instance() -> module._BaseBsReportFormProcessor:
    """创建未执行构造函数的处理器实例。

    Args:
        无。

    Returns:
        可用于方法测试的实例。

    Raises:
        无。
    """

    processor = object.__new__(module._BaseBsReportFormProcessor)
    processor._xbrl = None
    processor._xbrl_loaded = True
    processor._xbrl_taxonomy = None
    processor._xbrl_taxonomy_loaded = False
    processor._source_path = Path("/tmp/test.html")
    processor._tables = []
    return processor


@pytest.mark.unit
def test_supports_rejects_when_form_not_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证不在支持集合时直接返回 False。"""

    class _Cls(module._BaseBsReportFormProcessor):
        _SUPPORTED_FORMS = frozenset({"10-K"})

    monkeypatch.setattr(module, "_normalize_report_form_type", lambda value: "8-K")
    monkeypatch.setattr(module.BSProcessor, "supports", lambda *args, **kwargs: True)

    actual = _Cls.supports(source=_make_source(), form_type="8-K", media_type="text/html")
    assert actual is False


@pytest.mark.unit
def test_supports_uses_bsprocessor_when_form_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证表单支持时委托 BSProcessor.supports。"""

    class _Cls(module._BaseBsReportFormProcessor):
        _SUPPORTED_FORMS = frozenset({"10-K"})

    monkeypatch.setattr(module, "_normalize_report_form_type", lambda value: "10-K")
    monkeypatch.setattr(module.BSProcessor, "supports", lambda *args, **kwargs: True)

    assert _Cls.supports(source=_make_source(), form_type="10-K", media_type="text/html") is True


@pytest.mark.unit
def test_get_financial_statement_handles_all_guard_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证财务报表读取的各类兜底分支。"""

    processor = _make_processor_instance()

    monkeypatch.setattr(module, "_STATEMENT_METHODS", {"income": "income_statement"})

    unsupported = processor.get_financial_statement("cashflow")
    assert _statement_reason(unsupported) == "unsupported_statement_type"

    processor._get_xbrl = lambda: None
    no_xbrl = processor.get_financial_statement("income")
    assert _statement_reason(no_xbrl) == "xbrl_not_available"

    xbrl_without_method = SimpleNamespace(statements=SimpleNamespace())
    processor._get_xbrl = lambda: _as_xbrl(xbrl_without_method)
    no_method = processor.get_financial_statement("income")
    assert _statement_reason(no_method) == "statement_method_missing"

    xbrl_none_stmt = SimpleNamespace(statements=SimpleNamespace(income_statement=lambda: None))
    processor._get_xbrl = lambda: _as_xbrl(xbrl_none_stmt)
    no_statement = processor.get_financial_statement("income")
    assert _statement_reason(no_statement) == "statement_not_found"

    xbrl_stub = SimpleNamespace(statements=SimpleNamespace(income_statement=lambda: object()))
    processor._get_xbrl = lambda: _as_xbrl(xbrl_stub)
    monkeypatch.setattr(module, "_safe_statement_dataframe", lambda statement: None)
    empty_by_none = processor.get_financial_statement("income")
    assert _statement_reason(empty_by_none) == "statement_empty"

    monkeypatch.setattr(
        module,
        "_safe_statement_dataframe",
        lambda statement: _DummyDataFrame(columns=["2024-09-28"], empty=False),
    )
    monkeypatch.setattr(module, "_extract_period_columns", lambda columns: ["2024-09-28"])
    monkeypatch.setattr(module, "_build_statement_rows", lambda df, periods: [{"concept": "Revenue"}])
    monkeypatch.setattr(module, "_build_period_summary", lambda period: {"period_end": period})
    monkeypatch.setattr(module, "_infer_units_from_xbrl_query", lambda xbrl: "USD")
    monkeypatch.setattr(module, "_infer_currency_from_units", lambda units: "USD")

    success = processor.get_financial_statement("income")
    assert success["data_quality"] == "xbrl"
    assert success["currency"] == "USD"
    assert success["units"] == "USD"
    assert success["rows"] == [{"concept": "Revenue"}]
    locator = _statement_locator(success)
    assert locator["statement_type"] == "income"
    assert locator["statement_title"] == "Income Statement"
    assert locator["period_labels"] == ["2024-09-28"]
    assert locator["row_labels"] == ["Revenue"]


@pytest.mark.unit
def test_query_xbrl_facts_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 query_xbrl_facts 的空概念、无 XBRL 与成功路径。"""

    processor = _make_processor_instance()

    monkeypatch.setattr(module, "_normalize_query_statement_type", lambda value: "income")

    empty = processor.query_xbrl_facts(concepts=["  ", ""])
    assert empty["total"] == 0
    assert empty["facts"] == []

    processor._get_xbrl = lambda: None
    no_xbrl = processor.query_xbrl_facts(concepts=["Revenue"])  # type: ignore[list-item]
    assert _facts_reason(no_xbrl) == "xbrl_not_available"
    assert _facts_data_quality(no_xbrl) == "partial"

    processor._get_xbrl = lambda: _as_xbrl(object())
    monkeypatch.setattr(module, "_query_facts_rows", lambda **kwargs: [{"concept": "Revenue", "value": 1.0}])
    monkeypatch.setattr(module, "_normalize_fact_row", lambda row: {"concept": row["concept"], "numeric_value": 1.0})
    success = processor.query_xbrl_facts(concepts=["Revenue"])  # type: ignore[list-item]
    assert success["total"] == 1
    assert success["facts"][0]["concept"] == "Revenue"


@pytest.mark.unit
def test_get_financial_statement_fallbacks_to_html_when_xbrl_not_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 XBRL 缺失时可回退到 HTML 财务表提取。"""

    processor = _make_processor_instance()
    table = _make_table_block(
        caption="Consolidated Statements of Operations",
        headers=["Year ended December 31, 2024"],
    )
    processor._tables = [table]
    processor._get_xbrl = lambda: None

    monkeypatch.setattr(module, "_STATEMENT_METHODS", {"income": "income_statement"})
    monkeypatch.setattr(module, "_select_report_statement_tables", lambda **kwargs: [table])
    monkeypatch.setattr(
        module,
        "_build_html_statement_result_from_tables",
        lambda **kwargs: {
            "statement_type": "income",
            "periods": [{"period_end": "2024-12-31", "fiscal_year": 2024, "fiscal_period": "FY"}],
            "rows": [{"concept": "", "label": "Revenue", "values": [120.0]}],
            "currency": "USD",
            "units": "USD in millions",
            "scale": "millions",
            "data_quality": "extracted",
            "statement_locator": {"statement_type": "income"},
        },
    )

    result = processor.get_financial_statement("income")
    assert result["data_quality"] == "extracted"
    assert result["rows"][0]["label"] == "Revenue"
    assert result["scale"] == "millions"


@pytest.mark.unit
def test_get_financial_statement_fallbacks_to_html_when_statement_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 XBRL statement 为空时仍可回退到 HTML 财务表提取。"""

    processor = _make_processor_instance()
    table = _make_table_block(
        caption="Consolidated Statements of Cash Flows",
        headers=["Year ended December 31, 2024"],
    )
    processor._tables = [table]

    monkeypatch.setattr(module, "_STATEMENT_METHODS", {"cash_flow": "cashflow_statement"})
    processor._get_xbrl = lambda: _as_xbrl(
        SimpleNamespace(statements=SimpleNamespace(cashflow_statement=lambda: object()))
    )
    monkeypatch.setattr(module, "_safe_statement_dataframe", lambda statement: None)
    monkeypatch.setattr(module, "_select_report_statement_tables", lambda **kwargs: [table])
    monkeypatch.setattr(
        module,
        "_build_html_statement_result_from_tables",
        lambda **kwargs: {
            "statement_type": "cash_flow",
            "periods": [{"period_end": "2024-12-31", "fiscal_year": 2024, "fiscal_period": "FY"}],
            "rows": [{"concept": "", "label": "Net cash provided by operating activities", "values": [55.0]}],
            "currency": "USD",
            "units": "USD",
            "scale": None,
            "data_quality": "extracted",
            "statement_locator": {"statement_type": "cash_flow"},
        },
    )

    result = processor.get_financial_statement("cash_flow")
    assert result["data_quality"] == "extracted"
    assert result["rows"][0]["label"] == "Net cash provided by operating activities"


@pytest.mark.unit
def test_get_financial_statement_fallbacks_to_html_when_statement_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 XBRL 可加载但 statement 为 None 时仍可回退到 HTML。"""

    processor = _make_processor_instance()
    table = _make_table_block(
        caption="Consolidated Balance Sheets",
        headers=["December 31, 2024", "December 31, 2023"],
    )
    processor._tables = [table]

    monkeypatch.setattr(module, "_STATEMENT_METHODS", {"balance_sheet": "balance_sheet"})
    processor._get_xbrl = lambda: _as_xbrl(
        SimpleNamespace(statements=SimpleNamespace(balance_sheet=lambda: None))
    )
    monkeypatch.setattr(module, "_select_report_statement_tables", lambda **kwargs: [table])
    monkeypatch.setattr(
        module,
        "_build_html_statement_result_from_tables",
        lambda **kwargs: {
            "statement_type": "balance_sheet",
            "periods": [{"period_end": "2024-12-31", "fiscal_year": 2024, "fiscal_period": "FY"}],
            "rows": [{"concept": "", "label": "Total assets", "values": [300.0]}],
            "currency": "USD",
            "units": "USD",
            "scale": None,
            "data_quality": "extracted",
            "statement_locator": {"statement_type": "balance_sheet"},
        },
    )

    result = processor.get_financial_statement("balance_sheet")
    assert result["data_quality"] == "extracted"
    assert result["rows"][0]["label"] == "Total assets"


@pytest.mark.unit
def test_get_financial_statement_keeps_xbrl_reason_when_no_html_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证找不到 HTML 候选表时保留原始 XBRL 失败原因。"""

    processor = _make_processor_instance()
    processor._get_xbrl = lambda: None

    monkeypatch.setattr(module, "_STATEMENT_METHODS", {"income": "income_statement"})
    monkeypatch.setattr(module, "_select_report_statement_tables", lambda **kwargs: [])

    result = processor.get_financial_statement("income")
    assert _statement_reason(result) == "xbrl_not_available"


@pytest.mark.unit
def test_get_financial_statement_returns_low_confidence_when_html_parse_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证存在候选表但 HTML 结构化失败时返回低置信原因。"""

    processor = _make_processor_instance()
    table = _make_table_block(
        caption="Consolidated Statements of Stockholders' Equity",
        headers=["Year ended December 31, 2024"],
    )
    processor._tables = [table]
    processor._get_xbrl = lambda: None

    monkeypatch.setattr(module, "_STATEMENT_METHODS", {"equity": "statement_of_equity"})
    monkeypatch.setattr(module, "_select_report_statement_tables", lambda **kwargs: [table])
    monkeypatch.setattr(module, "_build_html_statement_result_from_tables", lambda **kwargs: None)

    result = processor.get_financial_statement("equity")
    assert _statement_reason(result) == "low_confidence_extraction"


@pytest.mark.unit
def test_get_xbrl_load_and_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """验证 _get_xbrl 的缓存、缺文件与异常兜底行为。"""

    processor = _make_processor_instance()
    processor._xbrl_loaded = True
    cached_xbrl = _as_xbrl("cached")
    processor._xbrl = cached_xbrl
    assert processor._get_xbrl() == cached_xbrl

    processor._xbrl_loaded = False
    processor._xbrl = None
    processor._source_path = tmp_path / "input.html"

    monkeypatch.setattr(module, "discover_xbrl_files", lambda path: {})
    assert processor._get_xbrl() is None

    processor._xbrl_loaded = False
    monkeypatch.setattr(
        module,
        "discover_xbrl_files",
        lambda path: {
            "instance": tmp_path / "a.xml",
            "schema": tmp_path / "a.xsd",
            "presentation": None,
            "calculation": None,
            "definition": None,
            "label": None,
        },
    )
    xbrl_obj = _as_xbrl("xbrl_obj")
    monkeypatch.setattr(module.XBRL, "from_files", lambda **kwargs: xbrl_obj)
    assert processor._get_xbrl() == xbrl_obj

    processor._xbrl_loaded = False
    monkeypatch.setattr(module.XBRL, "from_files", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    assert processor._get_xbrl() is None


@pytest.mark.unit
def test_get_xbrl_taxonomy_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 taxonomy 读取含缓存和空 XBRL 分支。"""

    processor = _make_processor_instance()

    processor._xbrl_taxonomy_loaded = True
    processor._xbrl_taxonomy = "us-gaap"
    assert processor.get_xbrl_taxonomy() == "us-gaap"

    processor._xbrl_taxonomy_loaded = False
    processor._get_xbrl = lambda: None
    assert processor.get_xbrl_taxonomy() is None

    processor._xbrl_taxonomy_loaded = False
    processor._get_xbrl = lambda: _as_xbrl(object())
    monkeypatch.setattr(module, "_infer_xbrl_taxonomy", lambda xbrl: "ifrs-full")
    assert processor.get_xbrl_taxonomy() == "ifrs-full"
