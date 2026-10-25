"""财报文件上传识别逻辑。

负责从本地文件名中识别：
- 财期（fiscal_year / fiscal_period）
- Material 类型路由（财务报表、电话会议记录、业绩演示等）
- 主报告优先级打分与同期去重
- 年报/季报/material 各类数量上限过滤

本模块无 CLI/IO 依赖，仅做纯数据识别与过滤，便于独立测试。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 文件扩展名白名单
# ---------------------------------------------------------------------------
SUPPORTED_UPLOAD_FROM_SUFFIXES: frozenset[str] = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".xls",
        ".xlsx",
        ".htm",
        ".html",
        ".txt",
        ".md",
    }
)

# ---------------------------------------------------------------------------
# 财期识别 Patterns
#
# Qn / nQ 双格式均支持；使用负向后行断言 (?<!\d) 防止
# "2022Q4" 中 "2Q" 误匹配为 Q2、"2023Q4" 中 "3Q" 误匹配为 Q3 等年份干扰问题。
# ---------------------------------------------------------------------------
FISCAL_YEAR_PATTERN: re.Pattern = re.compile(r"(?P<year>20\d{2})")
Q1_PATTERN: re.Pattern = re.compile(r"(?:Q1|(?<!\d)1Q|第一季度|一季度)", re.IGNORECASE)
Q2_PATTERN: re.Pattern = re.compile(r"(?:Q2|(?<!\d)2Q|第二季度|二季度)", re.IGNORECASE)
Q3_PATTERN: re.Pattern = re.compile(r"(?:Q3|(?<!\d)3Q|第三季度|三季度)", re.IGNORECASE)
Q4_PATTERN: re.Pattern = re.compile(r"(?:Q4|(?<!\d)4Q|第四季度|四季度)", re.IGNORECASE)
H1_PATTERN: re.Pattern = re.compile(
    r"(?:H1|HALF[-_ ]?YEAR|半年度|半年报|中报|中期报告)", re.IGNORECASE
)
FY_PATTERN: re.Pattern = re.compile(r"(?:FY|ANNUAL|年度报告|年报)", re.IGNORECASE)
# Q4 含"季报"关键词时保留为 Q4 季报，否则默认升级为 FY（全年业绩）
_Q4_QUARTERLY_MARKER_PATTERN: re.Pattern = re.compile(r"季报", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Material 路由表
#
# 每项格式：(compiled_pattern, form_type, 描述)
# 按顺序匹配，首个命中者决定 form_type。
# 新增 material 类型时只需在此追加一行，无需修改业务逻辑。
# ---------------------------------------------------------------------------
_MATERIAL_ROUTING_TABLE: list[tuple[re.Pattern, str, str]] = [
    (
        re.compile(r"财务报表", re.IGNORECASE),
        "FINANCIAL_STATEMENTS",
        "财务报表",
    ),
    (
        re.compile(
            (
                r"电话会议|"
                r"(?:财报|业绩|业绩会|业绩说明会|业绩发布会).{0,8}会议纪要|"
                r"Earnings.{0,5}Call|Transcript|Conference.{0,5}Call"
            ),
            re.IGNORECASE,
        ),
        "EARNINGS_CALL",
        "业绩电话会议记录",
    ),
    (
        re.compile(
            r"演示|Slide|Presentation|Investor.{0,10}Day|Deck",
            re.IGNORECASE,
        ),
        "EARNINGS_PRESENTATION",
        "业绩演示/投资者演示",
    ),
]

# ---------------------------------------------------------------------------
# 主报告优先级打分辅助常量
#
# 层 0：长覆盖正式报告（年度报告 / 中期报告 / 年报 / 中报 等正式注册文件）
# 层 1：季度正式报告（季报）
# 层 2：通用报告类（含"报告"但无明确覆盖范围）
# 层 3：公告/通告类
# 层 4：其他未识别文件
# 层 5：补充材料（演示、幻灯、新闻等）
# ---------------------------------------------------------------------------
_PRIORITY_LONG_SCOPE_REPORT: re.Pattern = re.compile(
    r"年度报告|中期报告|Annual.{0,5}Report|Interim.{0,5}Report|半年.{0,3}报告|年报|中报",
    re.IGNORECASE,
)
_PRIORITY_QUARTERLY_REPORT: re.Pattern = re.compile(
    r"季报|季度.{0,5}报告|Quarterly.{0,5}Report",
    re.IGNORECASE,
)
_PRIORITY_GENERIC_REPORT: re.Pattern = re.compile(r"报告", re.IGNORECASE)
_PRIORITY_ANNOUNCEMENT: re.Pattern = re.compile(r"公告|通告|Announcement", re.IGNORECASE)
_PRIORITY_SUPPLEMENTARY: re.Pattern = re.compile(
    r"演示|Slide|Presentation|Deck|新闻|News|简报|摘要|Summary",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# 上传收集上限常量
# ---------------------------------------------------------------------------
_UPLOAD_ANNUAL_PERIODS: frozenset[str] = frozenset({"FY"})
_UPLOAD_PERIODIC_PERIODS: frozenset[str] = frozenset({"Q1", "Q2", "Q3", "Q4", "H1"})
_UPLOAD_MAX_ANNUAL: int = 5
# 季报/半年报：仅取最新一年内最多份数（港股可同时有 Q1/H1/Q2/Q3 四期，预留余量）
_UPLOAD_MAX_PERIODIC: int = 6
# 业绩演示：取最新 _UPLOAD_MAX_PRESENTATION 份（按文件名年份降序）
_UPLOAD_MAX_PRESENTATION: int = 6
_DEFAULT_MATERIAL_FORMS: str = "FINANCIAL_STATEMENTS"

# 合法的 material form_type 枚举（用于 CLI --forms 参数校验）。
# 来源：
#   - _MATERIAL_ROUTING_TABLE：自动识别支持的三种主要类型
#     （FINANCIAL_STATEMENTS / EARNINGS_CALL / EARNINGS_PRESENTATION）
#   - 人工管理扩展集：无自动识别规则、需显式 --forms 指定的类型
#     （CORPORATE_GOVERNANCE 等）
# 上传时使用 --forms 传入的值必须存在于此集合中（大写比较）。
VALID_MATERIAL_FORM_TYPES: frozenset[str] = frozenset(
    {entry[1] for entry in _MATERIAL_ROUTING_TABLE}
) | frozenset({
    "CORPORATE_GOVERNANCE",  # 无自动识别规则，需显式 --forms 指定
    "MATERIAL_OTHER",        # 兜底通用类型，映射为 material document_type
})

# ---------------------------------------------------------------------------
# 年份/年季子目录识别
# 匹配 2025/、2025Q1/、2025H1/ 等结构化子目录名，触发自动递归扫描。
# ---------------------------------------------------------------------------
_YEAR_SUBDIR_PATTERN: re.Pattern = re.compile(r"^20\d{2}(?:Q[1-4]|H1)?$", re.IGNORECASE)

# 财期顺序权重，用于同年内排序（数字越小越靠前）
_PERIOD_ORDER: dict[str, int] = {"Q1": 1, "H1": 2, "Q2": 3, "Q3": 4, "Q4": 5}


def _detect_year_subdir_layout(source_dir: Path) -> bool:
    """检测目录是否采用年份子目录组织结构（如 2024/、2025/）。

    Args:
        source_dir: 待检测目录。

    Returns:
        True 表示检测到年份子目录布局；否则 False。

    Raises:
        无。
    """
    return any(
        d.is_dir() and _YEAR_SUBDIR_PATTERN.match(d.name)
        for d in source_dir.iterdir()
    )


def _collect_upload_from_files(*, source_dir: Path, recursive: bool) -> list[Path]:
    """收集待识别文件列表。

    若目录采用年份子目录布局（顶层存在 20XX 目录），自动启用递归扫描，
    无需用户显式传入 ``--recursive``。

    Args:
        source_dir: 源目录。
        recursive: 是否递归扫描子目录；年份子目录布局时自动置为 True。

    Returns:
        可参与识别的文件路径列表（按路径排序）。

    Raises:
        OSError: 目录读取失败时抛出。
    """
    # 自动检测年份子目录布局
    if not recursive and _detect_year_subdir_layout(source_dir):
        recursive = True
    candidates = source_dir.rglob("*") if recursive else source_dir.iterdir()
    files: list[Path] = []
    for file_path in candidates:
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in SUPPORTED_UPLOAD_FROM_SUFFIXES:
            continue
        files.append(file_path.resolve())
    return sorted(files)


def _infer_fiscal_from_filename(filename: str) -> Optional[tuple[int, str]]:
    """从文件名推断 fiscal_year 与 fiscal_period。

    Args:
        filename: 文件名（不含目录）。

    Returns:
        推断成功返回 ``(fiscal_year, fiscal_period)``；否则返回 ``None``。

    Raises:
        无。
    """
    year_match = FISCAL_YEAR_PATTERN.search(filename)
    if year_match is None:
        return None
    fiscal_year = int(year_match.group("year"))
    fiscal_period = _infer_fiscal_period_from_filename(filename)
    if fiscal_period is None:
        return None
    return fiscal_year, fiscal_period


def _infer_fiscal_period_from_filename(filename: str) -> Optional[str]:
    """从文件名推断 fiscal_period。

    Q4 处理规则：
    - 含「季报」关键词（明确是季报） → Q4
    - 不含「季报」→ FY（港股/港式公司的 Q4 通常指全年业绩）

    Args:
        filename: 文件名。

    Returns:
        推断出的财期；无法识别返回 ``None``。

    Raises:
        无。
    """
    if H1_PATTERN.search(filename):
        return "H1"
    if FY_PATTERN.search(filename):
        return "FY"
    if Q1_PATTERN.search(filename):
        return "Q1"
    if Q2_PATTERN.search(filename):
        return "Q2"
    if Q3_PATTERN.search(filename):
        return "Q3"
    if Q4_PATTERN.search(filename):
        # 含「季报」→ 明确为季报；否则升级为全年报
        if _Q4_QUARTERLY_MARKER_PATTERN.search(filename):
            return "Q4"
        return "FY"
    return None


def _infer_fiscal_from_path(file_path: Path) -> Optional[tuple[int, str]]:
    """从文件路径推断 fiscal_year 与 fiscal_period。

    优先从文件名推断；若失败，则尝试从父目录名（如 2025Q1、2021Q4）推断。
    常见场景：「2025Q1/业绩公告.pdf」文件名本身无年份，但父目录携带了年份与财期信息。

    Q4 父目录沿用与文件名相同的升级规则：文件名含「季报」→ 保留 Q4；否则 → 升级为 FY
    （港股 Q4 业绩公告通常对应全年业绩，与年报同期）。
    纯年份子目录（如 2025/）缺失财期信息，仍返回 None。

    Args:
        file_path: 文件完整路径（含父目录信息）。

    Returns:
        推断成功返回 ``(fiscal_year, fiscal_period)``；否则返回 ``None``。

    Raises:
        无。
    """
    # 优先从文件名推断
    result = _infer_fiscal_from_filename(file_path.name)
    if result is not None:
        return result

    # 文件名无年份/财期信息 → 尝试父目录名（如 2025Q1）
    parent_name = file_path.parent.name
    if not _YEAR_SUBDIR_PATTERN.match(parent_name):
        return None

    year_match = FISCAL_YEAR_PATTERN.search(parent_name)
    if year_match is None:
        return None
    fiscal_year = int(year_match.group("year"))

    # 从目录名提取财期（目录名形如 2025Q1、2025H1，无需包含中文关键词）
    if Q1_PATTERN.search(parent_name):
        fiscal_period: Optional[str] = "Q1"
    elif Q2_PATTERN.search(parent_name):
        fiscal_period = "Q2"
    elif Q3_PATTERN.search(parent_name):
        fiscal_period = "Q3"
    elif Q4_PATTERN.search(parent_name):
        # Q4 目录沿用文件名同等升级规则：文件名无「季报」→ FY
        fiscal_period = "Q4" if _Q4_QUARTERLY_MARKER_PATTERN.search(file_path.name) else "FY"
    elif H1_PATTERN.search(parent_name):
        fiscal_period = "H1"
    else:
        # 纯年份目录（如 2025/），无法确定财期
        fiscal_period = None

    if fiscal_period is None:
        return None
    return fiscal_year, fiscal_period


def _match_material_form_type(filename: str) -> Optional[str]:
    """按 _MATERIAL_ROUTING_TABLE 匹配文件名，返回对应 form_type 或 None。

    按表中顺序逐一尝试，首个命中的 pattern 决定 form_type。
    未命中任何 pattern 时返回 None，表示该文件应走 filing 流程。

    Args:
        filename: 文件名（含扩展名）。

    Returns:
        命中的 form_type 字符串（如 ``"FINANCIAL_STATEMENTS"``、
        ``"EARNINGS_CALL"``、``"EARNINGS_PRESENTATION"``），
        未命中则返回 ``None``。

    Raises:
        无。
    """
    for pattern, form_type, _ in _MATERIAL_ROUTING_TABLE:
        if pattern.search(filename):
            return form_type
    return None


def _compute_main_report_priority(filename: str) -> int:
    """自适应计算主报告优先级分值（越小越优先）。

    不枚举具体文件名，而是依据文档类型结构特征分层打分：

    - 层 0（最高）：长覆盖正式报告 — 年度报告、中期报告、Annual/Interim Report、
      年报、中报等全年/半年度的正式注册文件。
    - 层 1：季度正式报告 — 季报、Quarterly Report。
    - 层 2：通用报告 — 含"报告"关键词但无明确覆盖范围。
    - 层 3：公告/通告类 — 业绩公告、Announcement 等披露性短文。
    - 层 4：其他未识别文件。
    - 层 5（最低）：补充材料 — 演示、Slide、新闻等。

    自适应说明：新出现的文件名（如"中期业绩报告"、"半年度结果"）只要包含
    对应特征词即可落入正确层级，无需手动维护枚举列表。

    Args:
        filename: 文件名（含扩展名）。

    Returns:
        优先级整数；0 最高，值越大优先级越低。

    Raises:
        无。
    """
    if _PRIORITY_LONG_SCOPE_REPORT.search(filename):
        return 0
    if _PRIORITY_QUARTERLY_REPORT.search(filename):
        return 1
    if _PRIORITY_GENERIC_REPORT.search(filename):
        return 2
    if _PRIORITY_ANNOUNCEMENT.search(filename):
        return 3
    if _PRIORITY_SUPPLEMENTARY.search(filename):
        return 5
    return 4


def _pick_best_per_period(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """同一（fiscal_year, fiscal_period）只保留最高优先级的主报告文件。

    按 ``_compute_main_report_priority`` 排序，取优先级最高的一条；
    其余同期文件归入 dropped 列表。

    Args:
        entries: 候选上传条目列表，每项含 ``fiscal_year``、``fiscal_period``、
            ``file``、``command`` 字段。

    Returns:
        二元组 ``(kept, dropped)``，kept 每期最多一条，dropped 为被去重的冗余文件。

    Raises:
        无。
    """
    groups: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for entry in entries:
        key = (entry["fiscal_year"], entry["fiscal_period"])
        groups.setdefault(key, []).append(entry)

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for group in groups.values():
        if len(group) == 1:
            kept.append(group[0])
        else:
            sorted_group = sorted(
                group,
                key=lambda e: _compute_main_report_priority(Path(e["file"]).name),
            )
            kept.append(sorted_group[0])
            dropped.extend(sorted_group[1:])
    return kept, dropped


def _filter_upload_entries(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按收集上限筛选上传条目。

    规则：
    - 年报（FY）：按 fiscal_year 降序取最新 ``_UPLOAD_MAX_ANNUAL`` 份。
    - 季报/半年报（Q1/Q2/Q3/Q4/H1）：仅保留识别到的最新 fiscal_year 内的条目，
      再按财期顺序取最多 ``_UPLOAD_MAX_PERIODIC`` 份。

    Args:
        entries: 已识别的上传条目列表，每项含 ``fiscal_year``、``fiscal_period``、
            ``file``、``command`` 字段。

    Returns:
        二元组 ``(kept, dropped)``，kept 为保留条目，dropped 为被截断条目。

    Raises:
        无。
    """
    annual = sorted(
        [e for e in entries if e["fiscal_period"] in _UPLOAD_ANNUAL_PERIODS],
        key=lambda e: e["fiscal_year"],
        reverse=True,
    )
    periodic = sorted(
        [e for e in entries if e["fiscal_period"] in _UPLOAD_PERIODIC_PERIODS],
        key=lambda e: (e["fiscal_year"], _PERIOD_ORDER.get(e["fiscal_period"], 99)),
        reverse=True,
    )

    # 年报：取最新 _UPLOAD_MAX_ANNUAL 份
    kept_annual = annual[:_UPLOAD_MAX_ANNUAL]

    # 季报/半年报：仅取最新 fiscal_year 内的，再限制数量
    kept_periodic: list[dict[str, Any]] = []
    if periodic:
        latest_year = periodic[0]["fiscal_year"]
        within_year = [e for e in periodic if e["fiscal_year"] == latest_year]
        # 恢复升序（Q1 → H1 → Q3）后取前 N 份
        kept_periodic = sorted(
            within_year[:_UPLOAD_MAX_PERIODIC],
            key=lambda e: _PERIOD_ORDER.get(e["fiscal_period"], 99),
        )

    kept_set = {id(e) for e in kept_annual + kept_periodic}
    dropped = [e for e in entries if id(e) not in kept_set]
    kept = kept_annual + kept_periodic
    return kept, dropped


def _material_year_key(entry: dict[str, Any]) -> int:
    """提取 material 条目文件名中的年份，用于排序键（最新优先）。

    Args:
        entry: material 条目，包含 ``file`` 字段（字符串路径）。

    Returns:
        从文件名提取的四位年份整数；无法提取时返回 0（排最后）。

    Raises:
        无。
    """
    m = FISCAL_YEAR_PATTERN.search(Path(entry["file"]).name)
    return int(m.group("year")) if m else 0


def _filter_material_entries(
    material_entries: list[dict[str, Any]],
    max_per_form_type: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按 form_type 分别应用数量上限，超出者归入 dropped。

    每种 form_type 按文件名推断的 fiscal_year 降序（最新优先）排序后截断。
    未在 ``max_per_form_type`` 中设置上限的 form_type 全部保留。

    Args:
        material_entries: material 条目列表，每项含 ``file``、``material_forms`` 字段。
        max_per_form_type: form_type → 最大保留数量映射；未列出的 form_type 不限制。

    Returns:
        二元组 ``(kept, dropped)``，kept 为保留条目，dropped 为被截断条目。

    Raises:
        无。
    """
    # 按 form_type 分组
    by_form: dict[str, list[dict[str, Any]]] = {}
    for entry in material_entries:
        ft = entry["material_forms"]
        by_form.setdefault(ft, []).append(entry)

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    for form_type, items in by_form.items():
        cap = max_per_form_type.get(form_type)
        if cap is None:
            # 无上限，全部保留
            kept.extend(items)
            continue
        # 按文件名年份降序排，保留最近的 cap 条
        sorted_items = sorted(items, key=_material_year_key, reverse=True)
        kept.extend(sorted_items[:cap])
        dropped.extend(sorted_items[cap:])

    return kept, dropped


def _derive_material_name(filename: str, *, parent_dir_name: Optional[str] = None) -> str:
    """从文件名推导 material_name（保留年份/财期前缀，去除 HKEX 等冗余标识）。

    保留时间前缀是为了让 LLM 能精确定位材料所属财期。
    当文件名本身不含日期前缀时，尝试从 ``parent_dir_name``（如 ``2025Q1``）补全前缀，
    常见于港股年季子目录下的无前缀文件（如 ``2025Q3/财报电话会议.pdf``）。

    例：``"2024Q2 HKEX财务报表.pdf"`` → ``"2024Q2 财务报表"``；
        ``"2024Q4 财务报表.pdf"`` → ``"2024Q4 财务报表"``；
        ``"2025Q1业绩演示.pdf"`` → ``"2025Q1 业绩演示"``；
        ``"财务报表.pdf", parent_dir_name="2025Q3"`` → ``"2025Q3 财务报表"``；
        ``"财务报表.pdf"`` → ``"财务报表"``（无前缀时原样返回）。

    Args:
        filename: 文件名（含扩展名）。
        parent_dir_name: 可选父目录名（如 ``"2025Q3"``）；文件名无日期前缀时作为后备来源。

    Returns:
        推导出的 material_name；无法简化时返回去扩展名后的文件名。

    Raises:
        无。
    """
    stem = Path(filename).stem
    # 提取形如 "2024Q2"、"2024"、"2024FY" 的日期前缀
    date_match = re.match(r"^(20\d{2}(?:Q[1-4]|H1|FY)?)\s*", stem, flags=re.IGNORECASE)
    date_prefix = date_match.group(1).upper() if date_match else ""
    # 去除日期前缀后剩余部分
    rest = stem[date_match.end():].strip() if date_match else stem
    # 去除紧跟在前面的 "HKEX" 类前缀标识
    rest = re.sub(r"^HKEX\s*", "", rest, flags=re.IGNORECASE).strip()
    # 文件名无日期前缀时，从父目录名（如 2025Q3）补全
    if not date_prefix and parent_dir_name and _YEAR_SUBDIR_PATTERN.match(parent_dir_name):
        date_prefix = parent_dir_name.upper()
    # 重新拼回日期前缀，让 LLM 能精确感知财期
    if date_prefix and rest:
        return f"{date_prefix} {rest}"
    return rest if rest else stem
