"""从Docling原始网格提取合并三表，保留续页首行和可追溯定位。"""

import calendar
import math
import re
from dataclasses import dataclass
from datetime import date
from typing import TypedDict

_HEADER_SCAN_ROWS = 4
_YEAR_PATTERN = re.compile(r'(?<!\d)(?:19|20)\d{2}(?!\d)')
_MONTHS = {name.lower(): month for month, name in enumerate(calendar.month_name) if name}
_ENGLISH_DATE = re.compile(r'(\d{1,2})(' + '|'.join(_MONTHS) + r')((?:19|20)\d{2})', re.I)
_DURATIONS = (('threemonths', 3), ('sixmonths', 6), ('ninemonths', 9), ('twelvemonths', 12), ('三個月', 3), ('六個月', 6), ('九個月', 9), ('三个月', 3), ('六个月', 6), ('九个月', 9))
_TITLE_PATTERN = re.compile(
    r'(?P<scope>合并|合併|綜合|综合|母公司|公司)?(?P<title>資產負債表|资产负债表|財務狀況表|财务状况表|利潤表|利润表|損益及其他全面收益表|损益及其他综合收益表|損益表|损益表|現金流量表|现金流量表)'
    r'|(?P<english>(?:condensed)?(?:consolidated)?(?:statements?of)?(?:financialposition|balancesheets?|profitorloss|incomestatements?|comprehensiveincome|income|operations|cashflows?))', re.I)
_PARENT_SCOPES = frozenset({'母公司', '公司'})
_INCOME_TITLES = frozenset({'利潤表', '利润表', '損益表', '损益表', '損益及其他全面收益表', '损益及其他综合收益表'})
_BALANCE_TITLES = frozenset({'資產負債表', '资产负债表', '財務狀況表', '财务状况表'})
_SUPPORTED_STATEMENTS = frozenset({'income', 'balance_sheet', 'cash_flow'})
_MISSING = frozenset({'', '-', '--', '—', '–', '不适用', '不適用', 'N/A'})
_CURRENCIES = (('人民币', 'CNY'), ('人民幣', 'CNY'), ('RMB', 'CNY'), ('CNY', 'CNY'), ('港元', 'HKD'), ('HK$', 'HKD'), ('美元', 'USD'), ('US$', 'USD'), ('USD', 'USD'))
_SCALES = (('百萬元', 'millions'), ('百万元', 'millions'), ('millions', 'millions'), ('千元', 'thousands'), ('千美元', 'thousands'), ('千港元', 'thousands'), ('thousands', 'thousands'), ('万元', 'ten_thousands'), ('萬元', 'ten_thousands'))


@dataclass(frozen=True)
class StatementTable:
    """按原阅读顺序保存表格、前文和原始单元格，不经DataFrame表头提升。"""

    table_ref: str
    page_no: int | None
    context: str
    rows: tuple[tuple[str, ...], ...]


class StatementPeriod(TypedDict):
    """明确的财务期间，累计流量保留开始日期。"""

    period_end: str
    period_start: str | None


class StatementRow(TypedDict):
    """原始金额与逐行来源，缺失值保持为空。"""

    label: str
    values: list[float | None]
    source_table_ref: str
    page_no: int | None
    unit: str | None
    scale: str | None


class StatementLocator(TypedDict):
    """合并范围和参与拼接的表格位置。"""

    scope: str
    table_refs: list[str]
    page_numbers: list[int]


class DoclingStatementResult(TypedDict):
    """有明确口径和质量状态的标准报表结果。"""

    statement_type: str
    periods: list[StatementPeriod]
    rows: list[StatementRow]
    currency: str | None
    units: str | None
    scale: str | None
    data_quality: str
    reason: str | None
    statement_locator: StatementLocator


def _compact(text: str) -> str:
    """去除排版空白。参数：文本。返回：紧凑文本。异常：无。"""
    return re.sub(r'\s+', '', text)


def _statement(context: str) -> tuple[str, bool] | None:
    """识别最后一个报表标题及合并范围。参数：前文。返回：类型、是否应排除或空。异常：无。"""
    matches = list(_TITLE_PATTERN.finditer(_compact(context)))
    if not matches:
        return None
    match = matches[-1]
    title = match.group('title')
    english = (match.group('english') or '').lower()
    kind = 'balance_sheet' if title in _BALANCE_TITLES or 'financialposition' in english or 'balancesheet' in english else (
        'income' if title in _INCOME_TITLES or 'profit' in english or 'income' in english or 'operations' in english else 'cash_flow')
    excluded = match.group('scope') in _PARENT_SCOPES or match.group('scope') is None and 'consolidated' not in english
    return kind, excluded


def _number(text: str) -> float | None:
    """解析数值而不将缺失当零。参数：单元格。返回：数值或空。异常：无。"""
    value = _compact(text).replace(',', '').replace('，', '').replace('−', '-').replace('（', '(').replace('）', ')')
    if value in _MISSING:
        return None
    if value.startswith('(') and value.endswith(')'):
        value = '-' + value[1:-1]
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', value):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _period(text: str, context: str, kind: str) -> StatementPeriod | None:
    """识别列期间，不把报表年份当完整日期。参数：列头、前文、类型。返回：期间或空。异常：无。"""
    text, context = _compact(text), _compact(context)
    years = _YEAR_PATTERN.findall(text)
    if len(set(years)) != 1:
        return None
    year = int(years[0])
    full = re.search(r'(?:19|20)\d{2}[年/-](\d{1,2})[月/-](\d{1,2})日?', text)
    month_range = re.search(r'(\d{1,2})[-—–至](\d{1,2})月', text)
    english = _ENGLISH_DATE.search(text)
    if full is None and month_range is None:
        full = re.search(r'(?:19|20)\d{2}[年/-](\d{1,2})[月/-](\d{1,2})日?', context)
        month_range = re.search(r'(\d{1,2})[-—–至](\d{1,2})月', context)
        english = english or _ENGLISH_DATE.search(context)
    try:
        if full is not None:
            month, day = int(full[1]), int(full[2])
        elif month_range is not None:
            month = int(month_range[2]);day = calendar.monthrange(year, month)[1]
        elif english is not None:
            month = _MONTHS[english[2].lower()];day = int(english[1])
        else:
            return None
        end = date(year, month, day)
        start: date | None = None
        if kind != 'balance_sheet':
            duration = next((months for phrase, months in _DURATIONS if phrase in (text + context).lower()), None)
            if month_range is not None:
                start = date(year, int(month_range[1]), 1)
            elif duration is not None:
                start = date(year, month - duration + 1, 1)
            elif '年度' in text + context or 'yearended' in (text + context).lower():
                start = date(year, 1, 1)
        return {'period_end': end.isoformat(), 'period_start': start.isoformat() if start is not None else None}
    except ValueError:
        return None


def _columns(table: StatementTable, kind: str) -> tuple[list[int], list[StatementPeriod]]:
    """找到带期间的数值列，附注列不参与。参数：表格、类型。返回：列号和期间。异常：无。"""
    if not table.rows:
        return [], []
    indexes: list[int] = [];periods: list[StatementPeriod] = []
    primary_currency, _ = _units(table.context)
    for column in range(1, len(table.rows[0])):
        header: list[str] = []
        for row in table.rows[:_header_count(table)]:
            if column < len(row):
                header.append(row[column])
        column_currency, _ = _units(' '.join(header))
        if primary_currency and column_currency and column_currency != primary_currency:
            continue
        period = _period(' '.join(header), table.context, kind)
        if period is not None:
            indexes.append(column);periods.append(period)
    return indexes, periods


def _header_count(table: StatementTable) -> int:
    """区分表头和第一条业务数据。参数：原网格。返回：表头行数。异常：无。"""
    for index, row in enumerate(table.rows[:_HEADER_SCAN_ROWS]):
        label = _compact(row[0]) if row else ''
        is_column_label = re.fullmatch(r'项目|項目|附注|附註|items?|notes?', label, re.I) is not None
        if label and not is_column_label and _number(label) is None and any(_number(cell) is not None for cell in row[1:]):
            return index
    return min(len(table.rows), _HEADER_SCAN_ROWS)


def _units(context: str) -> tuple[str | None, str | None]:
    """读取明确币种和缩放。参数：范围文本。返回：币种、缩放或空。异常：无。"""
    compact = _compact(context)
    currency = next((code for token, code in _CURRENCIES if token.lower() in compact.lower()), None)
    scale = next((scale for token, scale in _SCALES if token.lower() in compact.lower()), None)
    if scale is None and re.search(r'单位[:：]元|單位[:：]元|人民币元|人民幣元|(?:RMB|CNY|HKD|USD)(?:元)?$', compact):
        scale = 'ones'
    return currency, scale


def extract_statement(tables: list[StatementTable], statement_type: str) -> DoclingStatementResult:
    """合并原始网格中的同范围续表。参数：有序表格、报表类型。返回：标准结果含缺口。异常：网格或日期数据损坏。"""
    if statement_type not in _SUPPORTED_STATEMENTS:
        return {'statement_type': statement_type, 'periods': [], 'rows': [], 'currency': None, 'units': None, 'scale': None,
                'data_quality': 'unavailable', 'reason': '该Docling报表类型尚未实现标准提取',
                'statement_locator': {'scope': 'consolidated', 'table_refs': [], 'page_numbers': []}}
    active: tuple[str, bool] | None = None
    indexes: list[int] = [];periods: list[StatementPeriod] = [];rows: list[StatementRow] = [];refs: list[str] = [];pages: list[int] = []
    currency: str | None = None;scale: str | None = None
    conflicting_units = False
    for table in tables:
        found = _statement(table.context)
        if found is not None and found != active:
            active = found;indexes = []
        if '财务报表附注' in _compact(table.context) or '財務報表附註' in _compact(table.context):
            active = None
        if active != (statement_type, False):
            continue
        current_indexes, current_periods = _columns(table, statement_type)
        if current_indexes:
            if periods and current_periods != periods:
                # 同一报表内不同期间组不能横向拼成一组。
                continue
            indexes, periods = current_indexes, current_periods
        if not indexes or not periods:
            continue
        current_currency, current_scale = _units(table.context)
        if (currency is not None and current_currency is not None and currency != current_currency
                or scale is not None and current_scale is not None and scale != current_scale):
            conflicting_units = True
            continue
        currency = current_currency or currency;scale = current_scale or scale
        for row in table.rows[_header_count(table):]:
            if max(indexes) >= len(row):
                continue
            label = _compact(row[0])
            if not label:
                continue
            values = [_number(row[index]) for index in indexes]
            if not any(value is not None for value in values):
                continue
            per_share = '每股' in label or 'pershare' in label.lower()
            rows.append({'label': label, 'values': values, 'source_table_ref': table.table_ref, 'page_no': table.page_no,
                         'unit': f'{currency} per share' if currency and per_share else currency,
                         'scale': 'ones' if per_share else scale})
        refs.append(table.table_ref)
        if table.page_no is not None:
            pages.append(table.page_no)
    complete = bool(rows and periods and currency and scale and not conflicting_units)
    reason = '同一合并报表的币种或缩放冲突，需核对原表' if conflicting_units else '缺少有效期间、数值、币种或缩放，不能视作完整标准三表'
    return {'statement_type': statement_type, 'periods': periods, 'rows': rows, 'currency': currency,
            'units': f'{currency} in {scale}' if currency and scale else None, 'scale': scale,
            'data_quality': 'extracted' if complete else 'unavailable',
            'reason': None if complete else reason,
            'statement_locator': {'scope': 'consolidated', 'table_refs': refs, 'page_numbers': pages}}
