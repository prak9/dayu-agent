"""SEC 报告 LLM 可喂性 CI 评分脚本（110 分制，支持 10-K / 10-Q / 20-F / 6-K / 8-K / SC 13G / DEF 14A）。

本脚本面向 CI 场景，基于 `tool_snapshot_*` 文件对 SEC 报告处理结果执行量化评分。
通过 `--form` 参数选择表单类型，自动加载对应的 FormProfile（Item 列表、
内容阈值、section_count 区间等）。

评分框架（总分 110）：
A. 结构完整性（25）
B. 内容充足性（30）
C. 检索可用性（15）
D. 一致性与数据质量（15）
E. 噪声与完整性（15）
S. 语义可寻址性（10；仅 10-K / 10-Q / 20-F，其他表单默认满分）

同时提供硬门禁（hard gate），用于在严重质量问题出现时直接让 CI 失败。

使用示例：

```bash
# 10-K（默认）
python -m alpha.fins.score_sec_ci \\
  --form 10-K \\
  --base workspace \\
  --tickers AAPL,AMZN,V,TDG,AXON

# 10-Q
python -m alpha.fins.score_sec_ci \\
  --form 10-Q \\
  --base workspace \\
  --tickers AAPL,AMZN,V,TDG,AXON

# 20-F
python -m alpha.fins.score_sec_ci \\
  --form 20-F \\
  --base workspace \\
  --tickers TSM,ASML

# 6-K
python -m alpha.fins.score_sec_ci \\
  --form 6-K \\
  --base workspace \\
  --tickers TCOM

# 8-K
python -m alpha.fins.score_sec_ci \\
  --form 8-K \\
  --base workspace \\
  --tickers AAPL,AMZN,V,TDG,AXON

# SC 13G
python -m alpha.fins.score_sec_ci \\
  --form "SC 13G" \\
  --base workspace \\
  --tickers AMZN

# DEF 14A
python -m alpha.fins.score_sec_ci \\
  --form "DEF 14A" \\
  --base workspace \\
  --tickers AAPL,AMZN,V,TDG,AXON
```
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from alpha.fins.domain.document_models import DocumentQuery, ProcessedHandle
from alpha.fins.domain.enums import SourceKind
from alpha.fins.storage import (
    DocumentBlobRepositoryProtocol,
    FsDocumentBlobRepository,
    FsProcessedDocumentRepository,
    FsSourceDocumentRepository,
)


# ---------------------------------------------------------------------------
# 通用常量
# ---------------------------------------------------------------------------

DEFAULT_TICKERS = ["AAPL", "AMZN", "V", "TDG", "AXON", "META", "MSFT"]
DEFAULT_STATEMENT_TYPES = [
    "income",
    "balance_sheet",
    "cash_flow",
    "equity",
    "comprehensive_income",
]
REQUIRED_SNAPSHOT_SCHEMA_VERSION = "tool_snapshot_v1.0.0"
SEARCH_THRESHOLD_CONFIG_PATH = (
    Path(__file__).resolve().parent / "config" / "search_c_thresholds_v1.json"
)
SEARCH_STRATEGY_EXACT = "exact"

MOJIBAKE_RE = re.compile(
    r"Ã.|Â.|â€.|ï¿½|\uFFFD|[\x80-\x9f]"
)

# S 维度：识别封面页 section（Cover Page 无 topic 属于正常，排除在语义覆盖率评分之外）
_COVER_PAGE_TITLE_RE = re.compile(r"(?i)^cover\s+page$")
TOC_PAGE_LINE_RE = re.compile(
    r"(?im)"
    r"^\s*"
    r"(?!Item[\s\xa0]+\d)"   # 排除 "Item N" 型节标题行（如 "Item 18" 或 "ITEM\xa018."）
    r"(?!Part[\s\xa0]+[IVX])"  # 排除 "Part I/II/III/IV" 型节标题行
    r"[A-Za-z][^\n]{0,180}\b\d{1,3}\s*$"
)

# 截断检测：section 末尾以悬挂介词/连词/冠词结束，表明句子中断
TRUNCATION_TAIL_RE = re.compile(
    r"(?:^|\s)"
    r"(?:to|and|or|the|of|in|for|with|by|that|at|from|as|a|an"
    r"|refer|see|including|such|under|pursuant|per|into|upon)"
    r"\s*$",
    re.IGNORECASE,
)

# 边界溢出检测：section 末尾出现下一个 Part/Item 的标题文本
BOUNDARY_LEAK_RE = re.compile(
    r"PART\s+I{1,4}"
    r"(?:\s*[\-\u2013\u2014]\s*(?:OTHER\s+INFORMATION|FINANCIAL\s+INFORMATION)"
    r"|\s*$)",
    re.IGNORECASE,
)

# SEC 规定内容可为 "None" / "N/A" / "Not applicable" 的 Item 白名单
# 10-K 白名单：这些 Item 在多数公司中是合法的极短章节
_NEAR_EMPTY_WHITELIST_10K = frozenset({
    "Item 1B",   # Unresolved Staff Comments → "None"
    "Item 1C",   # Cybersecurity → 部分公司内容很短
    "Item 3",    # Legal Proceedings → "None"
    "Item 4",    # Mine Safety Disclosures → "Not applicable"
    "Item 5",    # Market for Common Equity → 简短声明
    "Item 6",    # [Reserved]
    "Item 9",    # Changes and Disagreements → "None"
    "Item 9C",   # Disclosure Regarding Foreign Jurisdictions → "None"
})

# 10-Q 白名单：Item 编号在 Part I/II 间有重叠，白名单必须保留 Part 前缀，
# 避免误将 Part I（关键内容）按 Part II 规则豁免。
_NEAR_EMPTY_WHITELIST_10Q = frozenset({
    "Part I - Item 3",    # Quantitative and Qualitative Disclosures About Market Risk
    "Part I - Item 4",    # Controls and Procedures
    "Part II - Item 1",   # Legal Proceedings → 常见 "None"
    "Part II - Item 1A",  # Risk Factors → 允许 "no material changes" 简短声明
    "Part II - Item 2",   # Unregistered Sales → 常见 "None"
    "Part II - Item 3",   # Defaults Upon Senior Securities → 常见 "None"
    "Part II - Item 4",   # Mine Safety Disclosures → 常见 "Not applicable"
    "Part II - Item 5",   # Other Information → 常见 "None"
})

# 20-F 白名单：FPI 年报中大量监管披露项允许 "N/A"
_NEAR_EMPTY_WHITELIST_20F = frozenset({
    "Item 2",    # Offer Statistics and Expected Timetable → 已上市公司通常 N/A
    "Item 9",    # The Offer and Listing → 已上市公司通常极短
    "Item 12",   # Description of Securities Other Than Equity → 多数公司 N/A
    "Item 13",   # Defaults, Dividend Arrearages → 通常 "None"
    "Item 14",   # Material Modifications to Rights of Securities → 通常 "None"
    "Item 16",   # [Reserved]
    "Item 16A",  # Audit Committee Financial Expert
    "Item 16B",  # Code of Ethics
    "Item 16C",  # Principal Accountant Fees and Services
    "Item 16D",  # Exemptions from Listing Standards
    "Item 16E",  # Purchases of Equity Securities
    "Item 16F",  # Change in Registrant's Certifying Accountant
    "Item 16G",  # Corporate Governance
    "Item 16H",  # Mine Safety Disclosure
    "Item 16I",  # Disclosure Regarding Foreign Jurisdictions
    "Item 16J",  # Insider Trading Policies
    "Item 17",   # Financial Statements (alternative) → 极少使用，通常 N/A
})

# 8-K 白名单：附件列表通常极短
_NEAR_EMPTY_WHITELIST_8K = frozenset({
    "Item 9.01",  # Financial Statements and Exhibits → 仅为附件索引
})

# 6-K 白名单：无——6-K 章节数少，每个章节都应有意义内容
_NEAR_EMPTY_WHITELIST_6K = frozenset()

# SC 13G 白名单：多数为 "N/A" 或简短法定声明
_NEAR_EMPTY_WHITELIST_SC13G = frozenset({
    "Item 5",   # Ownership of 5% or Less → 通常 "N/A"
    "Item 6",   # Ownership Attributable to Another → 通常 "N/A"
    "Item 7",   # Identification and Classification of Subsidiary
    "Item 8",   # Identification and Classification of Members
    "Item 9",   # Notice of Dissolution of Group → 通常 "N/A"
    "Item 10",  # Certification → 简短声明
})

# DEF 14A 白名单：无——使用关键词匹配，非关键词章节不进入 Item 评估
_NEAR_EMPTY_WHITELIST_DEF14A = frozenset()

# 表格 markdown 空单元格检测：匹配 | 之间只有空白的单元格
TABLE_EMPTY_CELL_RE = re.compile(r"\|\s*\|")

# SEC 交叉引用检测：SEC Regulation S-K §229.10(d) 允许 "incorporation by reference"
# 以及 SEC Form 10-K General Instructions G(2) 允许 Item 8 引用年报中的 Financial Statements
# 交叉引用内容通常极短（< 2000 chars），包含特征性法律语言
_CROSS_REFERENCE_RE = re.compile(
    r"(?:"
    r"information\s+required\s+(?:by\s+)?this\s+item\s+is\s+(?:contained|included|set\s+forth)"
    r"|incorporated?\s+(?:herein\s+)?by\s+reference"
    r"|refer(?:red)?\s+to\s+(?:Part|Item|pages?|the\s+(?:annual|financial))"
    r"|contained\s+(?:on|in)\s+pages?\s+F-"
    # SEC Form 10-Q Instructions: Part II Item 1A 允许声明无重大变化
    # 放宽中间词匹配：允许 "no material changes to the Company's risk factors"
    r"|no\s+material\s+change(?:s)?\s+(?:from|to|in)\s+.*?risk\s+factor"
    r"|no\s+material\s+change(?:s)?\s+(?:from|to|in)\s+(?:the\s+)?previously"
    r"|previously\s+disclosed\s+(?:in|under)\s+(?:our|the|its)\s+(?:annual|Form\s+10-K)"
    # 20-F Item 18：财务报表位于年报末尾的标准交叉引用
    r"|(?:included|set\s+forth|contained|appear(?:s|ing)?)\s+(?:at|in|on)\s+(?:the\s+)?end\s+of"
    # 10-Q Part II Item 1A：引用 Annual Report / Form 10-K 中的 Risk Factors
    r"|see\s+(?:the\s+)?(?:information|discussion)\s+(?:under|in)\s+.*?(?:Annual\s+Report|Form\s+10-K)"
    # 20-F：常见简短交叉引用模式（"See page F-1"、"responded to Item 18"）
    r"|see\s+(?:the\s+)?(?:beginning\s+(?:on|at)\s+)?page(?:s)?\s+F-\d+"
    r"|(?:has\s+)?responded\s+to\s+Item\s+\d+"
    # 20-F Item 18：财报位于文档末尾交叉引用变体（"starting on page F-1"、
    # "beginning on/at page F-1"、"Reference is made to pages F-1"）
    r"|(?:beginning|starting)\s+(?:on|at)\s+pages?\s+F-"
    r"|reference\s+is\s+made\s+to\s+pages?\s+F-"
    # 20-F Item 18："information required in this item is included" 变体
    r"|information\s+required\s+in\s+this\s+item\s+is\s+(?:contained|included|set\s+forth)"
    r")",
    re.IGNORECASE,
)
# 交叉引用内容长度上限（超过此长度不视为交叉引用）
_CROSS_REFERENCE_MAX_LEN = 2000

# 10-K 使用简单 "Item N" 提取（编号全局唯一）
ITEM_RE = re.compile(r"(Item\s+\d+[A-Z]?)", re.IGNORECASE)

# 8-K 使用小数编号格式 "Item X.XX"
ITEM_DECIMAL_RE = re.compile(r"(Item\s+\d+\.\d+)", re.IGNORECASE)

# 10-Q 使用 "Part X - Item N" 提取（Part I/II 编号存在重叠）
PART_ITEM_RE = re.compile(
    r"(Part\s+I{1,4})\s*[-–—]\s*(Item\s+\d+[A-Z]?)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# FormProfile — 表单类型评分参数
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FormProfile:
    """表单类型评分参数配置。

    Attributes:
        form_type: 表单类型标识（如 ``10-K``、``10-Q``、``20-F``）。
        item_order: 标准 Item 顺序列表，用于判定排序正确性。
        key_items_required: 关键 Item 列表，缺失则扣分。
        content_thresholds: Item → 最低内容长度阈值。
        content_weights: Item → 评分权重（总计应为 30）。
        toc_check_items: 需检测 ToC 污染的 Item 列表。
        hard_gate_items: 硬门禁必须存在的 Item 列表。
        section_count_low: 合理 section_count 下界。
        section_count_high: 合理 section_count 上界。
        use_part_prefix: 提取 Item 时是否保留 Part 前缀。
        near_empty_whitelist: 允许近空的 SEC 白名单 Item 集合。
        section_keyword_map: 关键词 → 标准化标签映射（用于无 Item 结构的表单，
            如 6-K、DEF 14A）。键为标准化标签，值为匹配关键词元组。
        use_decimal_items: 是否使用 ``Item X.XX`` 双级小数编号（8-K）。
        has_xbrl_financials: 是否预期有 XBRL 财务报表。为 ``False`` 时
            D3 财报完整性默认满分。
        cross_reference_exempt_items: 允许应用 SEC 法定交叉引用豁免的 Item。
            仅这些 Item 在内容长度不足时可通过交叉引用模式豁免。
        score_semantic_coverage: 是否评估 S 维度语义可寻址性。仅 10-K / 10-Q / 20-F
            设为 ``True``；其他表单默认 ``False``（S 维度自动满分 10/10）。
    """

    form_type: str
    item_order: tuple[str, ...]
    key_items_required: tuple[str, ...]
    content_thresholds: dict[str, int]
    content_weights: dict[str, int]
    toc_check_items: tuple[str, ...]
    hard_gate_items: tuple[str, ...]
    section_count_low: int
    section_count_high: int
    use_part_prefix: bool
    near_empty_whitelist: frozenset[str]
    section_keyword_map: dict[str, tuple[str, ...]] = field(default_factory=dict)
    use_decimal_items: bool = False
    has_xbrl_financials: bool = True
    cross_reference_exempt_items: frozenset[str] = field(default_factory=frozenset)
    score_semantic_coverage: bool = False


TEN_K_PROFILE = FormProfile(
    form_type="10-K",
    item_order=(
        "Item 1", "Item 1A", "Item 1B", "Item 1C",
        "Item 2", "Item 3", "Item 4",
        "Item 5", "Item 6", "Item 7", "Item 7A",
        "Item 8", "Item 9", "Item 9A", "Item 9B", "Item 9C",
        "Item 10", "Item 11", "Item 12", "Item 13", "Item 14",
        "Item 15", "Item 16",
    ),
    key_items_required=("Item 1", "Item 1A", "Item 7", "Item 7A", "Item 8", "Item 15"),
    content_thresholds={
        "Item 1A": 5000,
        "Item 7": 5000,
        "Item 8": 10000,
        "Item 7A": 500,
    },
    content_weights={
        "Item 1A": 8,
        "Item 7": 8,
        "Item 8": 10,
        "Item 7A": 4,
    },
    toc_check_items=("Item 7", "Item 8"),
    hard_gate_items=("Item 1A", "Item 7", "Item 8"),
    section_count_low=15,
    section_count_high=35,
    use_part_prefix=False,
    near_empty_whitelist=_NEAR_EMPTY_WHITELIST_10K,
    cross_reference_exempt_items=frozenset({"Item 8"}),
    score_semantic_coverage=True,
)

TEN_Q_PROFILE = FormProfile(
    form_type="10-Q",
    item_order=(
        "Part I - Item 1", "Part I - Item 2",
        "Part I - Item 3", "Part I - Item 4",
        "Part II - Item 1", "Part II - Item 1A", "Part II - Item 2",
        "Part II - Item 3", "Part II - Item 4",
        "Part II - Item 5", "Part II - Item 6",
    ),
    key_items_required=(
        "Part I - Item 1",   # Financial Statements (condensed)
        "Part I - Item 2",   # MD&A
        "Part II - Item 1A", # Risk Factor Updates
    ),
    content_thresholds={
        "Part I - Item 1": 5000,
        "Part I - Item 2": 3000,
        "Part II - Item 1A": 2000,
    },
    content_weights={
        "Part I - Item 1": 10,
        "Part I - Item 2": 12,
        "Part II - Item 1A": 8,
    },
    toc_check_items=("Part I - Item 1", "Part I - Item 2"),
    hard_gate_items=("Part I - Item 1", "Part I - Item 2"),
    section_count_low=8,
    section_count_high=20,
    use_part_prefix=True,
    near_empty_whitelist=_NEAR_EMPTY_WHITELIST_10Q,
    cross_reference_exempt_items=frozenset({"Part II - Item 1A"}),
    score_semantic_coverage=True,
)

# 20-F: 外国私人发行人年报（8 SEC Form 20-F）
# Item 编号全局唯一，与 10-K 相同使用简单 "Item N" 格式
TWENTY_F_PROFILE = FormProfile(
    form_type="20-F",
    item_order=(
        "Item 1", "Item 2", "Item 3", "Item 4", "Item 4A",
        "Item 5", "Item 6", "Item 7", "Item 8", "Item 9",
        "Item 10", "Item 11", "Item 12",
        "Item 13", "Item 14", "Item 15",
        "Item 16", "Item 16A", "Item 16B", "Item 16C",
        "Item 16D", "Item 16E", "Item 16F", "Item 16G",
        "Item 16H", "Item 16I", "Item 16J",
        "Item 17", "Item 18", "Item 19",
    ),
    key_items_required=(
        "Item 3",   # Key Information / Risk Factors
        "Item 4",   # Information on the Company
        "Item 5",   # Operating and Financial Review (MD&A)
        "Item 8",   # Financial Information
        "Item 11",  # Quant & Qual Market Risk Disclosures
        "Item 18",  # Financial Statements
    ),
    content_thresholds={
        "Item 3": 5000,    # Key Information / Risk Factors ≈ 10-K Item 1A
        "Item 5": 5000,    # Operating and Financial Review ≈ 10-K Item 7
        "Item 18": 10000,  # Financial Statements ≈ 10-K Item 8
        "Item 11": 500,    # Market Risk Disclosures ≈ 10-K Item 7A
    },
    content_weights={
        "Item 3": 8,
        "Item 5": 8,
        "Item 18": 10,
        "Item 11": 4,
    },
    toc_check_items=("Item 5", "Item 18"),
    hard_gate_items=("Item 3", "Item 5", "Item 18"),
    section_count_low=20,
    section_count_high=300,  # 20-F Risk Factor 子节较多（如 FUTU=163, TCOM=274），放宽上限
    use_part_prefix=False,
    near_empty_whitelist=_NEAR_EMPTY_WHITELIST_20F,
    cross_reference_exempt_items=frozenset({"Item 18"}),
    score_semantic_coverage=True,
)

# 6-K: 外国私人发行人临时报告（经筛选后为季度业绩 / IFRS 调和）
# 无标准 Item 结构，使用关键词匹配识别关键章节
SIX_K_PROFILE = FormProfile(
    form_type="6-K",
    item_order=(),  # 无标准 Item 顺序
    key_items_required=(),  # 无固定必需 Item
    content_thresholds={
        "Financial Results": 300,   # 季度财务结果
        "Safe Harbor": 100,         # 安全港声明
    },
    content_weights={
        "Financial Results": 20,
        "Safe Harbor": 10,
    },
    toc_check_items=(),
    hard_gate_items=(),
    section_count_low=3,
    section_count_high=15,
    use_part_prefix=False,
    near_empty_whitelist=_NEAR_EMPTY_WHITELIST_6K,
    section_keyword_map={
        "Financial Results": (
            "financial results", "key highlights",
            "results of operations", "financial and business",
        ),
        "Safe Harbor": ("safe harbor", "forward-looking"),
    },
    use_decimal_items=False,
    has_xbrl_financials=False,
)

# 8-K: 重大事件报告（事件驱动，每次仅含 1-3 个 Item）
# 使用 Item X.XX 双级小数编号，内容维度默认满分
EIGHT_K_PROFILE = FormProfile(
    form_type="8-K",
    item_order=(
        "Item 1.01", "Item 1.02", "Item 1.03", "Item 1.04", "Item 1.05",
        "Item 2.01", "Item 2.02", "Item 2.03", "Item 2.04",
        "Item 2.05", "Item 2.06",
        "Item 3.01", "Item 3.02", "Item 3.03",
        "Item 4.01", "Item 4.02",
        "Item 5.01", "Item 5.02", "Item 5.03", "Item 5.04",
        "Item 5.05", "Item 5.06", "Item 5.07", "Item 5.08",
        "Item 6.01", "Item 6.02", "Item 6.03", "Item 6.04", "Item 6.05", "Item 6.06",
        "Item 7.01",
        "Item 8.01",
        "Item 9.01",
    ),
    key_items_required=(),  # 事件驱动，无固定必需 Item
    content_thresholds={},  # 内容维度默认满分
    content_weights={},
    toc_check_items=(),
    hard_gate_items=(),
    section_count_low=2,
    section_count_high=8,
    use_part_prefix=False,
    near_empty_whitelist=_NEAR_EMPTY_WHITELIST_8K,
    use_decimal_items=True,
    has_xbrl_financials=False,
)

# SC 13G: 大额持股披露（Schedule 13G）
# 固定 Item 1-10 结构，极短模板式表单
SC_13G_PROFILE = FormProfile(
    form_type="SC 13G",
    item_order=(
        "Item 1", "Item 2", "Item 3", "Item 4", "Item 5",
        "Item 6", "Item 7", "Item 8", "Item 9", "Item 10",
    ),
    key_items_required=("Item 2", "Item 4"),  # 申报人身份 + 持股详情
    content_thresholds={
        "Item 2": 50,   # 申报人身份信息
        "Item 4": 50,   # 持股比例详情
    },
    content_weights={
        "Item 2": 15,
        "Item 4": 15,
    },
    toc_check_items=(),
    hard_gate_items=(),  # SC 13G 极短，不设硬门禁
    section_count_low=5,
    section_count_high=12,
    use_part_prefix=False,
    near_empty_whitelist=_NEAR_EMPTY_WHITELIST_SC13G,
    has_xbrl_financials=False,
)

# DEF 14A: 代理声明书（Proxy Statement）
# 无标准 Item 编号，使用关键词匹配识别关键章节
DEF_14A_PROFILE = FormProfile(
    form_type="DEF 14A",
    item_order=(),  # 无标准 Item 顺序
    key_items_required=(),  # 无固定 Item
    content_thresholds={
        "Executive Compensation": 2000,  # 高管薪酬
        "Directors": 500,                # 董事信息
        "Security Ownership": 300,       # 股权结构
    },
    content_weights={
        "Executive Compensation": 12,
        "Directors": 10,
        "Security Ownership": 8,
    },
    toc_check_items=(),
    hard_gate_items=(),
    section_count_low=8,
    section_count_high=25,
    use_part_prefix=False,
    near_empty_whitelist=_NEAR_EMPTY_WHITELIST_DEF14A,
    section_keyword_map={
        "Executive Compensation": (
            "executive compensation", "compensation discussion",
        ),
        "Directors": ("election of director", "directors"),
        "Security Ownership": ("security ownership", "beneficial ownership"),
    },
    has_xbrl_financials=False,
)

FORM_PROFILES: dict[str, FormProfile] = {
    "10-K": TEN_K_PROFILE,
    "10-Q": TEN_Q_PROFILE,
    "20-F": TWENTY_F_PROFILE,
    "6-K": SIX_K_PROFILE,
    "8-K": EIGHT_K_PROFILE,
    "SC 13G": SC_13G_PROFILE,
    "DEF 14A": DEF_14A_PROFILE,
}

# 批量财报提取覆盖率门禁阈值（D3 Financial Coverage Hard Gate）。
# 含义：在该 form 的一批文档中，成功提取到财务数据的文档比例必须达到阈值；
# 否则触发 CI 失败，提示 processor 存在系统性提取问题，需优化。
# 仅适用于预期包含财务数据的表单；8-K / SC 13G / DEF 14A 无此门禁。
_FINANCIAL_COVERAGE_THRESHOLDS: dict[str, float] = {
    "10-K": 0.99,  # XBRL 强制，近乎全量可提取；< 99% 表明 processor 有系统性 bug
    "10-Q": 0.99,  # XBRL 同样强制；< 99% 与 10-K 同等含义，表明 processor 有系统性 bug
    "20-F": 0.99,  # FPI 同样要求 XBRL（2021 年后）；< 99% 信号：taxonomy 解析问题
    "6-K":  0.90,  # HTML 提取，pipeline 已过滤为季报；< 90% 信号：表格识别有盲区
}


# ---------------------------------------------------------------------------
# ScoreConfig — CI 阈值配置
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ScoreConfig:
    """评分与门禁 CI 阈值配置。

    Attributes:
        min_doc_pass: 单文档通过阈值。
        min_doc_warn: 单文档警告阈值。
        min_batch_avg: 批量平均分通过阈值。
        min_batch_p10: 批量 P10 通过阈值。
        huge_section_warn: 过大 section 预警阈值。
        huge_section_fail: 过大 section 硬失败阈值。
    """

    # 评分总分上限由 100 → 110（新增 S 维度 10 分），阈值对应等比调整。
    # 等比换算基准：85% * 110 ≈ 93，75% * 110 ≈ 83，78% * 110 ≈ 86。
    min_doc_pass: float = 93.0
    min_doc_warn: float = 83.0
    min_batch_avg: float = 93.0
    min_batch_p10: float = 86.0
    huge_section_warn: int = 200_000
    huge_section_fail: int = 350_000


@dataclass(frozen=True, slots=True)
class SearchThresholdProfile:
    """维度 C 分层阈值配置。

    Attributes:
        profile_id: 阈值档位 ID。
        pack_name: 查询词包名称。
        form_types: 适用表单类型列表。
        t5: 覆盖率 5 分阈值。
        t7: 覆盖率 7 分阈值。
        t9: 覆盖率 9 分阈值。
    """

    profile_id: str
    pack_name: str
    form_types: tuple[str, ...]
    t5: float
    t7: float
    t9: float


# ---------------------------------------------------------------------------
# 评分结果数据类
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DimensionScore:
    """单维度评分结果。"""

    points: float
    max_points: float
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HardGateResult:
    """硬门禁判定结果。"""

    passed: bool
    reasons: list[str]


@dataclass(frozen=True, slots=True)
class CompletenessFailure:
    """完整性硬门禁失败记录。"""

    ticker: str
    document_id: str
    reason: str


@dataclass(slots=True)
class DocumentScore:
    """单文档评分结果。"""

    ticker: str
    document_id: str
    total_score: float
    grade: str
    hard_gate: HardGateResult
    dimensions: dict[str, DimensionScore]


@dataclass(slots=True)
class BatchScore:
    """批量评分汇总结果。

    Attributes:
        documents: 各文档评分结果。
        average_score: 批量平均分。
        p10_score: P10 分位分。
        hard_gate_failures: 单文档硬门禁失败数。
        passed: 批量是否通过 CI 判定。
        failed_reasons: CI 失败原因列表。
        financial_coverage_rate: 财报提取覆盖率（0~1），不适用时为 None。
        completeness_failures: 完整性硬门禁失败记录。
    """

    documents: list[DocumentScore]
    average_score: float
    p10_score: float
    hard_gate_failures: int
    passed: bool
    failed_reasons: list[str]
    financial_coverage_rate: Optional[float] = None
    completeness_failures: list[CompletenessFailure] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ProcessedSnapshotDocument:
    """用于评分的 processed 快照访问对象。"""

    ticker: str
    document_id: str
    handle: ProcessedHandle


@dataclass(frozen=True, slots=True)
class TruthCallsLoadResult:
    """工具 truth 快照加载结果。"""

    calls: list[dict[str, Any]]
    exists: bool


@dataclass(frozen=True, slots=True)
class FormDiscoveryResult:
    """表单样本发现结果。"""

    snapshots: list[ProcessedSnapshotDocument]
    completeness_failures: list[CompletenessFailure]


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------

_SEARCH_THRESHOLD_PROFILES_CACHE: Optional[list[SearchThresholdProfile]] = None


def _format_snapshot_locator(snapshot: ProcessedSnapshotDocument) -> str:
    """格式化 processed 快照逻辑定位符。

    Args:
        snapshot: processed 快照访问对象。

    Returns:
        逻辑定位符字符串。

    Raises:
        无。
    """

    return f"processed:{snapshot.ticker}/{snapshot.document_id}"


def _build_snapshot_document(
    *,
    ticker: str,
    document_id: str,
) -> ProcessedSnapshotDocument:
    """构造 processed 快照访问对象。

    Args:
        ticker: 股票代码。
        document_id: 文档 ID。

    Returns:
        processed 快照访问对象。

    Raises:
        无。
    """

    return ProcessedSnapshotDocument(
        ticker=ticker,
        document_id=document_id,
        handle=ProcessedHandle(ticker=ticker, document_id=document_id),
    )


def _load_json(
    *,
    snapshot: ProcessedSnapshotDocument,
    blob_repository: DocumentBlobRepositoryProtocol,
    file_name: str,
) -> dict[str, Any]:
    """加载 processed 快照内的 JSON 文件。

    Args:
        snapshot: processed 快照访问对象。
        blob_repository: 文档文件仓储。
        file_name: JSON 文件名。

    Returns:
        JSON 对象；读取失败返回空字典。
    """

    try:
        payload_bytes = blob_repository.read_file_bytes(snapshot.handle, file_name)
    except FileNotFoundError:
        return {}
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _load_truth_calls(
    *,
    snapshot: ProcessedSnapshotDocument,
    blob_repository: DocumentBlobRepositoryProtocol,
    tool_name: str,
) -> list[dict[str, Any]]:
    """加载指定 tool truth 的 calls。

    Args:
        snapshot: processed 快照访问对象。
        blob_repository: 文档文件仓储。
        tool_name: 工具名（不含前缀），例如 ``read_section``。

    Returns:
        调用记录列表；文件缺失或解析失败时返回空列表。
    """

    return _load_truth_calls_result(
        snapshot=snapshot,
        blob_repository=blob_repository,
        tool_name=tool_name,
    ).calls


def _load_truth_calls_result(
    *,
    snapshot: ProcessedSnapshotDocument,
    blob_repository: DocumentBlobRepositoryProtocol,
    tool_name: str,
) -> TruthCallsLoadResult:
    """加载指定 tool truth 的 calls，并返回文件存在性。

    Args:
        snapshot: processed 快照访问对象。
        blob_repository: 文档文件仓储。
        tool_name: 工具名（不含前缀），例如 ``read_section``。

    Returns:
        加载结果；若文件不存在则 ``exists=False``。
    """

    file_name = f"tool_snapshot_{tool_name}.json"
    try:
        payload_bytes = blob_repository.read_file_bytes(snapshot.handle, file_name)
    except FileNotFoundError:
        return TruthCallsLoadResult(calls=[], exists=False)
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return TruthCallsLoadResult(calls=[], exists=True)
    if not isinstance(payload, dict):
        return TruthCallsLoadResult(calls=[], exists=True)
    calls = payload.get("calls", [])
    if not isinstance(calls, list):
        return TruthCallsLoadResult(calls=[], exists=True)
    return TruthCallsLoadResult(
        calls=[call for call in calls if isinstance(call, dict)],
        exists=True,
    )


def _load_snapshot_meta_required(
    *,
    snapshot: ProcessedSnapshotDocument,
    blob_repository: DocumentBlobRepositoryProtocol,
) -> dict[str, Any]:
    """加载并校验 `tool_snapshot_meta.json` 强制契约。

    Args:
        snapshot: processed 快照访问对象。
        blob_repository: 文档文件仓储。

    Returns:
        通过校验的 meta 字典。

    Raises:
        ValueError: 缺失或不满足 v2 契约时抛出。
    """

    payload = _load_json(
        snapshot=snapshot,
        blob_repository=blob_repository,
        file_name="tool_snapshot_meta.json",
    )
    if not payload:
        raise ValueError(f"缺少 tool_snapshot_meta.json: {_format_snapshot_locator(snapshot)}")

    snapshot_schema_version = str(payload.get("snapshot_schema_version", "")).strip()
    if snapshot_schema_version != REQUIRED_SNAPSHOT_SCHEMA_VERSION:
        raise ValueError(
            "tool_snapshot_meta.snapshot_schema_version 不匹配: "
            f"{snapshot_schema_version!r} != {REQUIRED_SNAPSHOT_SCHEMA_VERSION!r}"
        )

    pack_name = str(payload.get("search_query_pack_name", "")).strip()
    pack_version = str(payload.get("search_query_pack_version", "")).strip()
    search_query_count = payload.get("search_query_count")
    if not pack_name:
        raise ValueError("tool_snapshot_meta.search_query_pack_name 缺失")
    if not pack_version:
        raise ValueError("tool_snapshot_meta.search_query_pack_version 缺失")
    if not isinstance(search_query_count, int) or search_query_count <= 0:
        raise ValueError("tool_snapshot_meta.search_query_count 必须为正整数")
    return payload


def _load_search_threshold_profiles() -> list[SearchThresholdProfile]:
    """加载维度 C 阈值配置。

    Args:
        无。

    Returns:
        阈值配置列表。

    Raises:
        RuntimeError: 配置文件缺失或格式非法时抛出。
    """

    global _SEARCH_THRESHOLD_PROFILES_CACHE
    if _SEARCH_THRESHOLD_PROFILES_CACHE is not None:
        return _SEARCH_THRESHOLD_PROFILES_CACHE

    if not SEARCH_THRESHOLD_CONFIG_PATH.exists():
        raise RuntimeError(f"缺少 C 维阈值配置文件: {SEARCH_THRESHOLD_CONFIG_PATH}")
    try:
        with open(SEARCH_THRESHOLD_CONFIG_PATH, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"读取 C 维阈值配置失败: {SEARCH_THRESHOLD_CONFIG_PATH}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("C 维阈值配置格式错误：根节点必须是对象")
    if str(raw.get("schema_version", "")).strip() != "search_c_thresholds_v1":
        raise RuntimeError("C 维阈值配置 schema_version 非 search_c_thresholds_v1")

    raw_profiles = raw.get("profiles")
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise RuntimeError("C 维阈值配置 profiles 不能为空")

    profiles: list[SearchThresholdProfile] = []
    for item in raw_profiles:
        if not isinstance(item, dict):
            raise RuntimeError("C 维阈值配置 profiles 元素必须为对象")
        profile_id = str(item.get("profile_id", "")).strip()
        pack_name = str(item.get("pack_name", "")).strip()
        raw_forms = item.get("form_types", [])
        thresholds = item.get("thresholds", {})
        if not profile_id or not pack_name:
            raise RuntimeError("C 维阈值配置 profile_id/pack_name 不能为空")
        if not isinstance(raw_forms, list) or not raw_forms:
            raise RuntimeError(f"C 维阈值配置 {profile_id} 缺少 form_types")
        if not isinstance(thresholds, dict):
            raise RuntimeError(f"C 维阈值配置 {profile_id} 缺少 thresholds")
        t5 = float(thresholds.get("t5", -1))
        t7 = float(thresholds.get("t7", -1))
        t9 = float(thresholds.get("t9", -1))
        if not (0.0 <= t5 < t7 < t9 <= 1.0):
            raise RuntimeError(f"C 维阈值配置 {profile_id} 不满足 0<=t5<t7<t9<=1")
        forms = tuple(_normalize_form_type(str(form)) for form in raw_forms if str(form).strip())
        if not forms:
            raise RuntimeError(f"C 维阈值配置 {profile_id} 的 form_types 无有效值")
        profiles.append(
            SearchThresholdProfile(
                profile_id=profile_id,
                pack_name=pack_name,
                form_types=forms,
                t5=t5,
                t7=t7,
                t9=t9,
            )
        )

    _SEARCH_THRESHOLD_PROFILES_CACHE = profiles
    return profiles


def _resolve_search_threshold_profile(
    *,
    pack_name: str,
    form_type: str,
) -> SearchThresholdProfile:
    """按查询词包与表单类型解析 C 维阈值档位。

    Args:
        pack_name: 查询词包名。
        form_type: 表单类型。

    Returns:
        命中的阈值配置。

    Raises:
        ValueError: 找不到匹配阈值时抛出。
    """

    normalized_pack_name = str(pack_name or "").strip()
    normalized_form_type = _normalize_form_type(form_type)
    profiles = _load_search_threshold_profiles()
    for profile in profiles:
        if profile.pack_name != normalized_pack_name:
            continue
        if normalized_form_type in profile.form_types:
            return profile
    raise ValueError(
        "未找到 C 维阈值配置: "
        f"pack={normalized_pack_name!r} form_type={normalized_form_type!r}"
    )


# ---------------------------------------------------------------------------
# 目录发现
# ---------------------------------------------------------------------------

def _detect_form_type(
    *,
    snapshot: ProcessedSnapshotDocument,
    blob_repository: DocumentBlobRepositoryProtocol,
) -> Optional[str]:
    """检测 processed 快照的 form 类型。

    优先从 ``tool_snapshot_meta.json`` 顶层 ``form_type`` 字段读取；
    若元数据缺失，则向后兼容回退到 ``tool_snapshot_list_documents.json``
    中首个文档条目的 ``form_type`` 字段。

    Args:
        snapshot: processed 快照访问对象。
        blob_repository: 文档文件仓储。

    Returns:
        大写 form 类型字符串（如 ``10-K``），无法识别时返回 ``None``。
    """

    meta = _load_json(
        snapshot=snapshot,
        blob_repository=blob_repository,
        file_name="tool_snapshot_meta.json",
    )
    raw = meta.get("form_type", "")
    if str(raw).strip():
        return str(raw).upper()

    list_documents_payload = _load_json(
        snapshot=snapshot,
        blob_repository=blob_repository,
        file_name="tool_snapshot_list_documents.json",
    )
    calls = list_documents_payload.get("calls", [])
    if not isinstance(calls, list):
        return None
    fallback_form_type: Optional[str] = None
    for call in calls:
        if not isinstance(call, dict):
            continue
        response = call.get("response", {})
        if not isinstance(response, dict):
            continue
        documents = response.get("documents", [])
        if not isinstance(documents, list):
            continue
        for document in documents:
            if not isinstance(document, dict):
                continue
            fallback_form_type = str(document.get("form_type", "")).strip()
            if not fallback_form_type:
                continue
            document_id = str(document.get("document_id", "")).strip()
            if document_id == snapshot.document_id:
                return fallback_form_type.upper()
            if fallback_form_type and fallback_form_type:
                fallback_form_type = fallback_form_type.upper()
    return fallback_form_type


def _normalize_form_type(raw: str) -> str:
    """归一化表单类型（去除修订版后缀 /A）。

    例如 ``SC 13G/A`` → ``SC 13G``，``8-K/A`` → ``8-K``。

    Args:
        raw: 原始表单类型字符串。

    Returns:
        归一化后的表单类型。
    """
    normalized = raw.upper().strip()
    if normalized.endswith("/A"):
        normalized = normalized[:-2].strip()
    return normalized


def _discover_form_snapshots(
    base: str,
    tickers: list[str],
    form_type: str,
) -> FormDiscoveryResult:
    """发现指定 form 类型的 processed 快照与完整性缺陷。

    支持修订版归一化：SC 13G/A 与 SC 13G 使用相同的评估配置。

    Args:
        base: 组合根目录（如 ``workspace/portfolio``）。
        tickers: ticker 列表。
        form_type: 目标表单类型（如 ``10-K``、``SC 13G``）。

    Returns:
        样本发现结果。active source filing 若缺失 processed、processed form_type
        不可识别、或 processed form_type 与 source form_type 不一致，都会记为
        完整性硬门禁失败，而不是在发现阶段被静默忽略。
    """

    target = _normalize_form_type(form_type)
    workspace_root = _resolve_workspace_root(base)
    source_repository = FsSourceDocumentRepository(workspace_root)
    processed_repository = FsProcessedDocumentRepository(workspace_root)
    blob_repository = FsDocumentBlobRepository(workspace_root)
    found: list[ProcessedSnapshotDocument] = []
    completeness_failures: list[CompletenessFailure] = []
    for ticker in tickers:
        source_document_ids = source_repository.list_source_document_ids(ticker, SourceKind.FILING)
        active_document_ids: list[str] = []
        for document_id in source_document_ids:
            try:
                source_meta = source_repository.get_source_meta(
                    ticker,
                    document_id,
                    SourceKind.FILING,
                )
            except FileNotFoundError:
                continue
            if bool(source_meta.get("is_deleted", False)):
                continue
            if _normalize_form_type(str(source_meta.get("form_type", ""))) != target:
                continue
            active_document_ids.append(document_id)
        if not active_document_ids:
            continue
        processed_summaries = processed_repository.list_processed_documents(
            ticker,
            DocumentQuery(source_kind=SourceKind.FILING.value),
        )
        summary_by_document_id = {
            summary.document_id: summary
            for summary in processed_summaries
        }
        for document_id in sorted(active_document_ids):
            summary = summary_by_document_id.get(document_id)
            if summary is None:
                completeness_failures.append(
                    CompletenessFailure(
                        ticker=ticker,
                        document_id=document_id,
                        reason="缺少 processed 快照",
                    )
                )
                continue
            snapshot = _build_snapshot_document(
                ticker=ticker,
                document_id=summary.document_id,
            )
            detected = summary.form_type
            if not str(detected or "").strip():
                detected = _detect_form_type(
                    snapshot=snapshot,
                    blob_repository=blob_repository,
                )
            if detected is None:
                completeness_failures.append(
                    CompletenessFailure(
                        ticker=ticker,
                        document_id=document_id,
                        reason="processed 快照缺少可识别的 form_type",
                    )
                )
                continue
            if _normalize_form_type(detected) != target:
                completeness_failures.append(
                    CompletenessFailure(
                        ticker=ticker,
                        document_id=document_id,
                        reason=f"processed form_type 不匹配: {detected}",
                    )
                )
                continue
            found.append(snapshot)
    return FormDiscoveryResult(
        snapshots=found,
        completeness_failures=completeness_failures,
    )


def find_form_dirs(
    base: str,
    tickers: list[str],
    form_type: str,
) -> list[ProcessedSnapshotDocument]:
    """发现所有待评分的指定 form 类型 processed 快照。

    Args:
        base: 组合根目录（如 ``workspace/portfolio``）。
        tickers: ticker 列表。
        form_type: 目标表单类型（如 ``10-K``、``SC 13G``）。

    Returns:
        可进入评分的 processed 快照访问对象列表。
    """

    return _discover_form_snapshots(base, tickers, form_type).snapshots


def _resolve_workspace_root(base: str) -> Path:
    """将 `--base` 解析为 workspace 根目录。

    Args:
        base: CLI 传入路径。支持 workspace 根目录或 portfolio 目录。

    Returns:
        workspace 根目录路径。

    Raises:
        无。
    """

    normalized = Path(str(base)).resolve()
    if normalized.name == "portfolio":
        return normalized.parent
    return normalized


# ---------------------------------------------------------------------------
# Item 提取
# ---------------------------------------------------------------------------

def _extract_item(title: str, *, profile: FormProfile) -> Optional[str]:
    """从标题提取标准化 Item 编号或关键词匹配标签。

    支持三种匹配模式（按优先级）：
    1. Part 前缀模式（10-Q）：``Part X - Item N``
    2. 小数编号模式（8-K）：``Item X.XX``
    3. 简单编号模式（10-K / 20-F / SC 13G）：``Item N``
    4. 关键词匹配模式（6-K / DEF 14A）：标题包含指定关键词

    Args:
        title: section 标题。
        profile: 表单类型配置。

    Returns:
        标准格式（如 ``Item 7A``、``Part I - Item 2``、``Item 2.02``、
        ``Executive Compensation``）；无法提取时返回 ``None``。
    """

    title_str = str(title or "")

    # 模式 1: 10-Q Part 前缀格式
    if profile.use_part_prefix:
        match = PART_ITEM_RE.search(title_str)
        if match is not None:
            part_raw = match.group(1)
            roman_match = re.search(r"(I{1,4})", part_raw)
            if roman_match is not None:
                roman = roman_match.group(1).upper()
                item_raw = re.sub(r"\s+", " ", match.group(2)).strip()
                item_normalized = (
                    "Item" + item_raw[4:]
                    if item_raw.lower().startswith("item")
                    else item_raw
                )
                return f"Part {roman} - {item_normalized}"

    # 模式 2: 8-K 小数编号格式（Item X.XX）
    elif profile.use_decimal_items:
        match = ITEM_DECIMAL_RE.search(title_str)
        if match is not None:
            raw = re.sub(r"\s+", " ", match.group(1)).strip()
            return raw.replace("item", "Item") if raw.lower().startswith("item") else raw

    # 模式 3: 简单编号格式（Item N / Item NA）
    else:
        match = ITEM_RE.search(title_str)
        if match is not None:
            raw = re.sub(r"\s+", " ", match.group(1)).strip()
            return raw.replace("item", "Item") if raw.lower().startswith("item") else raw

    # 模式 4: 关键词匹配回退（6-K / DEF 14A 等无 Item 结构的表单）
    if profile.section_keyword_map:
        title_lower = title_str.lower()
        for label, keywords in profile.section_keyword_map.items():
            if any(kw in title_lower for kw in keywords):
                return label

    return None


# ---------------------------------------------------------------------------
# payload 构建
# ---------------------------------------------------------------------------

def _build_section_payload_maps(
    sections_calls: list[dict[str, Any]],
    read_calls: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """构建章节列表与 ref->payload 映射。

    Args:
        sections_calls: ``get_document_sections`` 调用列表。
        read_calls: ``read_section`` 调用列表。

    Returns:
        ``(sections, read_map)``；若缺失则返回空结构。
    """

    sections: list[dict[str, Any]] = []
    if sections_calls:
        response = sections_calls[0].get("response", {})
        raw_sections = response.get("sections", []) if isinstance(response, dict) else []
        sections = [item for item in raw_sections if isinstance(item, dict)]

    read_map: dict[str, dict[str, Any]] = {}
    for call in read_calls:
        response = call.get("response", {})
        if not isinstance(response, dict):
            continue
        ref = str(response.get("ref", "")).strip()
        if not ref:
            continue
        read_map[ref] = response
    return sections, read_map


def _build_ref_to_item_map(
    read_map: dict[str, dict[str, Any]],
    *,
    profile: FormProfile,
    sections: Optional[list[dict[str, Any]]] = None,
) -> dict[str, str]:
    """构建 ref -> Item 标准键的映射，包含祖先节点传播。

    对于 title 直接匹配 Item 的 ref，直接记录。
    对于子节 ref（title 不含 Item），沿 parent_ref 向上追溯，
    找到最近的 Item 祖先后记录。

    Args:
        read_map: read_section 映射。
        profile: 表单类型配置。
        sections: get_document_sections 章节列表，用于构建 parent_ref 索引。

    Returns:
        ref -> Item 标准键映射。
    """

    # 构建 ref -> parent_ref 的快速查找表
    parent_map: dict[str, str] = {}
    if sections:
        for s in sections:
            ref = str(s.get("ref", "") or "").strip()
            parent_ref = str(s.get("parent_ref", "") or "").strip()
            if ref and parent_ref:
                parent_map[ref] = parent_ref

    # 第一轮：直接 title 匹配
    ref_to_item: dict[str, str] = {}
    for ref, payload in read_map.items():
        title = str(payload.get("title", ""))
        item = _extract_item(title, profile=profile)
        if item is not None:
            ref_to_item[ref] = item

    # 第二轮：沿 parent_ref 链追溯，为子节填充所属 Item
    def _resolve_item(ref: str) -> Optional[str]:
        """向上追溯 parent_ref 链，返回最近的 Item 标准键。"""
        visited: set[str] = set()
        current = ref
        while current and current not in visited:
            if current in ref_to_item:
                return ref_to_item[current]
            visited.add(current)
            current = parent_map.get(current, "")
        return None

    for ref in list(read_map.keys()):
        if ref in ref_to_item:
            continue
        item = _resolve_item(ref)
        if item is not None:
            ref_to_item[ref] = item

    return ref_to_item


def _build_item_content_len(
    read_map: dict[str, dict[str, Any]],
    *,
    profile: FormProfile,
    sections: Optional[list[dict[str, Any]]] = None,
) -> dict[str, int]:
    """构建 Item -> 累计内容长度映射。

    将所有属于同一 Item 的 section（含父节与子节）的内容长度求和。
    通过 ``_build_ref_to_item_map`` 沿 parent_ref 链追溯，使子节内容
    也归属到对应 Item，避免因父节 intro 过短而低估 Item 内容量。

    Args:
        read_map: read_section 映射。
        profile: 表单类型配置。
        sections: get_document_sections 章节列表，用于构建父子索引。

    Returns:
        Item 标准键 → 累计内容长度。
    """

    ref_to_item = _build_ref_to_item_map(read_map, profile=profile, sections=sections)
    item_content_len: dict[str, int] = {}
    for ref, payload in read_map.items():
        item = ref_to_item.get(ref)
        if item is None:
            continue
        content_len = len(str(payload.get("content", "")))
        item_content_len[item] = item_content_len.get(item, 0) + content_len
    return item_content_len


def _build_item_content_text(
    read_map: dict[str, dict[str, Any]],
    *,
    profile: FormProfile,
) -> dict[str, str]:
    """构建 Item -> 内容文本映射（取最长内容）。

    与 ``_build_item_content_len`` 类似，但保留实际文本内容，
    用于交叉引用检测等需要分析文本语义的场景。

    Args:
        read_map: read_section 映射。
        profile: 表单类型配置。

    Returns:
        Item 标准键 → 内容文本。
    """

    item_content_text: dict[str, str] = {}
    for payload in read_map.values():
        title = str(payload.get("title", ""))
        item = _extract_item(title, profile=profile)
        if item is None:
            continue
        content = str(payload.get("content", ""))
        old_text = item_content_text.get(item, "")
        if len(content) > len(old_text):
            item_content_text[item] = content
    return item_content_text


def _is_sec_cross_reference(content: str) -> bool:
    """判断章节内容是否为 SEC 法定交叉引用。

    SEC Regulation S-K §229.10(d) 允许 "incorporation by reference"。
    SEC Form 10-K General Instructions G(2) 允许 Item 8 通过引用纳入
    年报中的 Financial Statements（如 "contained on pages F-1 through F-46"）。

    判定条件：内容长度 < ``_CROSS_REFERENCE_MAX_LEN`` 且匹配交叉引用特征模式。

    Args:
        content: 章节内容文本。

    Returns:
        ``True`` 表示该内容为 SEC 法定交叉引用。
    """
    if not content or len(content) > _CROSS_REFERENCE_MAX_LEN:
        return False
    return _CROSS_REFERENCE_RE.search(content) is not None


# ---------------------------------------------------------------------------
# 维度 A：结构完整性（25 分）
# ---------------------------------------------------------------------------

def _score_structure(
    sections: list[dict[str, Any]],
    item_content_len: dict[str, int],
    profile: FormProfile,
) -> DimensionScore:
    """计算维度 A：结构完整性（25 分）。

    Args:
        sections: section 列表。
        item_content_len: Item 长度映射。
        profile: 表单类型配置。

    Returns:
        维度评分结果。
    """

    points = 0.0
    details: dict[str, Any] = {}

    # A1: Item 顺序（8 分）
    sequence: list[str] = []
    for sec in sections:
        item = _extract_item(str(sec.get("title", "")), profile=profile)
        if item is not None:
            sequence.append(item)
    ordered: Optional[bool]
    # 无标准 Item 顺序的表单（如 6-K / DEF 14A）将 A1 视为不适用，默认满分。
    if not profile.item_order:
        ordered = None
        points += 8.0
    else:
        recognized_in_order = [item for item in sequence if item in profile.item_order]
        # 对有标准 Item 的表单，若一个都无法识别则不得分，避免“空序列误判有序”。
        if not recognized_in_order:
            ordered = False
        else:
            last_index = -1
            ordered = True
            for item in recognized_in_order:
                idx = profile.item_order.index(item)
                if idx < last_index:
                    ordered = False
                    break
                last_index = idx
        if ordered:
            points += 8.0
    details["order_ok"] = ordered
    details["recognized_item_count"] = len(sequence)

    # A2: 关键 Item 存在（10 分，缺一个扣 2）
    recognized_items = set(sequence)
    missing_required = [
        item for item in profile.key_items_required
        if item not in recognized_items
    ]
    points += max(0.0, 10.0 - 2.0 * len(missing_required))
    details["missing_required_items"] = missing_required

    # A3: section_count 合理（7 分，超出区间每 5 个扣 2）
    section_count = len(sections)
    deviation = 0
    if section_count < profile.section_count_low:
        deviation = profile.section_count_low - section_count
    elif section_count > profile.section_count_high:
        deviation = section_count - profile.section_count_high
    penalty_steps = math.ceil(deviation / 5) if deviation > 0 else 0
    points += max(0.0, 7.0 - 2.0 * penalty_steps)
    details["section_count"] = section_count

    return DimensionScore(points=points, max_points=25.0, details=details)


# ---------------------------------------------------------------------------
# 维度 B：内容充足性（30 分）
# ---------------------------------------------------------------------------

def _score_content(
    item_content_len: dict[str, int],
    profile: FormProfile,
    item_content_text: Optional[dict[str, str]] = None,
) -> DimensionScore:
    """计算维度 B：内容充足性（30 分）。

    对于 SEC 法定交叉引用（如 Item 8 引用 F-pages 财务报表），
    即使内容长度低于阈值也可视为通过；但仅对
    ``profile.cross_reference_exempt_items`` 中声明的 Item 生效，
    以避免短文本误判。

    Args:
        item_content_len: Item 长度映射。
        profile: 表单类型配置。
        item_content_text: Item 内容文本映射（用于交叉引用检测），可选。

    Returns:
        维度评分结果。
    """

    # 事件驱动型表单（如 8-K）不设内容阈值，默认满分
    if not profile.content_thresholds:
        return DimensionScore(
            points=30.0,
            max_points=30.0,
            details={
                "item_lengths": dict(item_content_len),
                "item_pass": {},
                "cross_references": [],
                "skip_reason": "no_content_thresholds",
            },
        )

    points = 0.0
    details: dict[str, Any] = {
        "item_lengths": dict(item_content_len),
        "item_pass": {},
        "cross_references": [],
    }
    for item, threshold in profile.content_thresholds.items():
        length = item_content_len.get(item, 0)
        passed = length >= threshold
        # SEC 交叉引用豁免：仅对 profile 明确允许的 Item 生效。
        if not passed and item_content_text is not None:
            if item in profile.cross_reference_exempt_items:
                content = item_content_text.get(item, "")
                if _is_sec_cross_reference(content):
                    passed = True
                    details["cross_references"].append(item)
        details["item_pass"][item] = passed
        if passed:
            points += profile.content_weights[item]
    return DimensionScore(points=points, max_points=30.0, details=details)


# ---------------------------------------------------------------------------
# 维度 C：检索可用性（15 分）
# ---------------------------------------------------------------------------

def _tokenize_query(query: str) -> list[str]:
    """将查询词切分为可匹配 token。

    Args:
        query: 查询文本。

    Returns:
        归一化 token 列表（长度至少为 3）。

    Raises:
        无。
    """

    raw_tokens = re.split(r"\W+", str(query or "").lower())
    return [token for token in raw_tokens if len(token) >= 3]


def _query_hit_in_snippet(query: str, snippet: str) -> bool:
    """判断 query 是否在片段文本中有可用命中。

    Args:
        query: 查询文本。
        snippet: 片段文本。

    Returns:
        是否命中。

    Raises:
        无。
    """

    normalized = str(snippet or "").lower()
    tokens = _tokenize_query(query)
    if not tokens:
        return bool(normalized.strip())
    return any(token in normalized for token in tokens)


def _extract_match_text(match: dict[str, Any]) -> str:
    """从搜索命中项中提取文本内容（兼容新旧格式）。

    新格式：``evidence.context``；旧格式：``snippet``。

    Args:
        match: 命中项字典。

    Returns:
        文本字符串。
    """
    evidence = match.get("evidence")
    if isinstance(evidence, dict):
        text = evidence.get("context") or evidence.get("matched_text") or ""
        return str(text)
    # 旧格式回退
    return str(match.get("snippet", ""))


def _validate_search_request_contract(request: dict[str, Any], *, index: int) -> tuple[str, float]:
    """校验 `search_document` 请求契约并返回关键字段。

    Args:
        request: 请求字典。
        index: 调用序号（从 1 开始）。

    Returns:
        `(query_text, query_weight)`。

    Raises:
        ValueError: 必填字段缺失或非法时抛出。
    """

    for key in ("query_id", "query_text", "query_intent", "query_weight"):
        if key not in request:
            raise ValueError(f"search_document.calls[{index}].request 缺少 {key}")
    query_id = str(request.get("query_id", "")).strip()
    query_text = str(request.get("query_text", "")).strip()
    query_intent = str(request.get("query_intent", "")).strip()
    if not query_id or not query_text or not query_intent:
        raise ValueError(f"search_document.calls[{index}] 请求字段不能为空")
    query_weight = request.get("query_weight")
    if not isinstance(query_weight, (int, float)) or float(query_weight) <= 0:
        raise ValueError(
            f"search_document.calls[{index}].request.query_weight 必须为正数"
        )
    return query_text, float(query_weight)


def _is_usable_match(match: dict[str, Any]) -> bool:
    """判断搜索命中是否可作为有效证据。

    Args:
        match: 命中项字典。

    Returns:
        若 evidence/snippet 与 ``section.ref`` 均有效则返回 ``True``。

    Raises:
        无。
    """

    section = match.get("section") or {}
    section_ref = str(section.get("ref", "")).strip()
    text = _extract_match_text(match).strip()
    return bool(section_ref and text)


def _is_high_quality_match(match: dict[str, Any]) -> bool:
    """判断搜索命中是否满足高质量证据标准。

    Args:
        match: 命中项字典。

    Returns:
        满足 evidence/snippet 长度区间且 section_ref 有效时返回 ``True``。

    Raises:
        无。
    """

    if not _is_usable_match(match):
        return False
    text = _extract_match_text(match)
    return 120 <= len(text) <= 1200


def _score_search_v2(
    search_calls: list[dict[str, Any]],
    *,
    form_type: str,
    snapshot_meta: dict[str, Any],
) -> DimensionScore:
    """计算维度 C v2：覆盖率 + 证据质量 + 检索效率（15 分）。

    Args:
        search_calls: `search_document` 调用列表。
        form_type: 当前文档表单类型。
        snapshot_meta: `tool_snapshot_meta.json` 已校验载荷。

    Returns:
        维度评分结果。

    Raises:
        ValueError: 快照契约缺失或字段非法时抛出。
    """

    pack_name = str(snapshot_meta.get("search_query_pack_name", "")).strip()
    pack_version = str(snapshot_meta.get("search_query_pack_version", "")).strip()
    query_total_expected = int(snapshot_meta.get("search_query_count", 0))
    if not pack_name or not pack_version:
        raise ValueError("tool_snapshot_meta 缺少 search_query_pack_name/version")
    if query_total_expected <= 0:
        raise ValueError("tool_snapshot_meta.search_query_count 必须大于 0")
    if len(search_calls) != query_total_expected:
        raise ValueError(
            "search_document 调用数量与 tool_snapshot_meta.search_query_count 不一致: "
            f"{len(search_calls)} != {query_total_expected}"
        )

    threshold_profile = _resolve_search_threshold_profile(
        pack_name=pack_name,
        form_type=form_type,
    )

    weighted_hit_sum = 0.0
    weighted_query_sum = 0.0
    hit_query_count = 0
    high_quality_query_count = 0
    exact_hit_query_count = 0
    all_hit_query_count = 0

    for index, call in enumerate(search_calls, start=1):
        request = call.get("request", {})
        response = call.get("response", {})
        if not isinstance(request, dict):
            raise ValueError(f"search_document.calls[{index}].request 必须是对象")
        if not isinstance(response, dict):
            raise ValueError(f"search_document.calls[{index}].response 必须是对象")
        query_text, query_weight = _validate_search_request_contract(request, index=index)
        weighted_query_sum += query_weight

        matches_raw = response.get("matches", [])
        matches = [item for item in matches_raw if isinstance(item, dict)] if isinstance(matches_raw, list) else []
        usable_matches = [match for match in matches if _is_usable_match(match)]
        has_hit = False
        if usable_matches:
            has_hit = any(_query_hit_in_snippet(query_text, _extract_match_text(match)) for match in usable_matches)
            if not has_hit:
                # 混合检索下，命中片段不一定包含原查询词；存在有效命中则视为召回成功。
                has_hit = True
        if has_hit:
            weighted_hit_sum += query_weight
            hit_query_count += 1
            all_hit_query_count += 1
            if any(_is_high_quality_match(match) for match in usable_matches):
                high_quality_query_count += 1

        diagnostics = response.get("diagnostics", {})
        if not isinstance(diagnostics, dict):
            raise ValueError(f"search_document.calls[{index}].response.diagnostics 必须是对象")
        strategy_hit_counts = diagnostics.get("strategy_hit_counts", {})
        if not isinstance(strategy_hit_counts, dict):
            raise ValueError(
                f"search_document.calls[{index}].response.diagnostics.strategy_hit_counts 必须是对象"
            )
        exact_hits = strategy_hit_counts.get(SEARCH_STRATEGY_EXACT, 0)
        if has_hit and isinstance(exact_hits, (int, float)) and float(exact_hits) > 0:
            exact_hit_query_count += 1

    if weighted_query_sum <= 0:
        raise ValueError("search_document 查询权重总和必须大于 0")

    coverage_rate_weighted = weighted_hit_sum / weighted_query_sum
    evidence_quality_rate = (
        high_quality_query_count / hit_query_count if hit_query_count > 0 else 0.0
    )
    efficiency_rate = (
        exact_hit_query_count / all_hit_query_count if all_hit_query_count > 0 else 0.0
    )

    c1_points = 0.0
    if coverage_rate_weighted >= threshold_profile.t9:
        c1_points = 9.0
    elif coverage_rate_weighted >= threshold_profile.t7:
        c1_points = 7.0
    elif coverage_rate_weighted >= threshold_profile.t5:
        c1_points = 5.0

    c2_points = 0.0
    if evidence_quality_rate >= 0.9:
        c2_points = 4.0
    elif evidence_quality_rate >= 0.75:
        c2_points = 2.0

    c3_points = 0.0
    if efficiency_rate >= 0.7:
        c3_points = 2.0
    elif efficiency_rate >= 0.5:
        c3_points = 1.0

    failed_buckets: list[str] = []
    if c1_points < 9.0:
        failed_buckets.append("coverage")
    if c2_points < 4.0:
        failed_buckets.append("evidence_quality")
    if c3_points < 2.0:
        failed_buckets.append("efficiency")

    return DimensionScore(
        points=c1_points + c2_points + c3_points,
        max_points=15.0,
        details={
            "coverage_rate_weighted": round(coverage_rate_weighted, 4),
            "evidence_quality_rate": round(evidence_quality_rate, 4),
            "efficiency_rate": round(efficiency_rate, 4),
            "hit_query_count": hit_query_count,
            "query_total": len(search_calls),
            "query_total_expected": query_total_expected,
            "query_weight_sum": round(weighted_query_sum, 4),
            "exact_hit_query_count": exact_hit_query_count,
            "all_hit_query_count": all_hit_query_count,
            "threshold_profile_id": threshold_profile.profile_id,
            "thresholds": {
                "coverage_t5": threshold_profile.t5,
                "coverage_t7": threshold_profile.t7,
                "coverage_t9": threshold_profile.t9,
                "evidence_quality_t2": 0.75,
                "evidence_quality_t4": 0.9,
                "efficiency_t1": 0.5,
                "efficiency_t2": 0.7,
            },
            "pack_name": pack_name,
            "pack_version": pack_version,
            "form_type_normalized": _normalize_form_type(form_type),
            "failed_buckets": failed_buckets,
        },
    )


# ---------------------------------------------------------------------------
# 维度 D：一致性与数据质量（15 分）
# ---------------------------------------------------------------------------

def _extract_table_refs_from_sections(read_map: dict[str, dict[str, Any]]) -> set[str]:
    """从 read_section 响应提取表格引用集合。

    注意：read_section 已移除 tables 字段（LLM 应通过 list_tables 获取），
    此函数保留接口但始终返回空集合，D1 悬挂检查改为仅依赖
    list_tables → sections 的反向验证。
    """

    return set()


def _markdown_has_data(markdown: str) -> bool:
    """检查 markdown 格式表格是否含有实际数据单元格。

    空单元格行如 ``|  |  |  |`` 视为无实际数据。

    Args:
        markdown: 表格的 markdown 字符串。

    Returns:
        是否有非空数据单元格。
    """
    if not markdown.strip():
        return False

    def _row_has_nonempty_cell(line: str) -> bool:
        """判断单行是否存在非空单元格。"""
        cells = [cell.strip() for cell in line.split("|")]
        cells = [cell for cell in cells if cell]
        return any(cells)

    def _is_markdown_separator_row(line: str) -> bool:
        """判断是否为 markdown 表头分隔行（如 ``|---|:---:|``）。"""
        normalized = line.strip()
        if not (normalized.startswith("|") and normalized.endswith("|")):
            return False
        parts = [part.strip() for part in normalized.strip("|").split("|")]
        if not parts:
            return False
        for part in parts:
            if not part:
                return False
            if "-" not in part:
                return False
            if any(ch not in {"-", ":"} for ch in part):
                return False
        return True

    lines = [line.strip() for line in markdown.strip().split("\n") if line.strip()]
    separator_idx = -1
    for idx, line in enumerate(lines):
        if _is_markdown_separator_row(line):
            separator_idx = idx
            break

    # 标准 markdown 表格：分隔行后的行才算数据行。
    candidate_rows = lines[separator_idx + 1:] if separator_idx >= 0 else lines
    for row in candidate_rows:
        if _row_has_nonempty_cell(row):
            return True
    return False


def _rows_has_data(rows: Any) -> bool:
    """检查 rows 列表是否含有实际数据。

    SEC 工具以 ``data.rows`` (list[dict]) 形式返回 records 类型的结构化行数据，
    每行为 ``{col_name: value}`` 字典。

    Args:
        rows: data.rows 列表。

    Returns:
        是否有非空记录行。
    """
    if not isinstance(rows, list):
        return False
    for row in rows:
        if isinstance(row, dict) and any(
            v is not None and str(v).strip()
            for v in row.values()
        ):
            return True
        if isinstance(row, (list, tuple)) and any(
            v is not None and str(v).strip()
            for v in row
        ):
            return True
    return False


def _table_data_has_content(data: dict[str, Any]) -> bool:
    """检查表格数据是否含有实际内容。

    SEC 工具的 ``get_table`` 返回的 ``data`` 字典通过 ``data.kind`` 指示格式：

    - ``kind=markdown``  → 数据在 ``data.markdown`` (str)
    - ``kind=records``   → 数据在 ``data.rows`` (list[dict])
    - ``kind=raw_text``  → 数据在 ``data.text`` (str)

    本函数检查所有三种格式，只要任一含数据即视为非空。

    Args:
        data: 表格响应中的 data 字典。

    Returns:
        是否有数据内容。
    """
    # 检查 markdown 格式（kind=markdown 时数据存于 data.markdown）
    markdown = data.get("markdown")
    if markdown and _markdown_has_data(str(markdown)):
        return True

    # 检查 rows 格式（kind=records 时数据存于 data.rows）
    rows = data.get("rows")
    if rows and _rows_has_data(rows):
        return True

    # 检查 raw_text 格式（kind=raw_text 时数据存于 data.text）
    text = data.get("text")
    if text and str(text).strip():
        return True

    return False


def _evaluate_table_data_quality(
    get_table_calls: list[dict[str, Any]],
) -> tuple[float, dict[str, Any]]:
    """评估表格数据质量：非空表格占比。

    SEC 工具返回的表格有三种数据格式（markdown / records / raw_text），
    只要任一格式含有实际数据，即计入非空表格。

    Args:
        get_table_calls: ``get_table`` 调用列表。

    Returns:
        ``(D4 分数, 详情字典)``。
    """
    total_tables = 0
    nonempty_tables = 0

    for call in get_table_calls:
        response = call.get("response", {})
        if not isinstance(response, dict):
            continue
        total_tables += 1

        # 表格内容位于 response.data
        data = response.get("data", {})
        if not isinstance(data, dict):
            continue

        if _table_data_has_content(data):
            nonempty_tables += 1

    if total_tables == 0:
        ratio = 1.0
    else:
        ratio = nonempty_tables / total_tables

    # D4: 表格数据质量（3 分）
    if ratio >= 0.9:
        d4_points = 3.0
    elif ratio >= 0.7:
        d4_points = 2.0
    else:
        d4_points = 0.0

    details = {
        "total_tables": total_tables,
        "nonempty_tables": nonempty_tables,
        "nonempty_ratio": round(ratio, 4),
    }
    return d4_points, details


def _evaluate_table_caption_fill(
    list_tables_calls: list[dict[str, Any]],
) -> tuple[float, dict[str, Any]]:
    """评估表格 caption 填充率（D5, 2 分）。

    衡量处理器为表格生成描述性标题的能力，包括 HTML ``<caption>`` 标签
    原生提供和从 ``context_before`` 自动推断两种来源。

    caption 填充率是可被持续优化的信号：改进推断算法 → 填充率上升 → D5 得分提高。

    Args:
        list_tables_calls: ``list_tables`` 调用列表。

    Returns:
        ``(D5 分数, 详情字典)``。
    """
    total_tables = 0
    caption_filled = 0

    for call in list_tables_calls:
        response = call.get("response", {})
        if not isinstance(response, dict):
            continue
        tables = response.get("tables", [])
        if not isinstance(tables, list):
            continue
        for table in tables:
            if not isinstance(table, dict):
                continue
            total_tables += 1
            cap = table.get("caption")
            if cap and str(cap).strip():
                caption_filled += 1

    # 表格数量过少时默认满分（样本不足，指标不可靠）
    if total_tables < 5:
        return 2.0, {
            "caption_total_tables": total_tables,
            "caption_filled": caption_filled,
            "caption_skip_reason": "too_few_tables",
        }

    ratio = caption_filled / total_tables

    # D5: caption 填充率（2 分）
    if ratio >= 0.4:
        d5_points = 2.0
    elif ratio >= 0.2:
        d5_points = 1.0
    else:
        d5_points = 0.0

    return d5_points, {
        "caption_total_tables": total_tables,
        "caption_filled": caption_filled,
        "caption_fill_ratio": round(ratio, 4),
    }


def _evaluate_financial_statement_depth(
    fs_calls: list[dict[str, Any]],
) -> tuple[float, dict[str, Any]]:
    """评估财务报表完整性与深度。

    D3 分为三层：
    - 五大报表存在且 xbrl 质量（2 分）
    - 平均行数 ≥ 10（1 分）
    - 所有报表期数 ≥ 2（1 分）

    Args:
        fs_calls: ``get_financial_statement`` 调用列表。

    Returns:
        ``(D3 分数, 详情字典)``。
    """
    available_statements: set[str] = set()
    row_counts: list[int] = []
    period_counts: list[int] = []

    for call in fs_calls:
        request = call.get("request", {})
        response = call.get("response", {})
        if not isinstance(request, dict) or not isinstance(response, dict):
            continue
        statement_type = str(request.get("statement_type", "")).strip()
        # 判断报表是否可用（schema 定义 data_quality: "xbrl" | "extracted" | "partial"）
        data_quality = str(response.get("data_quality", "")).strip().lower()
        has_rows = bool(response.get("rows"))
        # 仅 xbrl/extracted 质量标记本身就可信；若为 partial，必须有实际行数据才算可用
        # （避免 taxonomy 解析“尝试了但没提到任何数据”的情况被误计为有效）
        usable = data_quality in ("xbrl", "extracted") or has_rows
        if statement_type and usable:
            available_statements.add(statement_type)
            rows = response.get("rows", [])
            row_counts.append(len(rows) if isinstance(rows, list) else 0)
            periods = response.get("periods", [])
            period_counts.append(len(periods) if isinstance(periods, list) else 0)

    missing_count = len(
        [st for st in DEFAULT_STATEMENT_TYPES if st not in available_statements]
    )

    # D3a: 五大报表存在且可用（2 分）
    d3a = 2.0 if missing_count == 0 else max(0.0, 2.0 - float(missing_count) * 0.5)

    # D3b: 平均行数 ≥ 10（1 分）
    mean_rows = (sum(row_counts) / len(row_counts)) if row_counts else 0.0
    d3b = 1.0 if mean_rows >= 10 else 0.0

    # D3c: 所有报表至少 2 个期间（1 分）
    all_periods_ok = all(pc >= 2 for pc in period_counts) if period_counts else False
    d3c = 1.0 if all_periods_ok else 0.0

    d3_points = d3a + d3b + d3c

    details = {
        "available_statements": sorted(available_statements),
        "missing_statement_count": missing_count,
        "mean_row_count": round(mean_rows, 1),
        "period_counts": period_counts,
        "all_periods_ge2": all_periods_ok,
    }
    return d3_points, details


def _evaluate_six_k_financial_statement_depth(
    fs_calls: list[dict[str, Any]],
) -> tuple[float, dict[str, Any]]:
    """评估 6-K 财务报表可提取性。

    6-K 的评估目标不是五大报表齐备，而是“LLM 是否能直接消费
    最新财务结果”。因此 D3 采用 release core set：

    - `income` 与 `balance_sheet` 为核心报表（2 分）
    - 核心报表平均行数达标（1 分）
    - 至少一个核心报表具备 >=2 个期间（1 分）

    `cash_flow` 仅作补充，不是硬要求。

    Args:
        fs_calls: ``get_financial_statement`` 调用列表。

    Returns:
        ``(D3 分数, 详情字典)``。
    """

    usable_calls: dict[str, dict[str, Any]] = {}
    for call in fs_calls:
        request = call.get("request", {})
        response = call.get("response", {})
        if not isinstance(request, dict) or not isinstance(response, dict):
            continue
        statement_type = str(request.get("statement_type", "")).strip()
        if statement_type not in {"income", "balance_sheet", "cash_flow"}:
            continue
        data_quality = str(response.get("data_quality", "")).strip().lower()
        has_rows = bool(response.get("rows"))
        # 仅 xbrl/extracted 质量标记本身就可信；若为 partial，必须有实际行数据才算可用
        usable = data_quality in {"xbrl", "extracted"} or has_rows
        if usable:
            usable_calls[statement_type] = response

    core_available = [
        statement_type
        for statement_type in ("income", "balance_sheet")
        if statement_type in usable_calls
    ]
    d3a = float(len(core_available))

    core_row_counts: list[int] = []
    core_period_counts: list[int] = []
    for statement_type in core_available:
        response = usable_calls[statement_type]
        rows = response.get("rows", [])
        periods = response.get("periods", [])
        core_row_counts.append(len(rows) if isinstance(rows, list) else 0)
        core_period_counts.append(len(periods) if isinstance(periods, list) else 0)

    mean_rows = (sum(core_row_counts) / len(core_row_counts)) if core_row_counts else 0.0
    d3b = 1.0 if mean_rows >= 8 else 0.0
    d3c = 1.0 if any(period_count >= 2 for period_count in core_period_counts) else 0.0

    details = {
        "d3_mode": "six_k_release_core",
        "available_statements": sorted(usable_calls.keys()),
        "core_available": core_available,
        "mean_row_count": round(mean_rows, 1),
        "period_counts": core_period_counts,
        "core_periods_ge2": any(period_count >= 2 for period_count in core_period_counts),
    }
    return d3a + d3b + d3c, details


def _score_consistency(
    sections: list[dict[str, Any]],
    read_map: dict[str, dict[str, Any]],
    list_tables_calls: list[dict[str, Any]],
    fs_calls: list[dict[str, Any]],
    get_table_calls: list[dict[str, Any]],
    profile: FormProfile,
) -> DimensionScore:
    """计算维度 D：一致性与数据质量（15 分）。

    子项分配：
    - D1: 表格 ref 可追溯（3 分）
    - D2: 跨工具 ref 一致（3 分）
    - D3: 财报完整性（4 分）= 存在(2) + 行数(1) + 期数(1)
    - D4: 表格数据质量（3 分）
    - D5: 表格 caption 填充率（2 分）

    对于不含 XBRL 财务报表的表单（6-K、8-K、SC 13G、DEF 14A），
    D3 默认满分（4/4）。

    Args:
        sections: section 列表。
        read_map: read_section 映射。
        list_tables_calls: ``list_tables`` 调用列表。
        fs_calls: ``get_financial_statement`` 调用列表。
        get_table_calls: ``get_table`` 调用列表。
        profile: 表单类型配置。

    Returns:
        维度评分结果。
    """

    section_refs = {str(sec.get("ref", "")) for sec in sections if str(sec.get("ref", "")).strip()}
    read_refs = set(read_map.keys())

    list_table_refs: set[str] = set()
    table_section_refs: list[str] = []
    if list_tables_calls:
        response = list_tables_calls[0].get("response", {})
        tables = response.get("tables", []) if isinstance(response, dict) else []
        for table in tables:
            if not isinstance(table, dict):
                continue
            # 跳过 null/None 值，避免 str(None) → "None" 导致虚假悬挂
            raw_table_ref = table.get("table_ref")
            if raw_table_ref is not None:
                table_ref = str(raw_table_ref).strip()
                if table_ref:
                    list_table_refs.add(table_ref)
            raw_within = table.get("within_section")
            if isinstance(raw_within, dict):
                raw_section_ref = raw_within.get("ref")
            else:
                raw_section_ref = None
            if raw_section_ref is not None:
                table_section_ref = str(raw_section_ref).strip()
                if table_section_ref:
                    table_section_refs.append(table_section_ref)

    section_table_refs = _extract_table_refs_from_sections(read_map)
    dangling_table_refs = sorted(ref for ref in section_table_refs if ref not in list_table_refs)
    dangling_table_sections = sorted(ref for ref in table_section_refs if ref not in section_refs)

    points = 0.0

    # D1: 悬挂 table refs（3 分）
    d1_ok = not dangling_table_refs and not dangling_table_sections
    if d1_ok:
        points += 3.0

    # D2: 跨工具 ref 一致（3 分）
    missing_in_read = sorted(ref for ref in section_refs if ref not in read_refs)
    extra_in_read = sorted(ref for ref in read_refs if ref not in section_refs)
    ref_consistent = not missing_in_read and not extra_in_read
    if ref_consistent:
        points += 3.0

    # D3: 财报完整性（4 分）
    # 不含 XBRL 的表单类型默认满分
    if profile.form_type == "6-K":
        d3_points, d3_details = _evaluate_six_k_financial_statement_depth(fs_calls)
    elif profile.has_xbrl_financials:
        d3_points, d3_details = _evaluate_financial_statement_depth(fs_calls)
    else:
        d3_points = 4.0
        d3_details = {"skip_reason": "no_xbrl_expected"}
    points += d3_points

    # D4: 表格数据质量（3 分）
    d4_points, d4_details = _evaluate_table_data_quality(get_table_calls)
    points += d4_points

    # D5: 表格 caption 填充率（2 分）
    d5_points, d5_details = _evaluate_table_caption_fill(list_tables_calls)
    points += d5_points

    return DimensionScore(
        points=points,
        max_points=15.0,
        details={
            "dangling_table_refs": dangling_table_refs,
            "dangling_table_sections": dangling_table_sections,
            "ref_consistent": ref_consistent,
            "missing_in_read": missing_in_read,
            "extra_in_read": extra_in_read,
            **d3_details,
            **d4_details,
            **d5_details,
        },
    )


# ---------------------------------------------------------------------------
# 维度 E：噪声与完整性（15 分）
# ---------------------------------------------------------------------------

def _detect_truncated_sections(
    read_map: dict[str, dict[str, Any]],
    profile: Optional[FormProfile] = None,
    parent_refs: Optional[set[str]] = None,
) -> list[str]:
    """检测以悬挂介词/连词结尾的 section（疑似句子中断）。

    对 SEC 法定交叉引用内容豁免：交叉引用常以 "refer to" / "see" 等
    词汇结尾，这是完整的法律语言而非截断。

    对有子节的父节豁免：父节内容在子节分割点处自然截断，属于结构性
    分割而非实际截断，子节的内容是完整的延续，不应误报为截断。

    Args:
        read_map: read_section 映射。
        profile: 表单类型配置。提供时，交叉引用豁免仅对该 profile
            允许的 Item 生效；不提供时按通用规则判定。
        parent_refs: 存在子节的父节 ref 集合；提供时这些节不参与截断检测。

    Returns:
        截断的 section ref 列表。
    """
    truncated: list[str] = []
    for ref, payload in read_map.items():
        # 父节豁免：父节内容在子节分割点处自然终止，不视为截断
        if parent_refs and ref in parent_refs:
            continue
        content = str(payload.get("content", "")).rstrip()
        if not content:
            continue
        # 交叉引用豁免：
        # 1) 未提供 profile 时，沿用通用判定（用于独立单元测试）。
        # 2) 提供 profile 时，仅 profile 允许的 Item 生效，避免误豁免。
        if _is_sec_cross_reference(content):
            if profile is None:
                continue
            title = str(payload.get("title", ""))
            item = _extract_item(title, profile=profile)
            if item is not None and item in profile.cross_reference_exempt_items:
                continue
        # 取末尾 80 字符检测
        tail = content[-80:]
        if TRUNCATION_TAIL_RE.search(tail):
            truncated.append(ref)
    return truncated


def _detect_boundary_leakage(
    read_map: dict[str, dict[str, Any]],
) -> list[str]:
    """检测 section 末尾是否包含其他 Part 的标题文本（边界溢出）。

    典型案例：10-Q Part I Item 4 末尾包含 "PART II — OTHER INFORMATION"。

    Args:
        read_map: read_section 映射。

    Returns:
        发生溢出的 section ref 列表。
    """
    leaked: list[str] = []
    for ref, payload in read_map.items():
        content = str(payload.get("content", "")).rstrip()
        if not content:
            continue
        # 检查末尾 200 字符是否有其他 Part 的标题
        tail = content[-200:]
        if BOUNDARY_LEAK_RE.search(tail):
            leaked.append(ref)
    return leaked


def _count_near_empty_sections(
    read_map: dict[str, dict[str, Any]],
    profile: FormProfile,
) -> int:
    """统计近空 section 数量（排除 SEC 白名单 Item）。

    近空定义：内容长度 1–100 字符（normalized），且不在
    ``profile.near_empty_whitelist`` 白名单中。

    白名单匹配逻辑：按 ``_extract_item`` 输出的标准键原样匹配。
    对 10-Q 保留 Part 前缀，避免 Part I/II 同号 Item 混淆。

    Args:
        read_map: read_section 映射。
        profile: 表单类型配置。

    Returns:
        不在白名单中的近空 section 数量。
    """
    whitelist = profile.near_empty_whitelist
    count = 0
    for payload in read_map.values():
        content = str(payload.get("content", ""))
        normalized_len = len(re.sub(r"\s+", " ", content).strip())
        if normalized_len < 1 or normalized_len > 100:
            continue
        # 提取 Item 名称，检查是否在白名单中
        title = str(payload.get("title", ""))
        item = _extract_item(title, profile=profile)
        if item is None:
            count += 1
            continue
        if item in whitelist:
            continue
        count += 1
    return count


def _score_noise_integrity(
    read_map: dict[str, dict[str, Any]],
    cfg: ScoreConfig,
    profile: FormProfile,
    sections: Optional[list[dict[str, Any]]] = None,
) -> DimensionScore:
    """计算维度 E：噪声与完整性（15 分）。

    子项分配：
    - E1: 空/近空 section（3 分）
    - E2: Mojibake（3 分）
    - E3: 最大 section 尺寸（3 分）
    - E4: 章节截断检测（3 分）
    - E5: 边界溢出检测（3 分）

    Args:
        read_map: read_section 映射。
        cfg: CI 阈值配置。
        profile: 表单类型配置。
        sections: get_document_sections 章节列表，用于构建父节豁免集合。

    Returns:
        维度评分结果。
    """

    contents = [str(payload.get("content", "")) for payload in read_map.values()]
    normalized_lengths = [len(re.sub(r"\s+", " ", text).strip()) for text in contents]

    empty_count = sum(1 for length in normalized_lengths if length == 0)
    near_empty_count = _count_near_empty_sections(read_map, profile)
    max_length = max(normalized_lengths) if normalized_lengths else 0
    all_text = "\n".join(contents)
    mojibake_count = len(MOJIBAKE_RE.findall(all_text))

    # 构建父节 ref 集合：在 parent_ref 链中被引用过的 ref 即为父节
    parent_refs: Optional[set[str]] = None
    if sections:
        parent_refs = {
            str(s.get("parent_ref", "") or "").strip()
            for s in sections
            if str(s.get("parent_ref", "") or "").strip()
        }

    # 截断和边界溢出检测
    truncated_refs = _detect_truncated_sections(read_map, profile=profile, parent_refs=parent_refs)
    leaked_refs = _detect_boundary_leakage(read_map)

    points = 0.0

    # E1: 空/近空 section（3 分）
    e1_penalty = 1.0 * empty_count + 0.5 * near_empty_count
    points += max(0.0, 3.0 - e1_penalty)

    # E2: mojibake（3 分）
    points += 3.0 if mojibake_count == 0 else 0.0

    # E3: 最大 section 尺寸（3 分）
    if max_length <= cfg.huge_section_warn:
        points += 3.0
    elif max_length <= cfg.huge_section_fail:
        points += 1.0

    # E4: 章节截断（3 分）
    truncation_count = len(truncated_refs)
    if truncation_count == 0:
        points += 3.0
    elif truncation_count <= 2:
        points += 1.0

    # E5: 边界溢出（3 分）
    leakage_count = len(leaked_refs)
    if leakage_count == 0:
        points += 3.0
    elif leakage_count <= 2:
        points += 1.0

    return DimensionScore(
        points=points,
        max_points=15.0,
        details={
            "empty_sections": empty_count,
            "near_empty_sections": near_empty_count,
            "mojibake_hits": mojibake_count,
            "max_section_len": max_length,
            "truncated_sections": truncated_refs,
            "truncation_count": truncation_count,
            "leaked_sections": leaked_refs,
            "leakage_count": leakage_count,
        },
    )


# ---------------------------------------------------------------------------
# 维度 S：语义可寻址性（10 分）
# ---------------------------------------------------------------------------

def _score_semantic_coverage(
    sections: list[dict[str, Any]],
    profile: FormProfile,
) -> DimensionScore:
    """计算维度 S：语义可寻址性（10 分）。

    衡量 Level-1 section 的 topic 字段填充率，反映 agent 能否通过语义标签
    （如 risk_factors、mda）定位章节，而无需逐字匹配标题。

    仅适用于 10-K / 10-Q / 20-F（具有标准化 Item → topic 映射）。
    对于 6-K / 8-K / SC 13G / DEF 14A，语义路由通过关键词匹配或
    直接标题导航完成，本维度自动满分（10/10）。

    「特殊 section」不计入评分（以下两类）：
    - Cover Page：封面页，不对应任何 Item，无 topic 属于正常。
    - SIGNATURE：topic="signature"，固定，不反映语义覆盖质量。

    评分规则：
    - topic 填充率 >= 90% → 10 分
    - topic 填充率 >= 70% → 6 分
    - topic 填充率 >= 50% → 3 分
    - topic 填充率 < 50% → 0 分

    Args:
        sections: get_document_sections 返回的 section 列表。
        profile: 表单类型评分配置。

    Returns:
        DimensionScore，max_points=10.0。
    """
    # 不适用的表单类型：6-K / 8-K / SC 13G / DEF 14A 默认满分
    if not profile.score_semantic_coverage:
        return DimensionScore(
            points=10.0,
            max_points=10.0,
            details={"skip_reason": "not_applicable"},
        )

    # 只看 Level-1 section
    lv1 = [s for s in sections if s.get("level") == 1]

    # 排除 Cover Page 和 SIGNATURE——这两类无 topic 属于设计如此
    scored = [
        s for s in lv1
        if s.get("topic") != "signature"
        and not _COVER_PAGE_TITLE_RE.match(str(s.get("title", "")))
    ]

    total = len(scored)
    if total == 0:
        # 文件包含的全部均为特殊 section（极短文件），默认满分
        return DimensionScore(
            points=10.0,
            max_points=10.0,
            details={"skip_reason": "no_scored_sections", "lv1_count": len(lv1)},
        )

    topic_filled = sum(1 for s in scored if s.get("topic") is not None)
    coverage_rate = topic_filled / total

    if coverage_rate >= 0.90:
        points = 10.0
    elif coverage_rate >= 0.70:
        points = 6.0
    elif coverage_rate >= 0.50:
        points = 3.0
    else:
        points = 0.0

    # 列出未填充 topic 的 section（为调试提供上下文）
    missing_topic: list[dict[str, Any]] = [
        {"ref": s.get("ref"), "title": s.get("title")}
        for s in scored
        if s.get("topic") is None
    ]

    return DimensionScore(
        points=points,
        max_points=10.0,
        details={
            "topic_coverage_rate": round(coverage_rate, 4),
            "scored_section_count": total,
            "topic_filled_count": topic_filled,
            "missing_topic_sections": missing_topic,
        },
    )


def _build_missing_dimension_score(
    *,
    max_points: float,
    missing_snapshots: list[str],
    reason: str,
) -> DimensionScore:
    """为缺失 truth 快照的维度构造 0 分结果。

    Args:
        max_points: 维度满分。
        missing_snapshots: 缺失或失效的快照文件名列表。
        reason: 0 分原因。

    Returns:
        0 分维度结果。
    """

    return DimensionScore(
        points=0.0,
        max_points=max_points,
        details={
            "missing_snapshots": missing_snapshots,
            "skip_reason": reason,
        },
    )


def _is_snapshot_meta_contract_error(exc: ValueError) -> bool:
    """判断异常是否来自 meta 完整性契约。"""

    message = str(exc)
    return message.startswith("缺少 tool_snapshot_meta.json") or message.startswith(
        "tool_snapshot_meta."
    )


# ---------------------------------------------------------------------------
# ToC 污染检测与硬门禁
# ---------------------------------------------------------------------------

def _detect_toc_contamination(
    item_content_len: dict[str, int],
    read_map: dict[str, dict[str, Any]],
    profile: FormProfile,
) -> list[str]:
    """检测关键 Item 的 ToC 污染迹象。

    规则：若 toc_check_items 中的 Item 内容长度 < 200 且内容中出现
    「标题+页码」行样式，视为疑似目录污染。
    cross_reference_exempt_items 中的 Item 不参与检测（预期可为交叉引用）。

    Args:
        item_content_len: Item 长度映射。
        read_map: read_section 映射。
        profile: 表单类型配置。

    Returns:
        命中项列表（如 ``["Item 7"]`` 或 ``["Part I - Item 1"]``）。
    """

    suspicious: list[str] = []
    for item in profile.toc_check_items:
        length = item_content_len.get(item, 0)
        if length >= 200:
            continue
        for payload in read_map.values():
            title = str(payload.get("title", ""))
            extracted = _extract_item(title, profile=profile)
            if extracted != item:
                continue
            content = str(payload.get("content", ""))
            # 交叉引用豁免项且内容确认为交叉引用 → 合法短内容，跳过 ToC 检测
            if (
                item in profile.cross_reference_exempt_items
                and _is_sec_cross_reference(content)
            ):
                break
            if TOC_PAGE_LINE_RE.search(content) is not None:
                suspicious.append(item)
                break
    return suspicious


def _evaluate_hard_gate(
    item_content_len: dict[str, int],
    consistency: DimensionScore,
    noise: DimensionScore,
    cfg: ScoreConfig,
    read_map: dict[str, dict[str, Any]],
    profile: FormProfile,
) -> HardGateResult:
    """执行硬门禁判定。

    Args:
        item_content_len: Item 长度映射。
        consistency: 维度 D 评分结果。
        noise: 维度 E 评分结果。
        cfg: CI 阈值配置。
        read_map: read_section 映射。
        profile: 表单类型配置。

    Returns:
        硬门禁判定结果。
    """

    reasons: list[str] = []

    # 关键 Item 缺失
    missing_hard = [item for item in profile.hard_gate_items if item not in item_content_len]
    if missing_hard:
        reasons.append(f"缺失关键 Item（{', '.join(missing_hard)}）")

    # ToC 污染
    toc_items = _detect_toc_contamination(item_content_len, read_map, profile)
    if toc_items:
        reasons.append(f"疑似 ToC 污染: {', '.join(sorted(toc_items))}")

    # 超大 section
    max_section_len = int(noise.details.get("max_section_len", 0))
    if max_section_len > cfg.huge_section_fail:
        reasons.append(f"存在超大 section（>{cfg.huge_section_fail}）")

    # 悬挂 table refs
    dangling_table_refs = list(consistency.details.get("dangling_table_refs", []))
    dangling_table_sections = list(consistency.details.get("dangling_table_sections", []))
    if dangling_table_refs or dangling_table_sections:
        reasons.append("存在悬挂 table refs")

    # ref 不一致
    if not bool(consistency.details.get("ref_consistent", True)):
        reasons.append("跨工具 section refs 不一致")

    # D3 XBRL 财务数据提取完全为空
    # 适用于 XBRL 强制表单（10-K / 10-Q / 20-F）且 mean_row_count==0
    # 表明 processor 已运行提取但所有报表均无实际行数据，是系统性提取失败信号
    if profile.has_xbrl_financials:
        d3_mean_rows = consistency.details.get("mean_row_count")
        if d3_mean_rows is not None and float(d3_mean_rows) == 0.0:
            reasons.append("D3 XBRL 报表数据全部为空（mean_row_count=0），processor 提取失败")

    # D3 6-K 财务报表提取失败
    # 适用于 pipeline 已过滤为季报发布的 6-K：
    # - core_available=[] 表示完全没有提取到 income/balance_sheet
    # - mean_row_count=0 表示提取到了报表名称但内容为空
    # 两种情况都表明 HTML 表格提取失败，应作为 processor 修复信号
    elif consistency.details.get("d3_mode") == "six_k_release_core":
        d3_mean_rows = consistency.details.get("mean_row_count")
        if d3_mean_rows is not None and float(d3_mean_rows) == 0.0:
            core_avail = consistency.details.get("core_available", [])
            if not core_avail:
                reasons.append("D3 6-K 财务报表完全未提取（core_available=[]），processor HTML 提取失败")
            else:
                reasons.append("D3 6-K 财务报表提取内容为空（mean_row_count=0），processor HTML 提取失败")

    return HardGateResult(passed=len(reasons) == 0, reasons=reasons)


# ---------------------------------------------------------------------------
# 文档 & 批量评分
# ---------------------------------------------------------------------------

def score_document(
    snapshot: ProcessedSnapshotDocument,
    blob_repository: DocumentBlobRepositoryProtocol,
    cfg: ScoreConfig,
    profile: FormProfile,
) -> DocumentScore:
    """对单个文档执行评分。

    Args:
        snapshot: processed 快照访问对象。
        blob_repository: 文档文件仓储。
        cfg: CI 阈值配置。
        profile: 表单类型配置。

    Returns:
        文档评分结果。

    Raises:
        ValueError: 快照缺失或不满足 v2 契约时抛出。
    """

    snapshot_meta = _load_snapshot_meta_required(
        snapshot=snapshot,
        blob_repository=blob_repository,
    )
    sections_load = _load_truth_calls_result(
        snapshot=snapshot,
        blob_repository=blob_repository,
        tool_name="get_document_sections",
    )
    read_load = _load_truth_calls_result(
        snapshot=snapshot,
        blob_repository=blob_repository,
        tool_name="read_section",
    )
    search_load = _load_truth_calls_result(
        snapshot=snapshot,
        blob_repository=blob_repository,
        tool_name="search_document",
    )
    list_tables_load = _load_truth_calls_result(
        snapshot=snapshot,
        blob_repository=blob_repository,
        tool_name="list_tables",
    )
    get_table_load = _load_truth_calls_result(
        snapshot=snapshot,
        blob_repository=blob_repository,
        tool_name="get_table",
    )
    fs_load = _load_truth_calls_result(
        snapshot=snapshot,
        blob_repository=blob_repository,
        tool_name="get_financial_statement",
    )

    sections, read_map = _build_section_payload_maps(sections_load.calls, read_load.calls)
    item_content_len = _build_item_content_len(read_map, profile=profile, sections=sections)
    item_content_text = _build_item_content_text(read_map, profile=profile)

    if sections_load.exists:
        dim_a = _score_structure(sections, item_content_len, profile)
        dim_s = _score_semantic_coverage(sections, profile)
    else:
        dim_a = _build_missing_dimension_score(
            max_points=25.0,
            missing_snapshots=["tool_snapshot_get_document_sections.json"],
            reason="missing_snapshot",
        )
        dim_s = _build_missing_dimension_score(
            max_points=10.0,
            missing_snapshots=["tool_snapshot_get_document_sections.json"],
            reason="missing_snapshot",
        )

    if read_load.exists:
        dim_b = _score_content(item_content_len, profile, item_content_text)
        dim_e = _score_noise_integrity(read_map, cfg, profile, sections=sections)
    else:
        dim_b = _build_missing_dimension_score(
            max_points=30.0,
            missing_snapshots=["tool_snapshot_read_section.json"],
            reason="missing_snapshot",
        )
        dim_e = _build_missing_dimension_score(
            max_points=15.0,
            missing_snapshots=["tool_snapshot_read_section.json"],
            reason="missing_snapshot",
        )

    if search_load.exists:
        try:
            dim_c = _score_search_v2(
                search_load.calls,
                form_type=profile.form_type,
                snapshot_meta=snapshot_meta,
            )
        except ValueError as exc:
            dim_c = _build_missing_dimension_score(
                max_points=15.0,
                missing_snapshots=["tool_snapshot_search_document.json"],
                reason=str(exc),
            )
    else:
        dim_c = _build_missing_dimension_score(
            max_points=15.0,
            missing_snapshots=["tool_snapshot_search_document.json"],
            reason="missing_snapshot",
        )

    consistency_missing_snapshots: list[str] = []
    if not sections_load.exists:
        consistency_missing_snapshots.append("tool_snapshot_get_document_sections.json")
    if not read_load.exists:
        consistency_missing_snapshots.append("tool_snapshot_read_section.json")
    if not list_tables_load.exists:
        consistency_missing_snapshots.append("tool_snapshot_list_tables.json")
    if not get_table_load.exists:
        consistency_missing_snapshots.append("tool_snapshot_get_table.json")
    requires_financial_snapshot = profile.has_xbrl_financials or profile.form_type == "6-K"
    if requires_financial_snapshot and not fs_load.exists:
        consistency_missing_snapshots.append("tool_snapshot_get_financial_statement.json")

    if consistency_missing_snapshots:
        dim_d = _build_missing_dimension_score(
            max_points=15.0,
            missing_snapshots=consistency_missing_snapshots,
            reason="missing_snapshot",
        )
    else:
        dim_d = _score_consistency(
            sections,
            read_map,
            list_tables_load.calls,
            fs_load.calls,
            get_table_load.calls,
            profile,
        )

    dimensions = {
        "A_structure": dim_a,
        "B_content": dim_b,
        "C_search": dim_c,
        "D_consistency": dim_d,
        "E_noise": dim_e,
        "S_semantic": dim_s,
    }
    total_score = sum(item.points for item in dimensions.values())
    hard_gate = _evaluate_hard_gate(item_content_len, dim_d, dim_e, cfg, read_map, profile)

    if total_score >= cfg.min_doc_pass:
        grade = "pass"
    elif total_score >= cfg.min_doc_warn:
        grade = "warn"
    else:
        grade = "fail"

    return DocumentScore(
        ticker=snapshot.ticker,
        document_id=snapshot.document_id,
        total_score=round(total_score, 2),
        grade=grade,
        hard_gate=hard_gate,
        dimensions=dimensions,
    )


def _percentile_p10(values: list[float]) -> float:
    """计算 P10 分位值（线性插值）。

    Args:
        values: 数值列表。

    Returns:
        P10 值；空列表返回 0.0。
    """

    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = 0.1 * (len(sorted_values) - 1)
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return float(sorted_values[lower])
    ratio = pos - lower
    return float(sorted_values[lower] * (1 - ratio) + sorted_values[upper] * ratio)


def _check_batch_financial_coverage_rate(
    docs: list[DocumentScore],
    profile: FormProfile,
) -> Optional[tuple[float, float]]:
    """计算批量财报提取覆盖率，并返回对应门禁阈值。

    仅适用于 ``_FINANCIAL_COVERAGE_THRESHOLDS`` 中定义的表单类型。
    一份文档"有财务数据"的判定依赖 D3 评分时已计算好的 details 字段：

    - 10-K / 10-Q / 20-F（has_xbrl_financials=True）：``available_statements`` 非空。
    - 6-K（HTML 提取模式）：``core_available`` 非空（income / balance_sheet）。

    Args:
        docs: 当前批量的文档评分列表。
        profile: 表单类型配置。

    Returns:
        ``(coverage_rate, threshold)`` 元组；不适用于该表单类型或文档列表为空时
        返回 ``None``。
    """
    threshold = _FINANCIAL_COVERAGE_THRESHOLDS.get(profile.form_type)
    if threshold is None or not docs:
        return None

    covered = 0
    for doc in docs:
        details = doc.dimensions.get("D_consistency", DimensionScore(0.0, 0.0)).details
        if profile.form_type == "6-K":
            # 6-K 评估维度为核心报表组（income / balance_sheet），非空且有行数据才算覆盖
            # data_quality='partial' + rows=0 不算覆盖（表格识别失败）
            if details.get("core_available") and details.get("mean_row_count", 0) > 0:
                covered += 1
        else:
            # 10-K / 10-Q / 20-F：有任意一张可用报表且有实际行数据才算覆盖
            # data_quality='partial' + rows=0 不算覆盖（taxonomy 解析失败）
            if details.get("available_statements") and details.get("mean_row_count", 0) > 0:
                covered += 1

    return covered / len(docs), threshold


def score_batch(
    base: str,
    tickers: list[str],
    cfg: ScoreConfig,
    form_type: str = "10-K",
) -> BatchScore:
    """对一组 ticker 的指定 form 类型文档执行批量评分。

    Args:
        base: 组合根目录。
        tickers: ticker 列表。
        cfg: CI 阈值配置。
        form_type: 目标表单类型（默认 ``10-K``）。

    Returns:
        批量评分汇总结果。

    Raises:
        ValueError: 未知表单类型时抛出。
    """

    profile = FORM_PROFILES.get(_normalize_form_type(form_type))
    if profile is None:
        raise ValueError(f"不支持的表单类型: {form_type}（可选: {', '.join(FORM_PROFILES)}）")

    workspace_root = _resolve_workspace_root(base)
    blob_repository = FsDocumentBlobRepository(workspace_root)
    docs: list[DocumentScore] = []
    discovery = _discover_form_snapshots(base, tickers, form_type)
    completeness_failures = list(discovery.completeness_failures)
    for snapshot in discovery.snapshots:
        try:
            docs.append(score_document(snapshot, blob_repository, cfg, profile))
        except ValueError as exc:
            if not _is_snapshot_meta_contract_error(exc):
                raise
            completeness_failures.append(
                CompletenessFailure(
                    ticker=snapshot.ticker,
                    document_id=snapshot.document_id,
                    reason=str(exc),
                )
            )

    scores = [doc.total_score for doc in docs]
    avg_score = float(sum(scores) / len(scores)) if scores else 0.0
    p10_score = _percentile_p10(scores)
    hard_gate_failures = sum(1 for doc in docs if not doc.hard_gate.passed)

    failed_reasons: list[str] = []
    if completeness_failures:
        failed_reasons.append(f"completeness hard gate 失败文档数={len(completeness_failures)}")
    if hard_gate_failures > 0:
        failed_reasons.append(f"硬门禁失败文档数={hard_gate_failures}")
    if avg_score < cfg.min_batch_avg:
        failed_reasons.append(f"批量平均分 {avg_score:.2f} < {cfg.min_batch_avg:.2f}")
    if p10_score < cfg.min_batch_p10:
        failed_reasons.append(f"批量 P10 分位 {p10_score:.2f} < {cfg.min_batch_p10:.2f}")
    if any(doc.total_score < cfg.min_doc_warn for doc in docs):
        failed_reasons.append("存在单文档分数低于 fail 阈值")

    # D3 财报完整性批量门禁：覆盖率低于阈值表明 processor 存在系统性提取问题
    coverage_check = _check_batch_financial_coverage_rate(docs, profile)
    financial_coverage_rate: Optional[float] = None
    if coverage_check is not None:
        raw_coverage, coverage_threshold = coverage_check
        financial_coverage_rate = round(raw_coverage, 4)
        if raw_coverage < coverage_threshold:
            failed_reasons.append(
                f"D3 财报提取覆盖率 {raw_coverage:.1%} < {coverage_threshold:.0%}"
                f"（processor 系统性提取问题，需优化）"
            )

    passed = len(failed_reasons) == 0
    return BatchScore(
        documents=docs,
        average_score=round(avg_score, 2),
        p10_score=round(p10_score, 2),
        hard_gate_failures=hard_gate_failures,
        passed=passed,
        failed_reasons=failed_reasons,
        financial_coverage_rate=financial_coverage_rate,
        completeness_failures=completeness_failures,
    )


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------

def _serialize_document(doc: DocumentScore) -> dict[str, Any]:
    """将单文档评分对象序列化为 JSON 友好结构。"""

    return {
        "ticker": doc.ticker,
        "document_id": doc.document_id,
        "total_score": doc.total_score,
        "grade": doc.grade,
        "hard_gate": asdict(doc.hard_gate),
        "dimensions": {
            name: {
                "points": dimension.points,
                "max_points": dimension.max_points,
                "details": dimension.details,
            }
            for name, dimension in doc.dimensions.items()
        },
    }


def _serialize_completeness_failure(failure: CompletenessFailure) -> dict[str, Any]:
    """序列化完整性硬门禁失败记录。"""

    return {
        "ticker": failure.ticker,
        "document_id": failure.document_id,
        "reason": failure.reason,
    }


def write_json_report(
    path: str,
    batch: BatchScore,
    cfg: ScoreConfig,
    form_type: str,
) -> None:
    """写出 JSON 报告。

    Args:
        path: 输出路径。
        batch: 批量评分结果。
        cfg: CI 阈值配置。
        form_type: 表单类型。
    """

    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "form_type": form_type,
        "config": asdict(cfg),
        "summary": {
            "average_score": batch.average_score,
            "p10_score": batch.p10_score,
            "hard_gate_failures": batch.hard_gate_failures,
            "completeness_failure_count": len(batch.completeness_failures),
            "expected_document_count": len(batch.documents) + len(batch.completeness_failures),
            "financial_coverage_rate": batch.financial_coverage_rate,
            "passed": batch.passed,
            "failed_reasons": batch.failed_reasons,
            "document_count": len(batch.documents),
        },
        "documents": [_serialize_document(doc) for doc in batch.documents],
        "completeness_failures": [
            _serialize_completeness_failure(failure)
            for failure in batch.completeness_failures
        ],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _build_dimension_overview_rows(
    batch: BatchScore,
) -> list[list[str]]:
    """构建维度概览表行（Ticker × 维度得分矩阵）。

    Args:
        batch: 批量评分结果。

    Returns:
        表格行列表（含表头）；无文档时返回空列表。
    """

    if not batch.documents:
        return []
    dim_names = list(batch.documents[0].dimensions.keys())
    header = ["Ticker", "Document"] + dim_names + ["Total"]
    rows: list[list[str]] = [header]
    for doc in batch.documents:
        row = [doc.ticker, doc.document_id]
        for name in dim_names:
            dim = doc.dimensions.get(name)
            row.append(f"{dim.points:.1f}/{dim.max_points:.0f}" if dim else "-")
        row.append(f"{doc.total_score:.2f}")
        rows.append(row)
    return rows


def _build_caption_summary_rows(
    batch: BatchScore,
) -> list[list[str]]:
    """构建 D5 caption 填充率摘要表行。

    Args:
        batch: 批量评分结果。

    Returns:
        表格行列表（含表头）；无相关数据时返回空列表。
    """

    header = ["Ticker", "Document", "Tables", "CaptionFilled", "FillRate", "D5"]
    rows: list[list[str]] = [header]
    has_data = False
    for doc in batch.documents:
        d_dim = doc.dimensions.get("D_consistency")
        if d_dim is None:
            continue
        details = d_dim.details
        total = details.get("caption_total_tables", 0)
        filled = details.get("caption_filled", 0)
        ratio = details.get("caption_fill_ratio")
        skip = details.get("caption_skip_reason")
        if skip:
            rows.append([doc.ticker, doc.document_id, str(total), str(filled), "skip", "2.0"])
        elif ratio is not None:
            has_data = True
            rows.append([
                doc.ticker, doc.document_id,
                str(total), str(filled),
                f"{ratio:.1%}", f"{_d5_points_from_ratio(ratio):.1f}",
            ])
    return rows if has_data else []


def _d5_points_from_ratio(ratio: float) -> float:
    """根据 caption 填充率计算 D5 分数（仅用于报告展示）。

    Args:
        ratio: caption 填充率。

    Returns:
        D5 得分。
    """

    if ratio >= 0.4:
        return 2.0
    if ratio >= 0.2:
        return 1.0
    return 0.0


def _format_markdown_table(rows: list[list[str]]) -> str:
    """构造 Markdown 表格。"""

    if not rows:
        return ""
    header = "| " + " | ".join(rows[0]) + " |"
    sep = "| " + " | ".join(["---"] * len(rows[0])) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join([header, sep, *body])


def write_markdown_report(
    path: str,
    batch: BatchScore,
    cfg: ScoreConfig,
    form_type: str,
) -> None:
    """写出 Markdown 报告。

    Args:
        path: 输出路径。
        batch: 批量评分结果。
        cfg: CI 阈值配置。
        form_type: 表单类型。
    """

    os.makedirs(os.path.dirname(path), exist_ok=True)

    rows = [["Ticker", "Document", "Score", "Grade", "HardGate"]]
    for doc in batch.documents:
        rows.append(
            [
                doc.ticker,
                doc.document_id,
                f"{doc.total_score:.2f}",
                doc.grade,
                "PASS" if doc.hard_gate.passed else "FAIL",
            ]
        )

    lines = [
        f"# {form_type} CI 评分报告",
        "",
        "## 批量结果",
        "",
        f"- 期望文档数: **{len(batch.documents) + len(batch.completeness_failures)}**",
        f"- 成功评分文档数: **{len(batch.documents)}**",
        f"- Completeness hard gate 失败数: **{len(batch.completeness_failures)}**",
        f"- 平均分: **{batch.average_score:.2f}**（阈值 {cfg.min_batch_avg:.2f}）",
        f"- P10 分位: **{batch.p10_score:.2f}**（阈值 {cfg.min_batch_p10:.2f}）",
        f"- 硬门禁失败数: **{batch.hard_gate_failures}**",
        *(
            [
                f"- 财报提取覆盖率: **{batch.financial_coverage_rate:.1%}**"
                f"（阈值 {_FINANCIAL_COVERAGE_THRESHOLDS.get(_normalize_form_type(form_type), 0):.0%}）"
            ]
            if batch.financial_coverage_rate is not None else []
        ),
        f"- CI 判定: **{'PASS' if batch.passed else 'FAIL'}**",
        "",
        "## 文档明细",
        "",
        _format_markdown_table(rows),
        "",
    ]

    if batch.completeness_failures:
        lines.extend(["## Completeness Hard Gate", ""])
        for failure in batch.completeness_failures:
            lines.append(f"- {failure.ticker}/{failure.document_id}: {failure.reason}")
        lines.append("")

    failed_docs = [doc for doc in batch.documents if not doc.hard_gate.passed]
    if failed_docs:
        lines.extend(["## 硬门禁详情", ""])
        for doc in failed_docs:
            lines.append(f"- {doc.ticker}/{doc.document_id}: {', '.join(doc.hard_gate.reasons)}")
        lines.append("")

    # 维度概览表
    dim_rows = _build_dimension_overview_rows(batch)
    if dim_rows:
        lines.extend(["## 维度概览", "", _format_markdown_table(dim_rows), ""])

    # D5 caption 填充率摘要
    caption_rows = _build_caption_summary_rows(batch)
    if caption_rows:
        lines.extend(["## D5: 表格 Caption 填充率", "", _format_markdown_table(caption_rows), ""])

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_tickers(raw: str) -> list[str]:
    """解析 CLI ticker 参数。"""

    parsed = [token.strip().upper() for token in str(raw).split(",") if token.strip()]
    return parsed or list(DEFAULT_TICKERS)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行参数列表；``None`` 时使用 ``sys.argv``。

    Returns:
        解析后的命名空间。
    """

    parser = argparse.ArgumentParser(description="SEC 报告 LLM 可喂性 CI 评分")
    parser.add_argument(
        "--form",
        default="10-K",
        choices=sorted(FORM_PROFILES.keys()),
        help="目标表单类型（默认 10-K）",
    )
    parser.add_argument(
        "--base",
        default="workspace",
        help="工作区路径（默认 workspace）；内部自动补齐到 portfolio 目录",
    )
    parser.add_argument(
        "--tickers",
        default=",".join(DEFAULT_TICKERS),
        help="逗号分隔 ticker 列表",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="JSON 报告输出路径（默认按 form 类型生成）",
    )
    parser.add_argument(
        "--output-md",
        default=None,
        help="Markdown 报告输出路径（默认按 form 类型生成）",
    )
    parser.add_argument("--min-doc-pass", type=float, default=93.0)
    parser.add_argument("--min-doc-warn", type=float, default=83.0)
    parser.add_argument("--min-batch-avg", type=float, default=93.0)
    parser.add_argument("--min-batch-p10", type=float, default=86.0)
    return parser.parse_args(argv)


def _default_report_path(form_type: str, ext: str) -> str:
    """根据表单类型生成默认报告路径。

    Args:
        form_type: 表单类型（如 ``10-K``）。
        ext: 文件扩展名（如 ``json`` 或 ``md``）。

    Returns:
        报告文件路径。
    """

    # 10-K → 10k, 10-Q → 10q, SC 13G → sc13g, DEF 14A → def14a
    slug = form_type.lower().replace("-", "").replace(" ", "")
    return f"workspace/reports/score_{slug}_ci.{ext}"


def build_config(args: argparse.Namespace) -> ScoreConfig:
    """从 CLI 参数构建评分配置。

    Args:
        args: 解析后的命名空间。

    Returns:
        评分配置对象。
    """

    return ScoreConfig(
        min_doc_pass=float(args.min_doc_pass),
        min_doc_warn=float(args.min_doc_warn),
        min_batch_avg=float(args.min_batch_avg),
        min_batch_p10=float(args.min_batch_p10),
    )


def _print_console_summary(batch: BatchScore, form_type: str) -> None:
    """打印控制台摘要。

    Args:
        batch: 批量评分结果。
        form_type: 表单类型。
    """

    print("=" * 80)
    print(f"{form_type} CI 评分结果")
    print("=" * 80)
    for doc in batch.documents:
        gate = "PASS" if doc.hard_gate.passed else "FAIL"
        print(
            f"- {doc.ticker:5s} {doc.document_id}: "
            f"score={doc.total_score:6.2f}, grade={doc.grade}, gate={gate}"
        )
    print("-" * 80)
    print(
        f"average={batch.average_score:.2f}, "
        f"p10={batch.p10_score:.2f}, "
        f"hard_gate_failures={batch.hard_gate_failures}, "
        f"completeness_failures={len(batch.completeness_failures)}"
    )
    if batch.completeness_failures:
        for failure in batch.completeness_failures:
            print(f"  ! completeness {failure.ticker}/{failure.document_id}: {failure.reason}")
    # D5 caption 填充率汇总
    _print_caption_summary(batch)
    print(f"CI: {'PASS' if batch.passed else 'FAIL'}")
    if not batch.passed:
        for reason in batch.failed_reasons:
            print(f"  * {reason}")


def _print_caption_summary(batch: BatchScore) -> None:
    """打印 D5 caption 填充率汇总行。

    Args:
        batch: 批量评分结果。
    """

    total_tables = 0
    total_filled = 0
    for doc in batch.documents:
        d_dim = doc.dimensions.get("D_consistency")
        if d_dim is None:
            continue
        total_tables += d_dim.details.get("caption_total_tables", 0)
        total_filled += d_dim.details.get("caption_filled", 0)
    if total_tables > 0:
        ratio = total_filled / total_tables
        print(f"D5_caption: {total_filled}/{total_tables} ({ratio:.1%})")


def main(argv: Optional[list[str]] = None) -> int:
    """脚本入口。

    Args:
        argv: 命令行参数列表；``None`` 时使用 ``sys.argv``。

    Returns:
        CI 退出码：0 表示通过，1 表示失败。
    """

    args = parse_args(argv)
    form_type = str(args.form).upper()
    tickers = _parse_tickers(args.tickers)
    cfg = build_config(args)
    base = str(args.base).strip() if args.base is not None else "workspace"

    output_json = args.output_json or _default_report_path(form_type, "json")
    output_md = args.output_md or _default_report_path(form_type, "md")

    batch = score_batch(base=base, tickers=tickers, cfg=cfg, form_type=form_type)

    write_json_report(output_json, batch, cfg, form_type)
    write_markdown_report(output_md, batch, cfg, form_type)
    _print_console_summary(batch, form_type)

    return 0 if batch.passed else 1


if __name__ == "__main__":
    sys.exit(main())
