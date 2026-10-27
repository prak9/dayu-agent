"""中国财报标准三表的期间、跨页、归属与缺失值行为测试。"""
from pathlib import Path

from docling_core.types.doc.document import DoclingDocument, TableData, TableCell, ProvenanceItem
from docling_core.types.doc.labels import DocItemLabel
from docling_core.types.doc.base import BoundingBox

from alpha.fins.processors.docling_statements import StatementTable, extract_statement
from alpha.fins.processors.fins_docling_processor import FinsDoclingProcessor
from alpha.fins.storage.local_file_source import LocalFileSource


def test_cn_three_statements_keep_continuation_first_row_and_consolidated_scope() -> None:
    """合并表跨页保留首行且排除母公司。参数：无。返回：无。异常：断言失败。"""
    tables = [
        StatementTable('t1', 9, '合并资产负债表\n单位：元 币种：人民币', (
            ('项目', '2026年9月30日', '2025年12月31日'), ('货币资金', '90,391,714,028', '65,576,737,700'))),
        StatementTable('t2', 10, '紫金矿业集团股份有限公司 2026年第三季度报告', (
            ('资产总计', '559,336,374,506', '512,005,142,450'), ('负债合计', '279,131,853,955', '263,982,621,036'))),
        StatementTable('t3', 11, '合并利润表\n单位：元 币种：人民币', (
            ('项目', '2026年前三季度（1-9月）', '2025年前三季度（1-9月）'), ('营业收入', '283,452,745,522', '254,199,543,240'))),
        StatementTable('t4', 12, '2026年第三季度报告', (
            ('归属于母公司股东的净利润', '57,525,672,087', '37,863,620,974'), ('亏损', '（1,234.50）', '—'))),
        StatementTable('t5', 14, '合并现金流量表\n单位：元 币种：人民币', (
            ('项目', '2026年前三季度（1-9月）', '2025年前三季度（1-9月）'), ('经营活动产生的现金流量净额', '84,276,321,162', '52,107,388,420'))),
        StatementTable('t6', 16, '母公司资产负债表\n单位：元 币种：人民币', (
            ('项目', '2026年9月30日', '2025年12月31日'), ('资产总计', '153,217,313,437', '145,606,099,640'))),
    ]
    balance = extract_statement(tables, 'balance_sheet')
    income = extract_statement(tables, 'income')
    cash = extract_statement(tables, 'cash_flow')
    assert balance['currency'] == 'CNY' and balance['scale'] == 'ones'
    assert balance['periods'] == [{'period_end': '2026-09-30', 'period_start': None}, {'period_end': '2025-12-31', 'period_start': None}]
    assert balance['rows'][1]['values'] == [559336374506.0, 512005142450.0]
    assert len(balance['rows']) == 3
    assert income['periods'][0] == {'period_end': '2026-09-30', 'period_start': '2026-01-01'}
    assert income['rows'][1]['values'] == [57525672087.0, 37863620974.0]
    assert income['rows'][2]['values'] == [-1234.5, None]
    assert cash['rows'][0]['values'] == [84276321162.0, 52107388420.0]
    assert cash['statement_locator']['table_refs'] == ['t5']


def test_hk_traditional_currency_scale_and_notes_column() -> None:
    """繁体中期表保留千元口径且不读附注号。参数：无。返回：无。异常：断言失败。"""
    tables = [StatementTable('t1', 55, '簡明綜合損益表\n截至2026年6月30日止六個月\n人民幣千元', (
        ('', '附註', '2026年', '2025年'), ('收入', '7', '5,511,075', '4,455,000'), ('本期利潤', '8', '676,645', '320,000')))]
    result = extract_statement(tables, 'income')
    assert result['currency'] == 'CNY' and result['scale'] == 'thousands'
    assert result['periods'][1] == {'period_end': '2025-06-30', 'period_start': '2025-01-01'}
    assert result['rows'][0]['values'] == [5511075.0, 4455000.0]


def test_unknown_period_or_unit_is_not_invented() -> None:
    """不从报告标题或数字猜测缺失期间与币种。参数：无。返回：无。异常：断言失败。"""
    result = extract_statement([StatementTable('t1', 1, '合并利润表', (('项目','本期','上期'),('收入','100','90')))], 'income')
    assert result['rows'] == [] and result['data_quality'] == 'unavailable'
    result = extract_statement([StatementTable('t2', 2, '合并利润表', (('项目','2026年1-6月','2025年1-6月'),('收入','100','90')))], 'income')
    assert result['currency'] is None and result['units'] is None


def test_english_hk_quarter_and_convenience_currency_are_distinct() -> None:
    """英文季度不是累计半年，便利美元列不混入人民币列。参数：无。返回：无。异常：断言失败。"""
    table = StatementTable('t1', 3, 'Condensed consolidated statement of profit or loss\nFor the three months ended 30June2026\nRMB in thousands', (
        ('Item','2026 RMB','2025 RMB','2026 US$'), ('Revenue','100','90','15'), ('Earnings per share','0.20','0.18','0.03')))
    result = extract_statement([table], 'income')
    assert result['periods'][0] == {'period_end': '2026-06-30', 'period_start': '2026-04-01'}
    assert result['rows'][0]['values'] == [100.0, 90.0]
    assert result['rows'][1]['scale'] == 'ones'
    assert result['rows'][1]['unit'] == 'CNY per share'


def test_year_headers_are_not_amounts_and_missing_scope_is_not_consolidated() -> None:
    """年份、缺范围和不支持报表不冒充有效金额。参数：无。返回：无。异常：断言失败。"""
    header_only = StatementTable('t1', 1, '合并利润表 截至2026年6月30日止六個月 单位：元 币种：人民币', (('项目','2026','2025'),))
    assert extract_statement([header_only], 'income')['rows'] == []
    unspecified = StatementTable('t2', 2, '利润表 单位：元 币种：人民币', (('项目','2026年1-6月','2025年1-6月'),('收入','100','90')))
    assert extract_statement([unspecified], 'income')['rows'] == []
    assert extract_statement([unspecified], 'equity')['data_quality'] == 'unavailable'
    invalid = StatementTable('t3', 3, '合并利润表 单位：元 币种：人民币', (('项目','2026年13-14月','2025年13-14月'),('收入','100','90')))
    assert extract_statement([invalid], 'income')['rows'] == []


def test_conflicting_continuation_scale_is_not_a_complete_statement() -> None:
    """同一报表续页缩放冲突不能静默当完整覆盖。参数：无。返回：无。异常：断言失败。"""
    first = StatementTable('t1', 1, '合并利润表 单位：元 币种：人民币', (('项目','2026年1-6月','2025年1-6月'),('收入','100','90')))
    continuation = StatementTable('t2', 2, '单位：万元 币种：人民币', (('净利润','10','9'),))
    result = extract_statement([first, continuation], 'income')
    assert result['data_quality'] == 'unavailable'
    assert '冲突' in str(result['reason'])
    assert len(result['rows']) == 1



def test_processor_reads_real_docling_grid_and_attached_unit_caption(tmp_path: Path) -> None:
    """经真实Docling对象核验网格和表格附属题注。参数：目录。返回：无。异常：断言失败。"""
    document = DoclingDocument(name='合并利润表原件')
    provenance = ProvenanceItem(page_no=1, bbox=BoundingBox(l=0, t=0, r=100, b=100), charspan=(0, 0))
    document.add_text(label=DocItemLabel.TEXT, text='合并利润表', prov=provenance)
    grid = (('项目', '2026年1-9月', '2025年1-9月'), ('收入', '100', '90'))
    cells = [TableCell(text=text, start_row_offset_idx=row, end_row_offset_idx=row+1,
        start_col_offset_idx=column, end_col_offset_idx=column+1) for row, values in enumerate(grid) for column, text in enumerate(values)]
    table = document.add_table(data=TableData(num_rows=2, num_cols=3, table_cells=cells), prov=provenance)
    caption = document.add_text(label=DocItemLabel.CAPTION, text='单位：元 币种：人民币', parent=table, prov=provenance)
    table.captions.append(caption.get_ref())
    path = tmp_path / 'filing_docling.json'
    path.write_text(document.model_dump_json())
    source = LocalFileSource(path=path, uri='local://filing_docling.json', media_type='application/json', content_length=path.stat().st_size, etag=None)
    processor = FinsDoclingProcessor(source)
    statement = processor.get_financial_statement('income')
    assert statement['data_quality'] == 'extracted'
    assert statement['currency'] == 'CNY' and statement['scale'] == 'ones'
    assert statement['rows'][0]['values'] == [100.0, 90.0]
    assert statement['rows'][0]['page_no'] == 1
