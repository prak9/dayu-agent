"""fins 表格金融语义增强工具。

本模块负责在业务域层为通用处理器产出的表格补充金融语义：
- 统一关键词库；
- 统一判定规则；
- 统一表格重标注流程。
- 金融语义额外字段提取（``extra_financial_table_fields``）。
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from alpha.engine.processors.text_utils import (
    normalize_optional_string as _normalize_optional_string,
    normalize_whitespace as _normalize_whitespace,
)


def extra_financial_table_fields(table: Any) -> dict[str, Any]:
    """提取金融语义额外字段（跨 FinsBSProcessor / FinsDoclingProcessor / FinsMarkdownProcessor 共享）。

    ``relabel_tables`` 会通过 ``setattr`` 为每个表格对象动态添加
    ``is_financial`` 属性，此函数将其填充到输出字典中。

    Args:
        table: 内部表格对象。

    Returns:
        包含 ``is_financial`` 的字段字典。
    """
    return {"is_financial": getattr(table, "is_financial", False)}

_FINANCIAL_KEYWORDS = (
    "balance sheet",
    "income statement",
    "cash flow",
    "statement of operations",
    "statement of cash flows",
    "financial position",
    "financial results",
    "total assets",
    "total liabilities",
    "net income",
    "net earnings",
    "revenue",
    "revenues",
    "earnings",
    "profit",
    "loss",
    "资产负债表",
    "利润表",
    "现金流量表",
    "营业收入",
    "净利润",
)


def is_financial_table(
    caption: Optional[str],
    headers: Optional[list[str]],
    context_before: str,
) -> bool:
    """判断表格是否为财务表。

    Args:
        caption: 表格标题。
        headers: 表头列表。
        context_before: 表格前文。

    Returns:
        命中金融关键词时返回 `True`，否则返回 `False`。

    Raises:
        RuntimeError: 判定失败时抛出。
    """

    parts = [str(caption or ""), str(context_before or "")]
    if headers:
        parts.extend(str(item or "") for item in headers)
    normalized_text = _normalize_whitespace(" ".join(parts)).lower()
    if not normalized_text:
        return False
    return any(keyword in normalized_text for keyword in _FINANCIAL_KEYWORDS)


def relabel_tables(tables: Iterable[Any]) -> None:
    """批量重标注表格金融语义。

    Args:
        tables: 表格对象可迭代序列。

    Returns:
        无。

    Raises:
        RuntimeError: 重标注失败时抛出。
    """

    for table in tables:
        relabel_single_table(table)


def relabel_single_table(table: Any) -> None:
    """重标注单个表格的金融语义。

    Args:
        table: 表格对象（需具备 `caption/headers/context_before/is_financial/table_type` 字段）。

    Returns:
        无。

    Raises:
        RuntimeError: 重标注失败时抛出。
    """

    caption = _normalize_optional_string(getattr(table, "caption", None))
    headers_value = getattr(table, "headers", None)
    headers = headers_value if isinstance(headers_value, list) else None
    context_before = str(getattr(table, "context_before", "") or "")
    is_financial = is_financial_table(caption=caption, headers=headers, context_before=context_before)

    setattr(table, "is_financial", is_financial)
    if is_financial:
        setattr(table, "table_type", "financial")
        return

    raw_type = str(getattr(table, "table_type", "") or "").strip().lower()
    if raw_type not in {"data", "layout"}:
        setattr(table, "table_type", "data")


class FinsProcessorMixin:
    """为 fins 处理器提供金融语义扩展的通用 Mixin。

    三个 fins 处理器子类（FinsBSProcessor / FinsDoclingProcessor /
    FinsMarkdownProcessor）均需覆盖 ``_extra_table_fields``，且实现完全
    相同。将此方法提升到本 Mixin，避免三处重复定义。

    MRO 约定：本 Mixin 须置于具体基类（BSProcessor / DoclingProcessor /
    MarkdownProcessor）之前，即：class FinsXxxProcessor(FinsProcessorMixin, XxxProcessor)。
    """

    def _extra_table_fields(self, table: Any) -> dict[str, Any]:
        """注入金融语义字段，委托 ``extra_financial_table_fields``。

        Args:
            table: 内部表格对象。

        Returns:
            包含 ``is_financial`` 的字段字典。
        """
        return extra_financial_table_fields(table)
