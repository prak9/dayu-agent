"""fins 业务域 Docling 处理器。

该处理器复用 engine `DoclingProcessor` 的通用解析能力，
并在业务域层补充表格金融语义标注。
"""

from __future__ import annotations

from typing import Optional


from alpha.engine.processors.docling_processor import DoclingProcessor
from alpha.engine.processors.source import Source

from .financial_enhancer import FinsProcessorMixin, relabel_tables
from .docling_statements import DoclingStatementResult, StatementTable, extract_statement

_STATEMENT_CONTEXT_CHARS = 1200


class FinsDoclingProcessor(FinsProcessorMixin, DoclingProcessor):
    """fins 业务域 Docling 处理器。"""

    PARSER_VERSION = "fins_docling_processor_v1.1.0"

    def __init__(
        self,
        source: Source,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> None:
        """初始化处理器。

        Args:
            source: 文档来源抽象。
            form_type: 可选表单类型。
            media_type: 可选媒体类型。

        Returns:
            无。

        Raises:
            ValueError: 源文件不存在或参数非法时抛出。
            RuntimeError: 解析失败时抛出。
        """

        super().__init__(source=source, form_type=form_type, media_type=media_type)
        relabel_tables(self._tables)

    def get_financial_statement(self, statement_type: str) -> DoclingStatementResult:
        """读取可追溯的合并三表。参数：三表类型。返回：期间、数值、口径及原表定位。异常：原网格损坏。"""
        contexts: dict[str, str] = {}
        page_units: dict[int, list[str]] = {}
        # 单位可能作为caption挂在表格上，普通阅读序未必包含它；补入同页明确口径。
        for text in self._document.texts:
            if any(marker in text.text for marker in ("单位", "單位", "币种", "幣種")):
                for provenance in text.prov:
                    page_units.setdefault(provenance.page_no, []).append(text.text)
        preceding: list[str] = []
        for item in self._linear_items:
            if item.item_type == "text":
                preceding.append(item.text)
            elif item.item_type == "table" and item.internal_ref is not None:
                contexts[item.internal_ref] = "\n".join(preceding)[-_STATEMENT_CONTEXT_CHARS:]
                preceding = []
        tables = [StatementTable(
            table.table_ref, table.page_no, contexts.get(table.internal_ref or "", table.context_before)
            + "\n" + "\n".join(page_units.get(table.page_no or 0, [])),
            tuple(tuple(cell.text for cell in row) for row in table.table_item.data.grid),
        ) for table in self._tables]
        return extract_statement(tables, statement_type)
