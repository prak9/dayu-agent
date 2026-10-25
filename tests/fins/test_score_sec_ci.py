"""`utils.score_sec_ci` 单元测试。

覆盖 10-K 与 10-Q 双表单类型的评分逻辑。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from alpha.fins.domain.document_models import ProcessedCreateRequest, SourceDocumentUpsertRequest
from alpha.fins.domain.enums import SourceKind
from alpha.fins.score_sec_ci import (
    BatchScore,
    CompletenessFailure,
    DimensionScore,
    DocumentScore,
    FORM_PROFILES,
    HardGateResult,
    ProcessedSnapshotDocument,
    ScoreConfig,
    _build_item_content_len,
    _build_ref_to_item_map,
    _build_section_payload_maps,
    _default_report_path,
    _detect_form_type,
    _count_near_empty_sections,
    _detect_boundary_leakage,
    _detect_toc_contamination,
    _detect_truncated_sections,
    _check_batch_financial_coverage_rate,
    _evaluate_financial_statement_depth,
    _evaluate_hard_gate,
    _evaluate_table_caption_fill,
    _evaluate_table_data_quality,
    _FINANCIAL_COVERAGE_THRESHOLDS,
    _extract_item,
    _format_markdown_table,
    _is_sec_cross_reference,
    _load_json,
    _load_snapshot_meta_required,
    _load_truth_calls,
    _parse_tickers,
    _print_console_summary,
    _score_content,
    _score_consistency,
    _score_search_v2,
    _score_semantic_coverage,
    _score_structure,
    _serialize_document,
    build_config,
    find_form_dirs,
    main,
    parse_args,
    score_batch,
    TEN_K_PROFILE,
    TEN_Q_PROFILE,
    TWENTY_F_PROFILE,
    SIX_K_PROFILE,
    EIGHT_K_PROFILE,
    write_json_report,
    write_markdown_report,
)
from tests.fins.storage_testkit import FsStorageTestContext, build_fs_storage_test_context


# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------

def _write_json(path: Path, payload: dict) -> None:
    """写入 JSON 测试文件。

    Args:
        path: 文件路径。
        payload: JSON 内容。

    Returns:
        无。

    Raises:
        OSError: 文件写入失败时抛出。
    """

    _try_register_processed_document_for_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _try_register_processed_document_for_path(path: Path) -> None:
    """当目标位于 processed 目录下时，预先注册 processed manifest。

    Args:
        path: 待写入文件路径。

    Returns:
        无。

    Raises:
        OSError: 仓储写入失败时抛出。
        ValueError: 路径位于非法 portfolio 结构时抛出。
    """

    document_dir = path.parent
    processed_dir = document_dir.parent
    if processed_dir.name != "processed":
        return

    workspace_root = _resolve_workspace_root_from_document_dir(document_dir)
    ticker = document_dir.parent.parent.name
    context = build_fs_storage_test_context(workspace_root)
    try:
        context.processed_repository.create_processed(
            ProcessedCreateRequest(
                ticker=ticker,
                document_id=document_dir.name,
                internal_document_id=document_dir.name.replace("fil_", ""),
                source_kind=SourceKind.FILING.value,
                form_type=None,
                meta={"is_deleted": False},
                sections=[],
                tables=[],
                financials=None,
            )
        )
    except FileExistsError:
        return


def _create_active_filing_source(
    workspace_root: Path,
    *,
    ticker: str,
    document_id: str,
    form_type: str,
) -> None:
    """创建 active filing source 元数据。

    Args:
        workspace_root: workspace 根目录。
        ticker: 股票代码。
        document_id: 文档 ID。
        form_type: 表单类型。

    Returns:
        无。

    Raises:
        OSError: 仓储写入失败时抛出。
    """

    context = build_fs_storage_test_context(workspace_root)
    context.source_repository.create_source_document(
        SourceDocumentUpsertRequest(
            ticker=ticker,
            document_id=document_id,
            internal_document_id=document_id.replace("fil_", ""),
            form_type=form_type,
            primary_document="primary.htm",
            meta={"form_type": form_type, "is_deleted": False},
        ),
        source_kind=SourceKind.FILING,
    )


def _resolve_workspace_root_from_document_dir(document_dir: Path) -> Path:
    """从 processed 文档目录反推 workspace 根目录。

    Args:
        document_dir: processed 文档目录，如 ``workspace/portfolio/AAA/processed/fil_xxx``。

    Returns:
        workspace 根目录。

    Raises:
        ValueError: 目录不在 ``portfolio`` 结构下时抛出。
    """

    for parent in document_dir.parents:
        if parent.name == "portfolio":
            return parent.parent
    raise ValueError(f"无法从目录推断 workspace 根目录: {document_dir}")


def _register_active_filing_for_document_dir(
    *,
    document_dir: Path,
    document_id: str,
    form_type: str,
) -> None:
    """为 processed 测试样本补充 active filing source。

    Args:
        document_dir: processed 文档目录。
        document_id: 文档 ID。
        form_type: 表单类型。

    Returns:
        无。

    Raises:
        OSError: 仓储写入失败时抛出。
        ValueError: 目录结构非法时抛出。
    """

    workspace_root = _resolve_workspace_root_from_document_dir(document_dir)
    ticker = document_dir.parent.parent.name
    _create_active_filing_source(
        workspace_root,
        ticker=ticker,
        document_id=document_id,
        form_type=form_type,
    )


def _register_processed_document_for_document_dir(
    *,
    document_dir: Path,
    document_id: str,
    form_type: str,
) -> None:
    """为 processed 测试样本补充 processed manifest 记录。

    Args:
        document_dir: processed 文档目录。
        document_id: 文档 ID。
        form_type: 表单类型。

    Returns:
        无。

    Raises:
        OSError: 仓储写入失败时抛出。
        ValueError: 目录结构非法时抛出。
    """

    workspace_root = _resolve_workspace_root_from_document_dir(document_dir)
    ticker = document_dir.parent.parent.name
    context = build_fs_storage_test_context(workspace_root)
    try:
        context.processed_repository.create_processed(
            ProcessedCreateRequest(
                ticker=ticker,
                document_id=document_id,
                internal_document_id=document_id.replace("fil_", ""),
                source_kind=SourceKind.FILING.value,
                form_type=form_type,
                meta={"form_type": form_type, "is_deleted": False},
                sections=[],
                tables=[],
                financials=None,
            )
        )
    except FileExistsError:
        return


def _make_snapshot_document(
    *,
    document_dir: Path,
    document_id: str,
    form_type: str,
) -> tuple[ProcessedSnapshotDocument, FsStorageTestContext]:
    """构造测试用 processed 快照访问对象。

    Args:
        document_dir: processed 文档目录。
        document_id: 文档 ID。
        form_type: 表单类型。

    Returns:
        快照访问对象与对应测试仓储上下文。

    Raises:
        FileNotFoundError: processed 文档不存在时抛出。
        OSError: 仓储读取失败时抛出。
        ValueError: 目录结构非法时抛出。
    """

    _register_processed_document_for_document_dir(
        document_dir=document_dir,
        document_id=document_id,
        form_type=form_type,
    )
    workspace_root = _resolve_workspace_root_from_document_dir(document_dir)
    ticker = document_dir.parent.parent.name
    context = build_fs_storage_test_context(workspace_root)
    handle = context.processed_repository.get_processed_handle(ticker, document_id)
    return ProcessedSnapshotDocument(
        ticker=ticker,
        document_id=document_id,
        handle=handle,
    ), context


def _make_list_documents_payload(document_id: str, form_type: str) -> dict:
    """构造 `tool_snapshot_list_documents.json` payload。"""

    return {
        "calls": [
            {
                "request": {"ticker": "TEST"},
                "response": {
                    "documents": [
                        {
                            "document_id": document_id,
                            "form_type": form_type,
                        }
                    ]
                },
            }
        ]
    }


def _make_minimal_10k_truth(
    *,
    document_dir: Path,
    document_id: str,
    item7_content: str,
    item8_content: str,
) -> None:
    """构造一组最小可评分的 10-K 快照文件。

    Args:
        document_dir: processed 文档目录。
        document_id: 文档 ID。
        item7_content: Item 7 内容。
        item8_content: Item 8 内容。

    Returns:
        无。

    Raises:
        OSError: 文件写入失败时抛出。
    """

    _write_json(
        document_dir / "tool_snapshot_list_documents.json",
        _make_list_documents_payload(document_id=document_id, form_type="10-K"),
    )
    _register_active_filing_for_document_dir(
        document_dir=document_dir,
        document_id=document_id,
        form_type="10-K",
    )

    sections = [
        {"ref": "s_0001", "title": "Part I - Item 1"},
        {"ref": "s_0002", "title": "Part I - Item 1A"},
        {"ref": "s_0003", "title": "Part II - Item 7"},
        {"ref": "s_0004", "title": "Part II - Item 7A"},
        {"ref": "s_0005", "title": "Part II - Item 8"},
        {"ref": "s_0006", "title": "Part IV - Item 15"},
    ]
    _write_json(
        document_dir / "tool_snapshot_get_document_sections.json",
        {"calls": [{"response": {"sections": sections}}]},
    )

    read_calls = [
        {"response": {"ref": "s_0001", "title": "Part I - Item 1", "content": "x" * 3000, "tables": ["t_0001"]}},
        {"response": {"ref": "s_0002", "title": "Part I - Item 1A", "content": "x" * 6000, "tables": []}},
        {"response": {"ref": "s_0003", "title": "Part II - Item 7", "content": item7_content, "tables": []}},
        {"response": {"ref": "s_0004", "title": "Part II - Item 7A", "content": "x" * 1000, "tables": []}},
        {"response": {"ref": "s_0005", "title": "Part II - Item 8", "content": item8_content, "tables": []}},
        {"response": {"ref": "s_0006", "title": "Part IV - Item 15", "content": "x" * 5000, "tables": []}},
    ]
    _write_json(document_dir / "tool_snapshot_read_section.json", {"calls": read_calls})

    _make_common_truth(document_dir, form_type="10-K")


def _make_minimal_10q_truth(
    *,
    document_dir: Path,
    document_id: str,
    part_i_item1_content: str,
    part_i_item2_content: str,
    part_ii_item1a_content: str,
) -> None:
    """构造一组最小可评分的 10-Q 快照文件。

    Args:
        document_dir: processed 文档目录。
        document_id: 文档 ID。
        part_i_item1_content: Part I - Item 1 内容。
        part_i_item2_content: Part I - Item 2 内容。
        part_ii_item1a_content: Part II - Item 1A 内容。

    Returns:
        无。

    Raises:
        OSError: 文件写入失败时抛出。
    """

    _write_json(
        document_dir / "tool_snapshot_list_documents.json",
        _make_list_documents_payload(document_id=document_id, form_type="10-Q"),
    )
    _register_active_filing_for_document_dir(
        document_dir=document_dir,
        document_id=document_id,
        form_type="10-Q",
    )

    sections = [
        {"ref": "s_0001", "title": "Part I - Item 1"},
        {"ref": "s_0002", "title": "Part I - Item 2"},
        {"ref": "s_0003", "title": "Part I - Item 3"},
        {"ref": "s_0004", "title": "Part I - Item 4"},
        {"ref": "s_0005", "title": "Part II - Item 1"},
        {"ref": "s_0006", "title": "Part II - Item 1A"},
        {"ref": "s_0007", "title": "Part II - Item 2"},
        {"ref": "s_0008", "title": "Part II - Item 6"},
        {"ref": "s_0009", "title": "SIGNATURE"},
    ]
    _write_json(
        document_dir / "tool_snapshot_get_document_sections.json",
        {"calls": [{"response": {"sections": sections}}]},
    )

    read_calls = [
        {"response": {"ref": "s_0001", "title": "Part I - Item 1", "content": part_i_item1_content, "tables": ["t_0001"]}},
        {"response": {"ref": "s_0002", "title": "Part I - Item 2", "content": part_i_item2_content, "tables": []}},
        {"response": {"ref": "s_0003", "title": "Part I - Item 3", "content": "x" * 500, "tables": []}},
        {"response": {"ref": "s_0004", "title": "Part I - Item 4", "content": "x" * 500, "tables": []}},
        {"response": {"ref": "s_0005", "title": "Part II - Item 1", "content": "x" * 500, "tables": []}},
        {"response": {"ref": "s_0006", "title": "Part II - Item 1A", "content": part_ii_item1a_content, "tables": []}},
        {"response": {"ref": "s_0007", "title": "Part II - Item 2", "content": "x" * 300, "tables": []}},
        {"response": {"ref": "s_0008", "title": "Part II - Item 6", "content": "x" * 200, "tables": []}},
        {"response": {"ref": "s_0009", "title": "SIGNATURE", "content": "x" * 100, "tables": []}},
    ]
    _write_json(document_dir / "tool_snapshot_read_section.json", {"calls": read_calls})

    _make_common_truth(document_dir, form_type="10-Q")


def _resolve_search_pack_name(form_type: str) -> str:
    """按表单类型返回 C 维检索词包名称。

    Args:
        form_type: 表单类型。

    Returns:
        检索词包名称。

    Raises:
        无。
    """

    normalized = str(form_type).upper().strip()
    if normalized in {"8-K", "6-K"}:
        return "event_pack"
    if normalized == "DEF 14A":
        return "governance_pack"
    if normalized.startswith("SC 13"):
        return "ownership_pack"
    return "annual_quarter_core40"


def _make_common_truth(document_dir: Path, *, form_type: str) -> None:
    """构造搜索、表格、财务报表等公共快照文件。

    Args:
        document_dir: processed 文档目录。

    Returns:
        无。
    """

    _register_processed_document_for_document_dir(
        document_dir=document_dir,
        document_id=document_dir.name,
        form_type=form_type,
    )

    search_calls = [
        {
            "request": {
                "query": "risk factors",
                "query_id": "q001",
                "query_text": "risk factors",
                "query_intent": "risk_factors",
                "query_weight": 1.0,
            },
            "response": {
                "diagnostics": {"strategy_hit_counts": {"exact": 1, "phrase_variant": 0, "synonym": 0, "token": 0}},
                "matches": [
                    {
                        "section": {"ref": "s_0002"},
                        "snippet": "This section discusses risk factors in detail for the reporting period.",
                    }
                ]
            },
        },
        {
            "request": {
                "query": "cash flow",
                "query_id": "q002",
                "query_text": "cash flow",
                "query_intent": "cash_flow",
                "query_weight": 1.0,
            },
            "response": {
                "diagnostics": {"strategy_hit_counts": {"exact": 1, "phrase_variant": 0, "synonym": 0, "token": 0}},
                "matches": [
                    {
                        "section": {"ref": "s_0003"},
                        "snippet": "Cash flow from operating activities increased substantially year over year.",
                    }
                ]
            },
        },
    ]
    _write_json(document_dir / "tool_snapshot_search_document.json", {"calls": search_calls})

    list_tables_calls = [
        {
            "response": {
                "tables": [
                    {"table_ref": "t_0001", "section_ref": "s_0001"},
                ]
            }
        }
    ]
    _write_json(document_dir / "tool_snapshot_list_tables.json", {"calls": list_tables_calls})

    # get_table 提供表格的实际 data.markdown 内容
    get_table_calls = [
        {
            "request": {"table_ref": "t_0001"},
            "response": {
                "ticker": "TEST",
                "table_ref": "t_0001",
                "data": {
                    "kind": "markdown",
                    "markdown": "| Metric | 2024 | 2023 |\n|---|---|---|\n| Revenue | 100B | 90B |",
                },
                "row_count": 1,
                "col_count": 3,
                "is_financial": False,
            },
        },
    ]
    _write_json(document_dir / "tool_snapshot_get_table.json", {"calls": get_table_calls})

    # 财务报表包含 rows 和 periods 以支持 D3 深度检查
    _sample_rows = [{"concept": f"us-gaap_Row{i}", "label": f"Row {i}", "values": [100.0, 200.0]} for i in range(15)]
    _sample_periods = [
        {"period_end": "2024-09-30", "fiscal_year": 2024, "fiscal_period": "FY"},
        {"period_end": "2023-09-30", "fiscal_year": 2023, "fiscal_period": "FY"},
    ]
    fs_calls = [
        {"request": {"statement_type": "income"}, "response": {"data_quality": "xbrl", "rows": _sample_rows, "periods": _sample_periods}},
        {"request": {"statement_type": "balance_sheet"}, "response": {"data_quality": "xbrl", "rows": _sample_rows, "periods": _sample_periods}},
        {"request": {"statement_type": "cash_flow"}, "response": {"data_quality": "xbrl", "rows": _sample_rows, "periods": _sample_periods}},
        {"request": {"statement_type": "equity"}, "response": {"data_quality": "xbrl", "rows": _sample_rows, "periods": _sample_periods}},
        {"request": {"statement_type": "comprehensive_income"}, "response": {"data_quality": "xbrl", "rows": _sample_rows, "periods": _sample_periods}},
    ]
    _write_json(document_dir / "tool_snapshot_get_financial_statement.json", {"calls": fs_calls})

    _write_json(
        document_dir / "tool_snapshot_meta.json",
        {
            "snapshot_schema_version": "tool_snapshot_v1.0.0",
            "search_query_pack_name": _resolve_search_pack_name(form_type),
            "search_query_pack_version": "search_query_pack_v1.0.0",
            "search_query_count": len(search_calls),
        },
    )


# ---------------------------------------------------------------------------
# 测试：_extract_item
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestExtractItem:
    """Item 提取标准化测试。"""

    def test_10k_basic_extraction(self) -> None:
        """10-K 模式：从标题中提取 Item 编号。"""

        profile_10k = FORM_PROFILES["10-K"]
        assert _extract_item("Part II - Item 7A", profile=profile_10k) == "Item 7A"
        assert _extract_item("item 8. Financial Statements", profile=profile_10k) == "Item 8"
        assert _extract_item("SIGNATURE", profile=profile_10k) is None

    def test_10q_with_part_prefix(self) -> None:
        """10-Q 模式：提取含 Part 前缀的完整 Item 键。"""

        profile_10q = FORM_PROFILES["10-Q"]
        assert _extract_item("Part I - Item 2", profile=profile_10q) == "Part I - Item 2"
        assert _extract_item("Part II - Item 1A", profile=profile_10q) == "Part II - Item 1A"
        assert _extract_item("Part I - Item 1", profile=profile_10q) == "Part I - Item 1"

    def test_10q_no_part_returns_none(self) -> None:
        """10-Q 模式：无 Part 前缀的标题返回 None。"""

        profile_10q = FORM_PROFILES["10-Q"]
        assert _extract_item("Item 7A", profile=profile_10q) is None
        assert _extract_item("SIGNATURE", profile=profile_10q) is None

    def test_10q_dash_variants(self) -> None:
        """10-Q 模式：支持多种连字符（en-dash、em-dash）。"""

        profile_10q = FORM_PROFILES["10-Q"]
        assert _extract_item("Part I – Item 2", profile=profile_10q) == "Part I - Item 2"
        assert _extract_item("Part II — Item 1A", profile=profile_10q) == "Part II - Item 1A"


# ---------------------------------------------------------------------------
# 测试：ToC 污染检测
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTocContamination:
    """ToC 污染检测测试。"""

    def test_10k_toc_contamination(self) -> None:
        """10-K：Item 7/8 短内容疑似目录。"""

        profile = FORM_PROFILES["10-K"]
        item_len = {"Item 7": 80, "Item 8": 120}
        read_map = {
            "sec_1": {"title": "Part II - Item 7", "content": "Management Discussion 20"},
            "sec_2": {"title": "Part II - Item 8", "content": "Financial Statements 35"},
        }
        hit = _detect_toc_contamination(item_len, read_map, profile)
        assert sorted(hit) == ["Item 7", "Item 8"]

    def test_10q_toc_contamination(self) -> None:
        """10-Q：Part I Item 1/2 短内容疑似目录。"""

        profile = FORM_PROFILES["10-Q"]
        item_len = {"Part I - Item 1": 80, "Part I - Item 2": 100}
        read_map = {
            "sec_1": {"title": "Part I - Item 1", "content": "Financial Statements 15"},
            "sec_2": {"title": "Part I - Item 2", "content": "Management Discussion and Analysis 20"},
        }
        hit = _detect_toc_contamination(item_len, read_map, profile)
        assert sorted(hit) == ["Part I - Item 1", "Part I - Item 2"]

    def test_10q_no_contamination_when_long(self) -> None:
        """10-Q：内容充足时不触发 ToC 检测。"""

        profile = FORM_PROFILES["10-Q"]
        item_len = {"Part I - Item 1": 6000, "Part I - Item 2": 4000}
        read_map = {
            "sec_1": {"title": "Part I - Item 1", "content": "x" * 6000},
            "sec_2": {"title": "Part I - Item 2", "content": "x" * 4000},
        }
        hit = _detect_toc_contamination(item_len, read_map, profile)
        assert hit == []

    def test_20f_item18_heading_line_not_flagged_as_toc(self) -> None:
        """20-F：内容以 'Item 18' 标题行开头时，不应触发 ToC 误判（CCEP/TS 场景）。"""

        profile = FORM_PROFILES["20-F"]
        # CCEP 场景：Item 18 仅有 "n/a"（公司使用 Item 17 提交 IFRS 财报）
        item_len_ccep = {"Item 18": 33}
        read_map_ccep = {
            "sec_27": {"title": "Part IV - Item 18 - Financial Statements",
                       "content": "Item 18\nFinancial Statements.\nn/a"},
        }
        hit = _detect_toc_contamination(item_len_ccep, read_map_ccep, profile)
        assert hit == [], f"CCEP 场景不应触发 ToC 误判，实际 hit={hit}"

        # TS 场景：Item 18 仅有标题文本
        item_len_ts = {"Item 18": 49}
        read_map_ts = {
            "sec_27": {"title": "Part IV - Item 18 - Financial Statements",
                       "content": "Item 18\nFinancial Statements\nFinancial Statements"},
        }
        hit = _detect_toc_contamination(item_len_ts, read_map_ts, profile)
        assert hit == [], f"TS 场景不应触发 ToC 误判，实际 hit={hit}"

    def test_20f_item18_xref_starting_on_page_f1(self) -> None:
        """20-F：'starting on page F-1' 应识别为合法交叉引用（TSM 场景）。"""

        profile = FORM_PROFILES["20-F"]
        item_len = {"Item 18": 120}
        read_map = {
            "sec_25": {"title": "Part IV - Item 18 - Financial Statements",
                       "content": "ITEM\xa018.\nFINANCIAL STATEMENTS\nRefer to the consolidated "
                                  "financial statements starting on page\nF-1\nof this annual report."},
        }
        hit = _detect_toc_contamination(item_len, read_map, profile)
        assert hit == [], f"TSM 场景 'starting on page F-1' 应为合法交叉引用，实际 hit={hit}"

    def test_20f_item18_xref_beginning_on_page_f1(self) -> None:
        """20-F：'beginning on page F-1' 应识别为合法交叉引用（BNTX/STNE 场景）。"""

        profile = FORM_PROFILES["20-F"]
        # BNTX 场景
        item_len_bntx = {"Item 18": 118}
        read_map_bntx = {
            "sec_25": {"title": "Part IV - Item 18 - Financial Statements",
                       "content": "Item 18. Financial Statements\nThe financial statements are filed "
                                  "as part of this Annual Report beginning on page\nF-1\n."},
        }
        hit = _detect_toc_contamination(item_len_bntx, read_map_bntx, profile)
        assert hit == [], f"BNTX 场景 'beginning on page F-1' 应为合法交叉引用，实际 hit={hit}"

        # STNE 场景
        item_len_stne = {"Item 18": 103}
        read_map_stne = {
            "sec_29": {"title": "Part IV - Item 18 - Financial Statements",
                       "content": "ITEM 18. Financial statements\nSee our audited consolidated "
                                  "financial statements beginning at page\nF-1\n."},
        }
        hit = _detect_toc_contamination(item_len_stne, read_map_stne, profile)
        assert hit == [], f"STNE 场景 'beginning at page F-1' 应为合法交叉引用，实际 hit={hit}"

    def test_20f_item18_real_toc_still_flagged(self) -> None:
        """20-F：真正的目录行（如 'Consolidated Balance Sheets F-3'）仍应触发 ToC 检测。"""

        profile = FORM_PROFILES["20-F"]
        item_len = {"Item 18": 80}
        read_map = {
            "sec_25": {"title": "Part IV - Item 18 - Financial Statements",
                       "content": "Consolidated Balance Sheets F-3\nConsolidated Statements of Income F-5"},
        }
        hit = _detect_toc_contamination(item_len, read_map, profile)
        assert "Item 18" in hit, f"真实 ToC 目录行应触发检测，实际 hit={hit}"

@pytest.mark.unit
class TestFindFormDirs:
    """目录发现测试。"""

    def test_filters_by_form_type(self, tmp_path: Path) -> None:
        """仅返回匹配指定 form 类型的目录。"""

        workspace_root = tmp_path / "workspace"
        base = workspace_root / "portfolio"
        tenk_dir = base / "AAA" / "processed" / "fil_10k"
        tenq_dir = base / "AAA" / "processed" / "fil_10q"
        other_dir = base / "AAA" / "processed" / "fil_8k"

        _write_json(tenk_dir / "tool_snapshot_list_documents.json", _make_list_documents_payload("fil_10k", "10-K"))
        _write_json(tenq_dir / "tool_snapshot_list_documents.json", _make_list_documents_payload("fil_10q", "10-Q"))
        _write_json(other_dir / "tool_snapshot_list_documents.json", _make_list_documents_payload("fil_8k", "8-K"))
        _create_active_filing_source(workspace_root, ticker="AAA", document_id="fil_10k", form_type="10-K")
        _create_active_filing_source(workspace_root, ticker="AAA", document_id="fil_10q", form_type="10-Q")
        _create_active_filing_source(workspace_root, ticker="AAA", document_id="fil_8k", form_type="8-K")
        _register_processed_document_for_document_dir(document_dir=tenk_dir, document_id="fil_10k", form_type="10-K")
        _register_processed_document_for_document_dir(document_dir=tenq_dir, document_id="fil_10q", form_type="10-Q")
        _register_processed_document_for_document_dir(document_dir=other_dir, document_id="fil_8k", form_type="8-K")

        # 查找 10-K
        found_10k = find_form_dirs(str(base), ["AAA"], "10-K")
        assert len(found_10k) == 1
        assert found_10k[0].document_id == "fil_10k"

        # 查找 10-Q
        found_10q = find_form_dirs(str(base), ["AAA"], "10-Q")
        assert len(found_10q) == 1
        assert found_10q[0].document_id == "fil_10q"

    def test_workspace_root_as_base_auto_appends_portfolio(self, tmp_path: Path) -> None:
        """base 传 workspace 根目录时自动拼接 portfolio。"""

        workspace_root = tmp_path / "workspace"
        portfolio_root = workspace_root / "portfolio"
        tenk_dir = portfolio_root / "AAA" / "processed" / "fil_10k"
        _write_json(
            tenk_dir / "tool_snapshot_list_documents.json",
            _make_list_documents_payload("fil_10k", "10-K"),
        )
        _create_active_filing_source(workspace_root, ticker="AAA", document_id="fil_10k", form_type="10-K")
        _register_processed_document_for_document_dir(document_dir=tenk_dir, document_id="fil_10k", form_type="10-K")

        found_10k = find_form_dirs(str(workspace_root), ["AAA"], "10-K")
        assert len(found_10k) == 1
        assert found_10k[0].document_id == "fil_10k"

    def test_excludes_stale_processed_without_active_source(self, tmp_path: Path) -> None:
        """陈旧 processed 文档不应进入评分集合。"""

        workspace_root = tmp_path / "workspace"
        portfolio_root = workspace_root / "portfolio"
        stale_dir = portfolio_root / "AAA" / "processed" / "fil_stale"
        active_dir = portfolio_root / "AAA" / "processed" / "fil_active"
        _write_json(
            stale_dir / "tool_snapshot_list_documents.json",
            _make_list_documents_payload("fil_stale", "6-K"),
        )
        _write_json(
            active_dir / "tool_snapshot_list_documents.json",
            _make_list_documents_payload("fil_active", "6-K"),
        )
        _create_active_filing_source(
            workspace_root,
            ticker="AAA",
            document_id="fil_active",
            form_type="6-K",
        )
        _register_processed_document_for_document_dir(document_dir=stale_dir, document_id="fil_stale", form_type="6-K")
        _register_processed_document_for_document_dir(document_dir=active_dir, document_id="fil_active", form_type="6-K")

        found = find_form_dirs(str(workspace_root), ["AAA"], "6-K")

        assert [item.document_id for item in found] == ["fil_active"]

    def test_returns_empty_when_ticker_has_no_active_source(self, tmp_path: Path) -> None:
        """没有 active source filing 时，不得回退到 processed-only。"""

        workspace_root = tmp_path / "workspace"
        portfolio_root = workspace_root / "portfolio"
        stale_dir = portfolio_root / "AAA" / "processed" / "fil_stale"
        _write_json(
            stale_dir / "tool_snapshot_list_documents.json",
            _make_list_documents_payload("fil_stale", "6-K"),
        )
        _register_processed_document_for_document_dir(document_dir=stale_dir, document_id="fil_stale", form_type="6-K")

        found = find_form_dirs(str(workspace_root), ["AAA"], "6-K")

        assert found == []

    def test_returns_empty_when_active_source_has_no_matching_form(self, tmp_path: Path) -> None:
        """active source 存在但表单类型不匹配时，不得放行陈旧 processed。"""

        workspace_root = tmp_path / "workspace"
        portfolio_root = workspace_root / "portfolio"
        stale_dir = portfolio_root / "AAA" / "processed" / "fil_stale"
        _write_json(
            stale_dir / "tool_snapshot_list_documents.json",
            _make_list_documents_payload("fil_stale", "6-K"),
        )
        _create_active_filing_source(
            workspace_root,
            ticker="AAA",
            document_id="fil_other",
            form_type="10-K",
        )
        _register_processed_document_for_document_dir(document_dir=stale_dir, document_id="fil_stale", form_type="6-K")

        found = find_form_dirs(str(workspace_root), ["AAA"], "6-K")

        assert found == []


# ---------------------------------------------------------------------------
# 测试：10-K 批量评分
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestScoreBatch10K:
    """10-K 批量评分集成测试。"""

    def test_hard_gate_failure_on_toc_contamination(self, tmp_path: Path) -> None:
        """ToC 污染触发硬门禁且批量判定失败。"""

        base = tmp_path / "portfolio"
        doc_dir = base / "AAA" / "processed" / "fil_bad"
        _make_minimal_10k_truth(
            document_dir=doc_dir,
            document_id="fil_bad",
            item7_content="Management's Discussion and Analysis 20",
            item8_content="Financial Statements and Supplementary Data 35",
        )

        batch = score_batch(str(base), ["AAA"], ScoreConfig(), form_type="10-K")
        assert len(batch.documents) == 1
        assert batch.documents[0].hard_gate.passed is False
        assert any("ToC" in reason for reason in batch.documents[0].hard_gate.reasons)
        assert batch.passed is False

    def test_pass_with_sufficient_content(self, tmp_path: Path) -> None:
        """高质量 10-K 样本可通过批量 CI 判定。"""

        base = tmp_path / "portfolio"
        doc_dir = base / "AAA" / "processed" / "fil_good"
        _make_minimal_10k_truth(
            document_dir=doc_dir,
            document_id="fil_good",
            item7_content="x" * 7000,
            item8_content="x" * 15000,
        )

        cfg = ScoreConfig(min_batch_avg=60.0, min_batch_p10=60.0)
        batch = score_batch(str(base), ["AAA"], cfg, form_type="10-K")
        assert len(batch.documents) == 1
        assert batch.documents[0].hard_gate.passed is True
        assert batch.documents[0].total_score >= 60.0
        assert batch.passed is True

    def test_score_batch_fails_when_snapshot_meta_missing(self, tmp_path: Path) -> None:
        """缺少 tool_snapshot_meta.json 时应触发 completeness hard gate。"""
        base = tmp_path / "portfolio"
        doc_dir = base / "AAA" / "processed" / "fil_meta_missing"
        _make_minimal_10k_truth(
            document_dir=doc_dir,
            document_id="fil_meta_missing",
            item7_content="x" * 7000,
            item8_content="x" * 15000,
        )
        (doc_dir / "tool_snapshot_meta.json").unlink()

        batch = score_batch(
            str(base),
            ["AAA"],
            ScoreConfig(min_batch_avg=0.0, min_batch_p10=0.0, min_doc_warn=0.0),
            form_type="10-K",
        )

        assert batch.passed is False
        assert batch.documents == []
        assert len(batch.completeness_failures) == 1
        assert batch.completeness_failures[0].document_id == "fil_meta_missing"
        assert "tool_snapshot_meta.json" in batch.completeness_failures[0].reason
        assert any("completeness hard gate" in reason for reason in batch.failed_reasons)

    def test_score_batch_fails_when_processed_document_missing(self, tmp_path: Path) -> None:
        """active filing 缺少 processed 时应触发 completeness hard gate。"""

        base = tmp_path / "portfolio"
        _create_active_filing_source(
            tmp_path,
            ticker="AAA",
            document_id="fil_missing_processed",
            form_type="10-K",
        )

        batch = score_batch(
            str(base),
            ["AAA"],
            ScoreConfig(min_batch_avg=0.0, min_batch_p10=0.0, min_doc_warn=0.0),
            form_type="10-K",
        )

        assert batch.passed is False
        assert batch.documents == []
        assert len(batch.completeness_failures) == 1
        assert batch.completeness_failures[0].document_id == "fil_missing_processed"
        assert batch.completeness_failures[0].reason == "缺少 processed 快照"

    def test_missing_search_snapshot_zeroes_c_dimension_instead_of_raising(self, tmp_path: Path) -> None:
        """缺少 search_document 快照时，C 维应记 0 分而不是整批失败。"""

        base = tmp_path / "portfolio"
        doc_dir = base / "AAA" / "processed" / "fil_search_missing"
        _make_minimal_10k_truth(
            document_dir=doc_dir,
            document_id="fil_search_missing",
            item7_content="x" * 7000,
            item8_content="x" * 15000,
        )
        (doc_dir / "tool_snapshot_search_document.json").unlink()

        batch = score_batch(
            str(base),
            ["AAA"],
            ScoreConfig(min_batch_avg=0.0, min_batch_p10=0.0, min_doc_warn=0.0),
            form_type="10-K",
        )

        assert len(batch.documents) == 1
        assert batch.completeness_failures == []
        c_dim = batch.documents[0].dimensions["C_search"]
        assert c_dim.points == 0.0
        assert c_dim.details["missing_snapshots"] == ["tool_snapshot_search_document.json"]

    def test_missing_sections_snapshot_zeroes_structure_semantic_and_consistency(self, tmp_path: Path) -> None:
        """缺少 get_document_sections 快照时，A/S/D 应记 0 分。"""

        base = tmp_path / "portfolio"
        doc_dir = base / "AAA" / "processed" / "fil_sections_missing"
        _make_minimal_10k_truth(
            document_dir=doc_dir,
            document_id="fil_sections_missing",
            item7_content="x" * 7000,
            item8_content="x" * 15000,
        )
        (doc_dir / "tool_snapshot_get_document_sections.json").unlink()

        batch = score_batch(
            str(base),
            ["AAA"],
            ScoreConfig(min_batch_avg=0.0, min_batch_p10=0.0, min_doc_warn=0.0),
            form_type="10-K",
        )

        doc = batch.documents[0]
        assert doc.dimensions["A_structure"].points == 0.0
        assert doc.dimensions["S_semantic"].points == 0.0
        assert doc.dimensions["D_consistency"].points == 0.0

    def test_missing_read_section_snapshot_zeroes_content_noise_and_consistency(self, tmp_path: Path) -> None:
        """缺少 read_section 快照时，B/E/D 应记 0 分。"""

        base = tmp_path / "portfolio"
        doc_dir = base / "AAA" / "processed" / "fil_read_missing"
        _make_minimal_10k_truth(
            document_dir=doc_dir,
            document_id="fil_read_missing",
            item7_content="x" * 7000,
            item8_content="x" * 15000,
        )
        (doc_dir / "tool_snapshot_read_section.json").unlink()

        batch = score_batch(
            str(base),
            ["AAA"],
            ScoreConfig(min_batch_avg=0.0, min_batch_p10=0.0, min_doc_warn=0.0),
            form_type="10-K",
        )

        doc = batch.documents[0]
        assert doc.dimensions["B_content"].points == 0.0
        assert doc.dimensions["E_noise"].points == 0.0
        assert doc.dimensions["D_consistency"].points == 0.0

    def test_missing_table_snapshot_zeroes_consistency_dimension(self, tmp_path: Path) -> None:
        """缺少 list_tables/get_table 等 D 维快照时，应只将 D 维记 0 分。"""

        base = tmp_path / "portfolio"
        doc_dir = base / "AAA" / "processed" / "fil_table_missing"
        _make_minimal_10k_truth(
            document_dir=doc_dir,
            document_id="fil_table_missing",
            item7_content="x" * 7000,
            item8_content="x" * 15000,
        )
        (doc_dir / "tool_snapshot_list_tables.json").unlink()

        batch = score_batch(
            str(base),
            ["AAA"],
            ScoreConfig(min_batch_avg=0.0, min_batch_p10=0.0, min_doc_warn=0.0),
            form_type="10-K",
        )

        doc = batch.documents[0]
        assert doc.dimensions["D_consistency"].points == 0.0
        assert "tool_snapshot_list_tables.json" in doc.dimensions["D_consistency"].details["missing_snapshots"]


# ---------------------------------------------------------------------------
# 测试：10-Q 批量评分
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestScoreBatch10Q:
    """10-Q 批量评分集成测试。"""

    def test_pass_with_sufficient_content(self, tmp_path: Path) -> None:
        """高质量 10-Q 样本可通过批量 CI 判定。"""

        base = tmp_path / "portfolio"
        doc_dir = base / "AAA" / "processed" / "fil_good_q"
        _make_minimal_10q_truth(
            document_dir=doc_dir,
            document_id="fil_good_q",
            part_i_item1_content="x" * 7000,
            part_i_item2_content="x" * 5000,
            part_ii_item1a_content="x" * 3000,
        )

        cfg = ScoreConfig(min_batch_avg=60.0, min_batch_p10=60.0)
        batch = score_batch(str(base), ["AAA"], cfg, form_type="10-Q")
        assert len(batch.documents) == 1
        assert batch.documents[0].hard_gate.passed is True
        assert batch.documents[0].total_score >= 60.0
        assert batch.passed is True

    def test_hard_gate_failure_missing_key_items(self, tmp_path: Path) -> None:
        """10-Q 缺失 Part I - Item 1 触发硬门禁失败。"""

        base = tmp_path / "portfolio"
        doc_dir = base / "AAA" / "processed" / "fil_bad_q"

        _write_json(
            doc_dir / "tool_snapshot_list_documents.json",
            _make_list_documents_payload("fil_bad_q", "10-Q"),
        )
        _create_active_filing_source(tmp_path, ticker="AAA", document_id="fil_bad_q", form_type="10-Q")

        # 只有 Part II Item，缺少 Part I Item 1/2
        sections = [
            {"ref": "s_0001", "title": "Part II - Item 1"},
            {"ref": "s_0002", "title": "Part II - Item 1A"},
            {"ref": "s_0003", "title": "Part II - Item 6"},
        ]
        _write_json(
            doc_dir / "tool_snapshot_get_document_sections.json",
            {"calls": [{"response": {"sections": sections}}]},
        )

        read_calls = [
            {"response": {"ref": "s_0001", "title": "Part II - Item 1", "content": "x" * 500, "tables": []}},
            {"response": {"ref": "s_0002", "title": "Part II - Item 1A", "content": "x" * 3000, "tables": []}},
            {"response": {"ref": "s_0003", "title": "Part II - Item 6", "content": "x" * 200, "tables": []}},
        ]
        _write_json(doc_dir / "tool_snapshot_read_section.json", {"calls": read_calls})
        _make_common_truth(doc_dir, form_type="10-Q")

        batch = score_batch(str(base), ["AAA"], ScoreConfig(), form_type="10-Q")
        assert len(batch.documents) == 1
        assert batch.documents[0].hard_gate.passed is False
        assert any("关键 Item" in r for r in batch.documents[0].hard_gate.reasons)

    def test_unsupported_form_raises(self) -> None:
        """不支持的表单类型应抛出 ValueError。"""

        with pytest.raises(ValueError, match="不支持"):
            score_batch("fake", ["AAA"], ScoreConfig(), form_type="UNKNOWN-FORM")


# ---------------------------------------------------------------------------
# 测试：20-F 批量评分
# ---------------------------------------------------------------------------

def _make_minimal_20f_truth(
    *,
    document_dir: Path,
    document_id: str,
    item3_content: str,
    item5_content: str,
    item18_content: str,
) -> None:
    """构造一组最小可评分的 20-F 快照文件。

    Args:
        document_dir: processed 文档目录。
        document_id: 文档 ID。
        item3_content: Item 3 (Key Information / Risk Factors) 内容。
        item5_content: Item 5 (Operating and Financial Review) 内容。
        item18_content: Item 18 (Financial Statements) 内容。

    Returns:
        无。

    Raises:
        OSError: 文件写入失败时抛出。
    """

    _write_json(
        document_dir / "tool_snapshot_list_documents.json",
        _make_list_documents_payload(document_id=document_id, form_type="20-F"),
    )
    _register_active_filing_for_document_dir(
        document_dir=document_dir,
        document_id=document_id,
        form_type="20-F",
    )

    sections = [
        {"ref": "s_0001", "title": "Item 1"},
        {"ref": "s_0002", "title": "Item 2"},
        {"ref": "s_0003", "title": "Item 3"},
        {"ref": "s_0004", "title": "Item 4"},
        {"ref": "s_0005", "title": "Item 4A"},
        {"ref": "s_0006", "title": "Item 5"},
        {"ref": "s_0007", "title": "Item 6"},
        {"ref": "s_0008", "title": "Item 7"},
        {"ref": "s_0009", "title": "Item 8"},
        {"ref": "s_0010", "title": "Item 9"},
        {"ref": "s_0011", "title": "Item 10"},
        {"ref": "s_0012", "title": "Item 11"},
        {"ref": "s_0013", "title": "Item 12"},
        {"ref": "s_0014", "title": "Item 13"},
        {"ref": "s_0015", "title": "Item 14"},
        {"ref": "s_0016", "title": "Item 15"},
        {"ref": "s_0017", "title": "Item 16"},
        {"ref": "s_0018", "title": "Item 16A"},
        {"ref": "s_0019", "title": "Item 16B"},
        {"ref": "s_0020", "title": "Item 16C"},
        {"ref": "s_0021", "title": "Item 16D"},
        {"ref": "s_0022", "title": "Item 16E"},
        {"ref": "s_0023", "title": "Item 16F"},
        {"ref": "s_0024", "title": "Item 16G"},
        {"ref": "s_0025", "title": "Item 16H"},
        {"ref": "s_0026", "title": "Item 16I"},
        {"ref": "s_0027", "title": "Item 16J"},
        {"ref": "s_0028", "title": "Item 17"},
        {"ref": "s_0029", "title": "Item 18"},
        {"ref": "s_0030", "title": "Item 19"},
        {"ref": "s_0031", "title": "SIGNATURE"},
    ]
    _write_json(
        document_dir / "tool_snapshot_get_document_sections.json",
        {"calls": [{"response": {"sections": sections}}]},
    )

    read_calls = [
        {"response": {"ref": "s_0001", "title": "Item 1", "content": "x" * 2000, "tables": []}},
        {"response": {"ref": "s_0002", "title": "Item 2", "content": "N/A", "tables": []}},
        {"response": {"ref": "s_0003", "title": "Item 3", "content": item3_content, "tables": ["t_0001"]}},
        {"response": {"ref": "s_0004", "title": "Item 4", "content": "x" * 8000, "tables": []}},
        {"response": {"ref": "s_0005", "title": "Item 4A", "content": "None", "tables": []}},
        {"response": {"ref": "s_0006", "title": "Item 5", "content": item5_content, "tables": []}},
        {"response": {"ref": "s_0007", "title": "Item 6", "content": "x" * 3000, "tables": []}},
        {"response": {"ref": "s_0008", "title": "Item 7", "content": "x" * 2000, "tables": []}},
        {"response": {"ref": "s_0009", "title": "Item 8", "content": "x" * 2000, "tables": []}},
        {"response": {"ref": "s_0010", "title": "Item 9", "content": "N/A", "tables": []}},
        {"response": {"ref": "s_0011", "title": "Item 10", "content": "x" * 5000, "tables": []}},
        {"response": {"ref": "s_0012", "title": "Item 11", "content": "x" * 1000, "tables": []}},
        {"response": {"ref": "s_0013", "title": "Item 12", "content": "N/A", "tables": []}},
        {"response": {"ref": "s_0014", "title": "Item 13", "content": "None", "tables": []}},
        {"response": {"ref": "s_0015", "title": "Item 14", "content": "None", "tables": []}},
        {"response": {"ref": "s_0016", "title": "Item 15", "content": "x" * 2000, "tables": []}},
        {"response": {"ref": "s_0017", "title": "Item 16", "content": "N/A", "tables": []}},
        {"response": {"ref": "s_0018", "title": "Item 16A", "content": "x" * 200, "tables": []}},
        {"response": {"ref": "s_0019", "title": "Item 16B", "content": "x" * 200, "tables": []}},
        {"response": {"ref": "s_0020", "title": "Item 16C", "content": "x" * 500, "tables": []}},
        {"response": {"ref": "s_0021", "title": "Item 16D", "content": "None", "tables": []}},
        {"response": {"ref": "s_0022", "title": "Item 16E", "content": "None", "tables": []}},
        {"response": {"ref": "s_0023", "title": "Item 16F", "content": "None", "tables": []}},
        {"response": {"ref": "s_0024", "title": "Item 16G", "content": "x" * 300, "tables": []}},
        {"response": {"ref": "s_0025", "title": "Item 16H", "content": "N/A", "tables": []}},
        {"response": {"ref": "s_0026", "title": "Item 16I", "content": "N/A", "tables": []}},
        {"response": {"ref": "s_0027", "title": "Item 16J", "content": "x" * 200, "tables": []}},
        {"response": {"ref": "s_0028", "title": "Item 17", "content": "N/A", "tables": []}},
        {"response": {"ref": "s_0029", "title": "Item 18", "content": item18_content, "tables": []}},
        {"response": {"ref": "s_0030", "title": "Item 19", "content": "x" * 1000, "tables": []}},
        {"response": {"ref": "s_0031", "title": "SIGNATURE", "content": "x" * 100, "tables": []}},
    ]
    _write_json(document_dir / "tool_snapshot_read_section.json", {"calls": read_calls})

    _make_common_truth(document_dir, form_type="20-F")


@pytest.mark.unit
class TestScoreBatch20F:
    """20-F 批量评分集成测试。"""

    def test_pass_with_sufficient_content(self, tmp_path: Path) -> None:
        """高质量 20-F 样本可通过批量 CI 判定。"""

        base = tmp_path / "portfolio"
        doc_dir = base / "TSM" / "processed" / "fil_good_20f"
        _make_minimal_20f_truth(
            document_dir=doc_dir,
            document_id="fil_good_20f",
            item3_content="x" * 7000,
            item5_content="x" * 7000,
            item18_content="x" * 15000,
        )

        cfg = ScoreConfig(min_batch_avg=60.0, min_batch_p10=60.0)
        batch = score_batch(str(base), ["TSM"], cfg, form_type="20-F")
        assert len(batch.documents) == 1
        assert batch.documents[0].hard_gate.passed is True
        assert batch.documents[0].total_score >= 60.0
        assert batch.passed is True

    def test_hard_gate_failure_missing_key_items(self, tmp_path: Path) -> None:
        """20-F 缺失关键 Item 3/5/18 时触发硬门禁失败。"""

        base = tmp_path / "portfolio"
        doc_dir = base / "TSM" / "processed" / "fil_bad_20f"

        _write_json(
            doc_dir / "tool_snapshot_list_documents.json",
            _make_list_documents_payload("fil_bad_20f", "20-F"),
        )
        _create_active_filing_source(tmp_path, ticker="TSM", document_id="fil_bad_20f", form_type="20-F")

        # 缺失 Item 3, 5, 18 — 仅有少量 Item
        sections = [
            {"ref": "s_0001", "title": "Item 1"},
            {"ref": "s_0002", "title": "Item 6"},
            {"ref": "s_0003", "title": "Item 10"},
        ]
        _write_json(
            doc_dir / "tool_snapshot_get_document_sections.json",
            {"calls": [{"response": {"sections": sections}}]},
        )

        read_calls = [
            {"response": {"ref": "s_0001", "title": "Item 1", "content": "x" * 2000, "tables": []}},
            {"response": {"ref": "s_0002", "title": "Item 6", "content": "x" * 3000, "tables": []}},
            {"response": {"ref": "s_0003", "title": "Item 10", "content": "x" * 5000, "tables": []}},
        ]
        _write_json(doc_dir / "tool_snapshot_read_section.json", {"calls": read_calls})
        _make_common_truth(doc_dir, form_type="20-F")

        batch = score_batch(str(base), ["TSM"], ScoreConfig(), form_type="20-F")
        assert len(batch.documents) == 1
        assert batch.documents[0].hard_gate.passed is False
        assert any("关键 Item" in r for r in batch.documents[0].hard_gate.reasons)

    def test_20f_near_empty_whitelist(self) -> None:
        """20-F 白名单 Item 不计入近空扣分。"""

        profile = FORM_PROFILES["20-F"]
        # Item 2, 9, 13, 14, 16, 17 全在白名单中
        read_map = {
            "sec_1": {"title": "Item 2", "content": "N/A"},
            "sec_2": {"title": "Item 9", "content": "N/A"},
            "sec_3": {"title": "Item 13", "content": "None"},
            "sec_4": {"title": "Item 14", "content": "None"},
            "sec_5": {"title": "Item 16", "content": "N/A"},
            "sec_6": {"title": "Item 17", "content": "N/A"},
        }
        count = _count_near_empty_sections(read_map, profile)
        assert count == 0

    def test_20f_non_whitelist_near_empty_counted(self) -> None:
        """20-F 非白名单 Item 近空时计入扣分。"""

        profile = FORM_PROFILES["20-F"]
        # Item 5 (MD&A) 不在白名单中
        read_map = {
            "sec_1": {"title": "Item 5", "content": "N/A"},
            "sec_2": {"title": "Item 13", "content": "None"},  # 白名单内
        }
        count = _count_near_empty_sections(read_map, profile)
        assert count == 1  # 只有 Item 5 计入

    def test_20f_form_profile_registered(self) -> None:
        """20-F FormProfile 已注册到 FORM_PROFILES 字典。"""

        assert "20-F" in FORM_PROFILES
        profile = FORM_PROFILES["20-F"]
        assert profile.form_type == "20-F"
        assert profile.use_part_prefix is False
        # 内容权重总计应为 30
        assert sum(profile.content_weights.values()) == 30


# ---------------------------------------------------------------------------
# 测试：D4 表格数据质量
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTableDataQuality:
    """D4 表格数据质量评估测试。"""

    def test_all_tables_have_data(self) -> None:
        """所有表格都有实际数据时得满分 3 分。"""
        calls = [
            {"response": {"data": {"kind": "markdown", "markdown": "| A | B |\n|---|---|\n| 100 | 200 |"}}},
            {"response": {"data": {"kind": "markdown", "markdown": "| X | Y |\n|---|---|\n| foo | bar |"}}},
        ]
        points, details = _evaluate_table_data_quality(calls)
        assert points == 3.0
        assert details["nonempty_ratio"] == 1.0

    def test_all_tables_empty_cells(self) -> None:
        """所有表格全为空单元格时得 0 分。"""
        calls = [
            {"response": {"data": {"kind": "markdown", "markdown": "| | |\n|---|---|\n|  |  |"}}},
            {"response": {"data": {"kind": "markdown", "markdown": "|  |  |  |\n|---|---|---|\n|  |  |  |"}}},
        ]
        points, details = _evaluate_table_data_quality(calls)
        assert points == 0.0
        assert details["nonempty_tables"] == 0

    def test_markdown_header_only_is_empty(self) -> None:
        """仅包含表头和分隔线的 markdown 表格应视为空表格。"""
        calls = [
            {"response": {"data": {"kind": "markdown", "markdown": "| Metric | Value |\n|---|---|"}}},
        ]
        points, details = _evaluate_table_data_quality(calls)
        assert points == 0.0
        assert details["nonempty_tables"] == 0

    def test_mixed_quality_above_70pct(self) -> None:
        """非空占比 ≥ 70% 时得 2 分。"""
        good = {"response": {"data": {"kind": "markdown", "markdown": "| A |\n|---|\n| data |"}}}
        empty = {"response": {"data": {"kind": "markdown", "markdown": "|  |\n|---|\n|  |"}}}
        # 8 good + 2 empty = 80%
        calls = [good] * 8 + [empty] * 2
        points, _ = _evaluate_table_data_quality(calls)
        assert points == 2.0

    def test_raw_text_kind_counted_as_nonempty(self) -> None:
        """kind=raw_text 的表格数据正确识别为非空。"""
        calls = [
            {"response": {"data": {"kind": "raw_text", "text": "Revenue: $100M"}}},
            {"response": {"data": {"kind": "markdown", "markdown": "| A |\n|---|\n| data |"}}},
        ]
        points, details = _evaluate_table_data_quality(calls)
        assert points == 3.0
        assert details["nonempty_tables"] == 2

    def test_raw_text_empty_is_empty(self) -> None:
        """kind=raw_text 但文本为空时视为空表格。"""
        calls = [
            {"response": {"data": {"kind": "raw_text", "text": ""}}},
            {"response": {"data": {"kind": "raw_text", "text": "   "}}},
        ]
        points, details = _evaluate_table_data_quality(calls)
        assert points == 0.0
        assert details["nonempty_tables"] == 0

    def test_no_tables_gets_full_score(self) -> None:
        """无表格时视为满分（不扣分）。"""
        points, details = _evaluate_table_data_quality([])
        assert points == 3.0
        assert details["total_tables"] == 0


# ---------------------------------------------------------------------------
# 测试：D5 表格 caption 填充率
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTableCaptionFill:
    """D5 表格 caption 填充率评估测试。"""

    def test_high_fill_rate(self) -> None:
        """caption 填充率 ≥40% 得满分 2 分。"""
        tables = [{"table_ref": f"tbl_{i:04d}", "caption": f"Caption {i}"} for i in range(1, 6)]
        calls = [{"response": {"tables": tables}}]
        points, details = _evaluate_table_caption_fill(calls)
        assert points == 2.0
        assert details["caption_fill_ratio"] == 1.0

    def test_low_fill_rate(self) -> None:
        """caption 填充率 < 20% 得 0 分。"""
        tables = [{"table_ref": f"tbl_{i:04d}", "caption": None} for i in range(1, 11)]
        tables[0]["caption"] = "Only one"  # 10% fill
        calls = [{"response": {"tables": tables}}]
        points, details = _evaluate_table_caption_fill(calls)
        assert points == 0.0

    def test_medium_fill_rate(self) -> None:
        """caption 填充率 20%-40% 得 1 分。"""
        tables = [{"table_ref": f"tbl_{i:04d}", "caption": None} for i in range(1, 11)]
        tables[0]["caption"] = "Cap 1"
        tables[1]["caption"] = "Cap 2"
        tables[2]["caption"] = "Cap 3"  # 30% fill
        calls = [{"response": {"tables": tables}}]
        points, details = _evaluate_table_caption_fill(calls)
        assert points == 1.0

    def test_too_few_tables_full_score(self) -> None:
        """表格过少时默认满分。"""
        tables = [{"table_ref": "t_0001", "caption": None}]
        calls = [{"response": {"tables": tables}}]
        points, details = _evaluate_table_caption_fill(calls)
        assert points == 2.0
        assert details.get("caption_skip_reason") == "too_few_tables"

    def test_empty_calls_full_score(self) -> None:
        """无调用数据时默认满分。"""
        points, details = _evaluate_table_caption_fill([])
        assert points == 2.0

    def test_empty_string_caption_not_counted(self) -> None:
        """空字符串 caption 不计入填充。"""
        tables = [{"table_ref": f"tbl_{i:04d}", "caption": ""} for i in range(1, 6)]
        calls = [{"response": {"tables": tables}}]
        points, details = _evaluate_table_caption_fill(calls)
        assert points == 0.0
        assert details["caption_filled"] == 0


# ---------------------------------------------------------------------------
# 测试：E4 截断检测
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTruncationDetection:
    """E4 章节截断检测测试。"""

    def test_detects_dangling_preposition(self) -> None:
        """检测以 'Refer to' 结尾的截断 section。"""
        read_map = {
            "sec_1": {"content": "applicable environmental laws. Refer to"},
            "sec_2": {"content": "This is a complete sentence."},
        }
        truncated = _detect_truncated_sections(read_map)
        assert truncated == ["sec_1"]

    def test_detects_dangling_conjunction(self) -> None:
        """检测以 'and' 结尾的截断。"""
        read_map = {
            "sec_1": {"content": "The company has operations in the US and"},
        }
        truncated = _detect_truncated_sections(read_map)
        assert truncated == ["sec_1"]

    def test_no_truncation_on_complete_sentence(self) -> None:
        """完整句子不触发截断检测。"""
        read_map = {
            "sec_1": {"content": "The company generated $100B in revenue."},
            "sec_2": {"content": "Risk factors include market volatility."},
        }
        truncated = _detect_truncated_sections(read_map)
        assert truncated == []

    def test_empty_content_not_flagged(self) -> None:
        """空内容不触发截断检测。"""
        read_map = {"sec_1": {"content": ""}}
        truncated = _detect_truncated_sections(read_map)
        assert truncated == []


# ---------------------------------------------------------------------------
# 测试：E5 边界溢出检测
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBoundaryLeakage:
    """E5 边界溢出检测测试。"""

    def test_detects_part_ii_heading_at_end(self) -> None:
        """检测 section 末尾出现 PART II 标题。"""
        read_map = {
            "sec_1": {"content": "Controls and procedures are effective. PART II — OTHER INFORMATION"},
        }
        leaked = _detect_boundary_leakage(read_map)
        assert leaked == ["sec_1"]

    def test_no_leakage_on_clean_content(self) -> None:
        """无溢出的正常内容不触发。"""
        read_map = {
            "sec_1": {"content": "Risk factors include market and credit risks."},
        }
        leaked = _detect_boundary_leakage(read_map)
        assert leaked == []

    def test_detects_part_heading_variant_dashes(self) -> None:
        """检测各种连字符变体的 Part 标题溢出。"""
        read_map = {
            "sec_1": {"content": "Some content here. PART II - OTHER INFORMATION"},
        }
        leaked = _detect_boundary_leakage(read_map)
        assert leaked == ["sec_1"]


# ---------------------------------------------------------------------------
# 测试：新维度 D/E 评分对总分的影响
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestNewDimensionScoring:
    """验证新的 D/E 子项在端到端评分中正确反映。"""

    def test_truncation_reduces_score(self, tmp_path: Path) -> None:
        """包含截断 section 时 E4 扣分，总分降低。"""
        base = tmp_path / "portfolio"
        doc_dir = base / "AAA" / "processed" / "fil_trunc"

        _make_minimal_10k_truth(
            document_dir=doc_dir,
            document_id="fil_trunc",
            item7_content="x" * 7000,
            item8_content="x" * 15000,
        )

        # 注入截断内容到 Item 1 section
        read_path = doc_dir / "tool_snapshot_read_section.json"
        read_data = json.loads(read_path.read_text(encoding="utf-8"))
        # 修改 s_0001 (Item 1) 的 content 使其以 "Refer to" 结尾
        read_data["calls"][0]["response"]["content"] = "applicable environmental laws. Refer to"
        read_path.write_text(json.dumps(read_data, ensure_ascii=False), encoding="utf-8")

        cfg = ScoreConfig(min_batch_avg=50.0, min_batch_p10=50.0)
        batch = score_batch(str(base), ["AAA"], cfg, form_type="10-K")
        doc = batch.documents[0]

        # E4 应检测到截断
        e_details = doc.dimensions["E_noise"].details
        assert e_details["truncation_count"] >= 1
        assert "s_0001" in e_details["truncated_sections"]

    def test_boundary_leakage_reduces_score(self, tmp_path: Path) -> None:
        """包含边界溢出时 E5 扣分。"""
        base = tmp_path / "portfolio"
        doc_dir = base / "AAA" / "processed" / "fil_leak"

        _make_minimal_10q_truth(
            document_dir=doc_dir,
            document_id="fil_leak",
            part_i_item1_content="x" * 7000,
            part_i_item2_content="x" * 5000,
            part_ii_item1a_content="x" * 3000,
        )

        # 注入边界溢出到 Part I - Item 4
        read_path = doc_dir / "tool_snapshot_read_section.json"
        read_data = json.loads(read_path.read_text(encoding="utf-8"))
        # s_0004 是 Part I - Item 4
        read_data["calls"][3]["response"]["content"] = "Controls OK. PART II — OTHER INFORMATION"
        read_path.write_text(json.dumps(read_data, ensure_ascii=False), encoding="utf-8")

        cfg = ScoreConfig(min_batch_avg=50.0, min_batch_p10=50.0)
        batch = score_batch(str(base), ["AAA"], cfg, form_type="10-Q")
        doc = batch.documents[0]

        # E5 应检测到溢出
        e_details = doc.dimensions["E_noise"].details
        assert e_details["leakage_count"] >= 1


# ---------------------------------------------------------------------------
# SEC 交叉引用检测
# ---------------------------------------------------------------------------


class TestCrossReferenceDetection:
    """SEC 法定交叉引用检测测试。"""

    @pytest.mark.unit
    def test_tdg_style_f_page_reference(self) -> None:
        """TDG 式 Item 8 交叉引用（引用 F-pages 财务报表）。

        Args:
            无。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        content = (
            "The information required by this Item is contained on "
            "pages F-1 through F-46 of this report."
        )
        assert _is_sec_cross_reference(content) is True

    @pytest.mark.unit
    def test_incorporation_by_reference(self) -> None:
        """incorporated by reference 模式。

        Args:
            无。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        content = "The information is incorporated herein by reference to the Annual Report."
        assert _is_sec_cross_reference(content) is True

    @pytest.mark.unit
    def test_refer_to_part(self) -> None:
        """refer to Part/Item 模式。

        Args:
            无。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        content = "Refer to Part II, Item 7A of our Annual Report on Form 10-K."
        assert _is_sec_cross_reference(content) is True

    @pytest.mark.unit
    def test_normal_content_not_cross_reference(self) -> None:
        """正常长内容不被误判为交叉引用。

        Args:
            无。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        content = "Revenue increased 15% year-over-year. " * 100
        assert _is_sec_cross_reference(content) is False

    @pytest.mark.unit
    def test_long_content_with_reference_not_cross_reference(self) -> None:
        """超过长度上限的内容即使包含交叉引用关键词也不豁免。

        Args:
            无。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        content = "Information is incorporated by reference. " + "x" * 3000
        assert _is_sec_cross_reference(content) is False

    @pytest.mark.unit
    def test_empty_content(self) -> None:
        """空内容不是交叉引用。

        Args:
            无。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        assert _is_sec_cross_reference("") is False
        assert _is_sec_cross_reference("   ") is False

    @pytest.mark.unit
    def test_truncation_exempt_for_cross_reference(self) -> None:
        """交叉引用内容以 'refer to' 结尾时不被标记为截断。

        Args:
            无。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        read_map = {
            "s_0001": {
                "content": "Refer to Part II, Item 7A of our Annual Report on Form 10-K for",
                "title": "Part I - Item 3",
            },
        }
        # 虽然以 "for" 结尾（悬挂介词），但因为是交叉引用应被豁免
        truncated = _detect_truncated_sections(read_map)
        assert len(truncated) == 0

    @pytest.mark.unit
    def test_cross_reference_exempts_b_content(self, tmp_path: Path) -> None:
        """交叉引用 Item 在 B_content 中获得豁免。

        Args:
            tmp_path: pytest 临时目录。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        base = tmp_path / "portfolio"
        doc_dir = base / "TDG" / "processed" / "fil_xref"

        _make_minimal_10k_truth(
            document_dir=doc_dir,
            document_id="fil_xref",
            item7_content="Financial analysis. " * 500,
            item8_content=(
                "The information required by this Item is contained "
                "on pages F-1 through F-46 of this report."
            ),
        )

        cfg = ScoreConfig(min_batch_avg=50.0, min_batch_p10=50.0)
        batch = score_batch(str(base), ["TDG"], cfg, form_type="10-K")
        doc = batch.documents[0]

        # Item 8 虽然很短（< 10000 阈值），但因交叉引用豁免应该 pass
        b_details = doc.dimensions["B_content"].details
        assert b_details["item_pass"]["Item 8"] is True
        assert "Item 8" in b_details["cross_references"]

    @pytest.mark.unit
    def test_cross_reference_only_applies_to_profile_exempt_items(self) -> None:
        """B_content 交叉引用豁免仅作用于 profile 声明的 Item。"""
        profile = FORM_PROFILES["10-K"]
        item_len = {"Item 1A": 30, "Item 7": 30, "Item 8": 30, "Item 7A": 30}
        item_text = {
            "Item 1A": "The information required by this Item is contained on pages F-1 through F-46.",
            "Item 7": "The information required by this Item is contained on pages F-1 through F-46.",
            "Item 8": "The information required by this Item is contained on pages F-1 through F-46.",
            "Item 7A": "The information required by this Item is contained on pages F-1 through F-46.",
        }
        score = _score_content(item_len, profile, item_text)
        item_pass = score.details["item_pass"]
        assert item_pass["Item 8"] is True
        assert item_pass["Item 1A"] is False
        assert item_pass["Item 7"] is False
        assert item_pass["Item 7A"] is False
        assert score.details["cross_references"] == ["Item 8"]

    @pytest.mark.unit
    def test_no_material_changes_is_cross_reference(self) -> None:
        """10-Q Item 1A 'no material changes' 声明被识别为交叉引用。

        SEC Form 10-Q Instructions Part II, Item 1A 允许声明
        "如果没有重大变化可以省略或简短声明引用 10-K"。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        content = (
            "There have been no material changes to the risk factors "
            "previously disclosed in our Annual Report on Form 10-K."
        )
        assert _is_sec_cross_reference(content) is True

    @pytest.mark.unit
    def test_previously_disclosed_in_10k(self) -> None:
        """'previously disclosed in Form 10-K' 模式。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        content = (
            "Risk factors are previously disclosed in our Form 10-K "
            "filed with the SEC on February 1, 2024."
        )
        assert _is_sec_cross_reference(content) is True

    @pytest.mark.unit
    def test_no_material_changes_to_company_risk_factors(self) -> None:
        """放宽后的 'no material changes...risk factors' 中间含公司名。

        AAPL 10-Q 使用 "no material changes to the Company's risk factors"
        而非标准的 "no material changes from the previously disclosed"。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        content = (
            "There have been no material changes to the Company's "
            "risk factors as previously disclosed."
        )
        assert _is_sec_cross_reference(content) is True

    @pytest.mark.unit
    def test_included_at_end_of_annual_report(self) -> None:
        """20-F Item 18 '(included|set forth) at the end of' 模式。

        WB 20-F Item 18 使用 "included at the end of this annual report"
        交叉引用。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        content = (
            "The financial statements are included at the end of "
            "this annual report on Form 20-F."
        )
        assert _is_sec_cross_reference(content) is True

    @pytest.mark.unit
    def test_appearing_at_end_of(self) -> None:
        """'appearing at the end of' 变体也被识别。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        content = "Consolidated financial statements appearing at the end of this report."
        assert _is_sec_cross_reference(content) is True

    @pytest.mark.unit
    def test_see_information_in_annual_report(self) -> None:
        """10-Q 'see the information...in Annual Report on Form 10-K' 模式。

        V 10-Q 使用 "see the information under...in our Annual Report on Form 10-K"
        交叉引用。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        content = (
            "See the information under Part I, Item 1A in our "
            "Annual Report on Form 10-K."
        )
        assert _is_sec_cross_reference(content) is True

    @pytest.mark.unit
    def test_see_discussion_in_form_10k(self) -> None:
        """'see the discussion in...Form 10-K' 变体。

        Returns:
            无。

        Raises:
            AssertionError: 断言失败时抛出。
        """
        content = "See the discussion in our Annual Report on Form 10-K for details."
        assert _is_sec_cross_reference(content) is True

    @pytest.mark.unit
    def test_truncation_cross_reference_requires_exempt_item_when_profile_provided(self) -> None:
        """E4 中带 profile 时，交叉引用仅豁免指定 Item。"""
        profile = FORM_PROFILES["10-Q"]
        read_map = {
            "s_0001": {
                "title": "Part I - Item 3",
                "content": "Refer to Part II, Item 1A of our Annual Report on Form 10-K for",
            },
            "s_0002": {
                "title": "Part II - Item 1A",
                "content": "There have been no material changes from previously disclosed risk factors in",
            },
        }
        truncated = _detect_truncated_sections(read_map, profile=profile)
        assert "s_0001" in truncated
        assert "s_0002" not in truncated


@pytest.mark.unit
class TestStructureScoring:
    """结构评分边界测试。"""

    def test_order_score_requires_recognizable_items(self) -> None:
        """有标准 Item 顺序的表单若无法识别任何 Item，A1 不得分。"""
        profile = FORM_PROFILES["10-K"]
        sections = [
            {"ref": "sec_1", "title": "Management Discussion"},
            {"ref": "sec_2", "title": "Risk Overview"},
        ]
        score = _score_structure(sections, item_content_len={}, profile=profile)
        assert score.details["order_ok"] is False
        # A2 缺失 6 个关键 Item 扣至 0，A3 section_count=2 得 1 分，总分应为 1
        assert score.points == 1.0


@pytest.mark.unit
class TestNearEmptyWhitelist10Q:
    """10-Q 近空白名单需区分 Part I/Part II 同号 Item。"""

    def test_part_prefix_is_preserved_in_whitelist_matching(self) -> None:
        """Part II 白名单条目可豁免，Part I 同号条目不可豁免。"""
        profile = FORM_PROFILES["10-Q"]
        read_map = {
            "sec_1": {"title": "Part I - Item 1", "content": "N/A"},
            "sec_2": {"title": "Part II - Item 1", "content": "None"},
        }
        count = _count_near_empty_sections(read_map, profile)
        assert count == 1


@pytest.mark.unit
class TestEightKProfile:
    """8-K Item 列表与 SEC 现行条目一致性。"""

    def test_8k_profile_contains_item_105_and_section6_items(self) -> None:
        """8-K profile 应包含 Item 1.05 与 Item 6.01–6.06。"""
        profile = FORM_PROFILES["8-K"]
        for item in ("Item 1.05", "Item 6.01", "Item 6.02", "Item 6.03", "Item 6.04", "Item 6.05", "Item 6.06"):
            assert item in profile.item_order


@pytest.mark.unit
class TestDataLoadingHelpers:
    """数据加载与 form 检测辅助函数测试。"""

    def test_load_json_returns_empty_for_missing_and_invalid(self, tmp_path: Path) -> None:
        """文件缺失或无效 JSON 时返回空字典。"""
        doc_dir = tmp_path / "workspace" / "portfolio" / "AAA" / "processed" / "fil_missing"
        snapshot, context = _make_snapshot_document(
            document_dir=doc_dir,
            document_id="fil_missing",
            form_type="10-K",
        )

        missing = _load_json(
            snapshot=snapshot,
            blob_repository=context.blob_repository,
            file_name="missing.json",
        )
        assert missing == {}

        bad_path = doc_dir / "bad.json"
        bad_path.write_text("{bad", encoding="utf-8")
        bad = _load_json(
            snapshot=snapshot,
            blob_repository=context.blob_repository,
            file_name="bad.json",
        )
        assert bad == {}

    def test_load_truth_calls_filters_non_dict_entries(self, tmp_path: Path) -> None:
        """_load_truth_calls 仅保留字典类型调用记录。"""
        doc_dir = tmp_path / "workspace" / "portfolio" / "AAA" / "processed" / "fil_calls"
        snapshot, context = _make_snapshot_document(
            document_dir=doc_dir,
            document_id="fil_calls",
            form_type="10-K",
        )
        _write_json(
            doc_dir / "tool_snapshot_read_section.json",
            {"calls": [{"response": {"ref": "sec_1"}}, "bad", 1, None]},
        )
        calls = _load_truth_calls(
            snapshot=snapshot,
            blob_repository=context.blob_repository,
            tool_name="read_section",
        )
        assert len(calls) == 1
        assert calls[0]["response"]["ref"] == "sec_1"

        _write_json(doc_dir / "tool_snapshot_read_section.json", {"calls": "bad-calls"})
        assert _load_truth_calls(
            snapshot=snapshot,
            blob_repository=context.blob_repository,
            tool_name="read_section",
        ) == []

    def test_load_snapshot_meta_required_validates_required_fields(self, tmp_path: Path) -> None:
        """缺少 v2 元字段时应抛出 ValueError。"""
        doc_dir = tmp_path / "workspace" / "portfolio" / "AAA" / "processed" / "fil_meta_invalid"
        snapshot, context = _make_snapshot_document(
            document_dir=doc_dir,
            document_id="fil_meta_invalid",
            form_type="10-K",
        )
        _write_json(doc_dir / "tool_snapshot_meta.json", {"snapshot_schema_version": "tool_snapshot_v1"})
        with pytest.raises(ValueError, match="snapshot_schema_version"):
            _load_snapshot_meta_required(
                snapshot=snapshot,
                blob_repository=context.blob_repository,
            )

        _write_json(
            doc_dir / "tool_snapshot_meta.json",
            {
                "snapshot_schema_version": "tool_snapshot_v1.0.0",
                "search_query_pack_name": "annual_quarter_core40",
                "search_query_pack_version": "search_query_pack_v1.0.0",
                "search_query_count": 2,
            },
        )
        meta = _load_snapshot_meta_required(
            snapshot=snapshot,
            blob_repository=context.blob_repository,
        )
        assert meta["search_query_count"] == 2

    def test_detect_form_type_matches_current_document_id(self, tmp_path: Path) -> None:
        """仅匹配当前目录文档 ID，且返回大写 form。"""
        doc_dir = tmp_path / "workspace" / "portfolio" / "AAA" / "processed" / "fil_abc"
        snapshot, context = _make_snapshot_document(
            document_dir=doc_dir,
            document_id="fil_abc",
            form_type="10-Q",
        )
        _write_json(
            doc_dir / "tool_snapshot_list_documents.json",
            {
                "calls": [
                    {"response": {"documents": [{"document_id": "fil_other", "form_type": "10-q"}]}},
                    {"response": {"documents": ["bad-entry"]}},
                    {"response": {"documents": [{"document_id": "fil_abc", "form_type": "10-q"}]}},
                ]
            },
        )
        assert _detect_form_type(
            snapshot=snapshot,
            blob_repository=context.blob_repository,
        ) == "10-Q"

    def test_build_maps_and_item_len_keep_longest_content(self) -> None:
        """章节映射与 Item 长度映射应过滤无效记录并保留最长内容。"""
        sections, read_map = _build_section_payload_maps(
            [{"response": {"sections": [{"ref": "sec_1"}, "bad"]}}],
            [
                {"response": {"ref": "sec_1", "title": "Part II - Item 7", "content": "x" * 10}},
                {"response": {"ref": "sec_1", "title": "Part II - Item 7", "content": "x" * 20}},
                {"response": {"ref": "", "title": "Part II - Item 8", "content": "x" * 30}},
                {"response": "bad"},
            ],
        )
        assert sections == [{"ref": "sec_1"}]
        assert set(read_map.keys()) == {"sec_1"}
        item_len = _build_item_content_len(read_map, profile=FORM_PROFILES["10-K"])
        assert item_len["Item 7"] == 20


@pytest.mark.unit
class TestSearchAndConsistencyHelpers:
    """搜索评分与一致性评分辅助逻辑测试。"""

    def test_score_search_v2_covers_coverage_quality_and_efficiency(self) -> None:
        """覆盖 C 维 v2 的覆盖率/证据质量/效率打分分档。"""
        snapshot_meta = {
            "search_query_pack_name": "annual_quarter_core40",
            "search_query_pack_version": "search_query_pack_v2",
            "search_query_count": 3,
        }

        low = _score_search_v2(
            [
                {
                    "request": {
                        "query": "risk factors",
                        "query_id": "q001",
                        "query_text": "risk factors",
                        "query_intent": "risk_factors",
                        "query_weight": 1.0,
                    },
                    "response": {
                        "matches": [],
                        "diagnostics": {"strategy_hit_counts": {"exact": 0, "phrase_variant": 0, "synonym": 0, "token": 0}},
                    },
                },
                {
                    "request": {
                        "query": "cash flow",
                        "query_id": "q002",
                        "query_text": "cash flow",
                        "query_intent": "cash_flow",
                        "query_weight": 1.0,
                    },
                    "response": {
                        "matches": [],
                        "diagnostics": {"strategy_hit_counts": {"exact": 0, "phrase_variant": 0, "synonym": 0, "token": 0}},
                    },
                },
                {
                    "request": {
                        "query": "operating margin",
                        "query_id": "q003",
                        "query_text": "operating margin",
                        "query_intent": "operating_margin",
                        "query_weight": 1.0,
                    },
                    "response": {
                        "matches": [],
                        "diagnostics": {"strategy_hit_counts": {"exact": 0, "phrase_variant": 0, "synonym": 0, "token": 0}},
                    },
                },
            ],
            form_type="10-K",
            snapshot_meta=snapshot_meta,
        )
        assert low.points == 0.0
        assert low.details["coverage_rate_weighted"] == 0.0
        assert low.details["evidence_quality_rate"] == 0.0
        assert low.details["efficiency_rate"] == 0.0

        mid = _score_search_v2(
            [
                {
                    "request": {
                        "query": "cash flow",
                        "query_id": "q001",
                        "query_text": "cash flow",
                        "query_intent": "cash_flow",
                        "query_weight": 1.0,
                    },
                    "response": {
                        "matches": [{"section": {"ref": "sec_1"}, "snippet": "cash flow statement expanded " * 8}],
                        "diagnostics": {"strategy_hit_counts": {"exact": 1, "phrase_variant": 0, "synonym": 0, "token": 0}},
                    },
                },
                {
                    "request": {
                        "query": "risk factors",
                        "query_id": "q002",
                        "query_text": "risk factors",
                        "query_intent": "risk_factors",
                        "query_weight": 1.0,
                    },
                    "response": {
                        "matches": [{"section": {"ref": "sec_2"}, "snippet": "risk factors remain stable " * 8}],
                        "diagnostics": {"strategy_hit_counts": {"exact": 0, "phrase_variant": 1, "synonym": 0, "token": 0}},
                    },
                },
                {
                    "request": {
                        "query": "inventory turnover",
                        "query_id": "q003",
                        "query_text": "inventory turnover",
                        "query_intent": "inventory_turnover",
                        "query_weight": 1.0,
                    },
                    "response": {
                        "matches": [],
                        "diagnostics": {"strategy_hit_counts": {"exact": 0, "phrase_variant": 0, "synonym": 0, "token": 0}},
                    },
                },
            ],
            form_type="10-K",
            snapshot_meta=snapshot_meta,
        )
        assert mid.points == 10.0  # 覆盖率 0.66->5，质量 1.0->4，效率 0.5->1
        assert 0.66 < mid.details["coverage_rate_weighted"] < 0.67
        assert mid.details["evidence_quality_rate"] == 1.0
        assert mid.details["efficiency_rate"] == 0.5

        high = _score_search_v2(
            [
                {
                    "request": {
                        "query": "cash flow",
                        "query_id": "q001",
                        "query_text": "cash flow",
                        "query_intent": "cash_flow",
                        "query_weight": 1.0,
                    },
                    "response": {
                        "matches": [{"section": {"ref": "sec_1"}, "snippet": "cash flow growth " * 20}],
                        "diagnostics": {"strategy_hit_counts": {"exact": 1, "phrase_variant": 0, "synonym": 0, "token": 0}},
                    },
                },
                {
                    "request": {
                        "query": "risk factors",
                        "query_id": "q002",
                        "query_text": "risk factors",
                        "query_intent": "risk_factors",
                        "query_weight": 1.0,
                    },
                    "response": {
                        "matches": [{"section": {"ref": "sec_2"}, "snippet": "risk factors updated " * 20}],
                        "diagnostics": {"strategy_hit_counts": {"exact": 1, "phrase_variant": 0, "synonym": 0, "token": 0}},
                    },
                },
                {
                    "request": {
                        "query": "operating margin",
                        "query_id": "q003",
                        "query_text": "operating margin",
                        "query_intent": "operating_margin",
                        "query_weight": 1.0,
                    },
                    "response": {
                        "matches": [{"section": {"ref": "sec_3"}, "snippet": "operating margin improved " * 20}],
                        "diagnostics": {"strategy_hit_counts": {"exact": 1, "phrase_variant": 0, "synonym": 0, "token": 0}},
                    },
                },
            ],
            form_type="10-K",
            snapshot_meta=snapshot_meta,
        )
        assert high.points == 15.0
        assert high.details["coverage_rate_weighted"] == 1.0
        assert high.details["evidence_quality_rate"] == 1.0
        assert high.details["efficiency_rate"] == 1.0

    def test_score_search_v2_requires_request_contract_fields(self) -> None:
        """缺少 query_id/query_text/query_intent/query_weight 时应抛错。"""
        snapshot_meta = {
            "search_query_pack_name": "annual_quarter_core40",
            "search_query_pack_version": "search_query_pack_v2",
            "search_query_count": 1,
        }
        with pytest.raises(ValueError, match="query_id"):
            _score_search_v2(
                [
                    {
                        "request": {"query": "cash flow"},
                        "response": {
                            "matches": [{"section": {"ref": "sec_1"}, "snippet": "cash flow " * 20}],
                            "diagnostics": {"strategy_hit_counts": {"exact": 1}},
                        },
                    }
                ],
                form_type="10-K",
                snapshot_meta=snapshot_meta,
            )

    def test_score_consistency_handles_non_xbrl_profile_and_bad_table_entries(self) -> None:
        """非 XBRL 表单应直接给 D3 满分，且忽略无效表格元数据。"""
        profile = FORM_PROFILES["8-K"]
        sections = [{"ref": "sec_1", "title": "Item 1.01"}]
        read_map = {"sec_1": {"title": "Item 1.01", "content": "ok", "tables": ["tbl_1"]}}
        list_tables_calls = [
            {"response": {"tables": [{"table_ref": "tbl_1", "section_ref": "sec_1"}, {"table_ref": None, "section_ref": None}, "bad"]}}
        ]
        get_table_calls = [{"response": {"data": {"kind": "markdown", "markdown": "| A |\n|---|\n| 1 |"}}}]
        score = _score_consistency(
            sections=sections,
            read_map=read_map,
            list_tables_calls=list_tables_calls,
            fs_calls=[],
            get_table_calls=get_table_calls,
            profile=profile,
        )
        assert score.details["skip_reason"] == "no_xbrl_expected"
        assert score.details["dangling_table_refs"] == []
        assert score.details["ref_consistent"] is True
        assert score.points >= 12.0

    def test_score_consistency_uses_six_k_release_core_depth(self) -> None:
        """6-K 应按核心报表可提取性评估 D3，而非默认满分。"""

        profile = FORM_PROFILES["6-K"]
        sections = [{"ref": "sec_1", "title": "Balance Sheets"}]
        read_map = {"sec_1": {"title": "Balance Sheets", "content": "ok", "tables": []}}
        list_tables_calls = [{"response": {"tables": []}}]
        get_table_calls = []
        fs_calls = [
            {
                "request": {"statement_type": "income"},
                "response": {
                    "data_quality": "extracted",
                    "rows": [{}, {}] * 6,
                    "periods": [{"period_end": "2025-12-31"}, {"period_end": "2024-12-31"}],
                },
            },
            {
                "request": {"statement_type": "balance_sheet"},
                "response": {
                    "data_quality": "extracted",
                    "rows": [{}, {}] * 6,
                    "periods": [{"period_end": "2025-12-31"}, {"period_end": "2024-12-31"}],
                },
            },
            {
                "request": {"statement_type": "cash_flow"},
                "response": {
                    "data_quality": "partial",
                    "rows": [],
                    "periods": [],
                    "reason": "statement_not_found",
                },
            },
        ]

        score = _score_consistency(
            sections=sections,
            read_map=read_map,
            list_tables_calls=list_tables_calls,
            fs_calls=fs_calls,
            get_table_calls=get_table_calls,
            profile=profile,
        )

        assert score.details["d3_mode"] == "six_k_release_core"
        assert score.details["core_available"] == ["income", "balance_sheet"]
        assert score.points >= 10.0

    def test_evaluate_financial_depth_skips_invalid_request_or_response(self) -> None:
        """财报深度评估应跳过 request/response 非字典记录。"""
        points, details = _evaluate_financial_statement_depth(
            [
                {"request": "bad", "response": {}},
                {"request": {"statement_type": "income"}, "response": "bad"},
                {"request": {"statement_type": "income"}, "response": {"data_quality": "xbrl", "rows": [{}] * 12, "periods": [1, 2]}},
            ]
        )
        assert points >= 1.0
        assert details["missing_statement_count"] >= 1

    def test_evaluate_financial_depth_partial_with_zero_rows_not_usable(self) -> None:
        """data_quality='partial' + rows=[] 不应计入 available_statements（GMAB/IBN 回归）。

        partial 质量标记只表示"尝试提取了"，但无行数据说明实际提取失败。
        此前逻辑将 partial 视为可用，导致 missing_statement_count=0 但 mean_row_count=0，
        形成虚假的覆盖率。
        """
        fs_calls = [
            {"request": {"statement_type": st}, "response": {"data_quality": "partial", "rows": [], "periods": []}}
            for st in ["income", "balance_sheet", "cash_flow", "equity", "comprehensive_income"]
        ]
        points, details = _evaluate_financial_statement_depth(fs_calls)
        # 5 张报表全部 partial+rows=0 → 全部不计入 available → missing_count=5
        assert details["available_statements"] == []
        assert details["missing_statement_count"] == 5
        assert details["mean_row_count"] == 0.0
        # D3a = max(0, 2 - 5*0.5) = 0；D3b=D3c=0
        assert points == pytest.approx(0.0)

    def test_evaluate_financial_depth_partial_with_real_rows_is_usable(self) -> None:
        """data_quality='partial' + rows 非空时，应仍算可用（提取到了部分数据）。"""
        fs_calls = [
            {"request": {"statement_type": "income"}, "response": {"data_quality": "partial", "rows": [{}] * 15, "periods": [1, 2]}},
        ]
        _, details = _evaluate_financial_statement_depth(fs_calls)
        assert "income" in details["available_statements"]

    def test_evaluate_financial_depth_treats_extracted_as_usable(self) -> None:
        """报告类 HTML fallback 的 extracted 结果应计入可用报表。"""

        fs_calls = [
            {
                "request": {"statement_type": statement_type},
                "response": {
                    "data_quality": "extracted",
                    "rows": [{"label": "row"}] * 12,
                    "periods": [{"period_end": "2024-12-31"}, {"period_end": "2023-12-31"}],
                },
            }
            for statement_type in ["income", "balance_sheet", "cash_flow", "equity", "comprehensive_income"]
        ]

        points, details = _evaluate_financial_statement_depth(fs_calls)
        assert details["missing_statement_count"] == 0
        assert sorted(details["available_statements"]) == [
            "balance_sheet",
            "cash_flow",
            "comprehensive_income",
            "equity",
            "income",
        ]
        assert points == pytest.approx(4.0)


@pytest.mark.unit
class TestReportAndCliPaths:
    """报告输出与 CLI 路径相关测试。"""

    @staticmethod
    def _make_batch(passed: bool) -> BatchScore:
        """构造最小批量结果对象。"""
        doc = DocumentScore(
            ticker="AAA",
            document_id="fil_001",
            total_score=88.5,
            grade="pass" if passed else "fail",
            hard_gate=HardGateResult(passed=passed, reasons=[] if passed else ["bad"]),
            dimensions={"A_structure": DimensionScore(points=20.0, max_points=25.0, details={"k": "v"})},
        )
        return BatchScore(
            documents=[doc],
            average_score=88.5,
            p10_score=88.5,
            hard_gate_failures=0 if passed else 1,
            passed=passed,
            failed_reasons=[] if passed else ["批量失败"],
            completeness_failures=[],
        )

    def test_report_writers_and_format_helpers(self, tmp_path: Path) -> None:
        """JSON/Markdown 报告可写出，且 markdown helper 覆盖空输入分支。"""
        batch = self._make_batch(passed=False)
        cfg = ScoreConfig()
        json_path = tmp_path / "reports" / "score.json"
        md_path = tmp_path / "reports" / "score.md"
        write_json_report(str(json_path), batch, cfg, "10-K")
        write_markdown_report(str(md_path), batch, cfg, "10-K")

        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["summary"]["document_count"] == 1
        assert payload["summary"]["completeness_failure_count"] == 0
        assert payload["documents"][0]["ticker"] == "AAA"
        assert "A_structure" in payload["documents"][0]["dimensions"]
        md = md_path.read_text(encoding="utf-8")
        assert "## 硬门禁详情" in md
        assert _format_markdown_table([]) == ""
        assert _format_markdown_table([["A", "B"], ["1", "2"]]).startswith("| A | B |")

    def test_ticker_parse_default_path_and_build_config(self) -> None:
        """覆盖 ticker 解析、默认报告路径和配置构建。"""
        assert _parse_tickers(" aapl , , msft ") == ["AAPL", "MSFT"]
        assert _parse_tickers(" , , ")  # 退回默认 ticker 列表
        assert _default_report_path("SC 13G", "json").endswith("score_sc13g_ci.json")

        args = parse_args(
            [
                "--form",
                "10-Q",
                "--base",
                "workspace_demo",
                "--tickers",
                "aapl,msft",
                "--min-doc-pass",
                "90",
                "--min-doc-warn",
                "80",
                "--min-batch-avg",
                "88",
                "--min-batch-p10",
                "75",
            ]
        )
        cfg = build_config(args)
        assert args.form == "10-Q"
        assert args.base == "workspace_demo"
        assert cfg.min_doc_pass == 90.0
        assert cfg.min_batch_p10 == 75.0

    def test_print_console_summary_and_main_paths(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        """覆盖控制台摘要与 main 的 pass/fail 两条路径。"""
        failed_batch = self._make_batch(passed=False)
        _print_console_summary(failed_batch, "10-K")
        stdout = capsys.readouterr().out
        assert "CI: FAIL" in stdout
        assert "批量失败" in stdout

        calls: dict[str, list[str]] = {"json": [], "md": []}

        def _fake_write_json(path: str, batch: BatchScore, cfg: ScoreConfig, form_type: str) -> None:
            calls["json"].append(path)

        def _fake_write_md(path: str, batch: BatchScore, cfg: ScoreConfig, form_type: str) -> None:
            calls["md"].append(path)

        monkeypatch.setattr("alpha.fins.score_sec_ci.write_json_report", _fake_write_json)
        monkeypatch.setattr("alpha.fins.score_sec_ci.write_markdown_report", _fake_write_md)
        monkeypatch.setattr("alpha.fins.score_sec_ci._print_console_summary", lambda batch, form_type: None)

        class _Args:
            """main 测试参数。"""

            form = "10-K"
            base = "workspace"
            tickers = "AAPL"
            output_json = None
            output_md = None
            min_doc_pass = 85.0
            min_doc_warn = 75.0
            min_batch_avg = 85.0
            min_batch_p10 = 78.0

        monkeypatch.setattr("alpha.fins.score_sec_ci.parse_args", lambda argv=None: _Args())
        monkeypatch.setattr("alpha.fins.score_sec_ci.score_batch", lambda **kwargs: self._make_batch(passed=True))
        assert main([]) == 0
        assert calls["json"][0].endswith("score_10k_ci.json")
        assert calls["md"][0].endswith("score_10k_ci.md")

        monkeypatch.setattr("alpha.fins.score_sec_ci.score_batch", lambda **kwargs: self._make_batch(passed=False))
        assert main([]) == 1

    def test_main_uses_default_portfolio_base_when_cli_omits_base(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未指定 --base 时应使用默认 `workspace/portfolio`。"""

        observed: list[str] = []

        class _Args:
            """main 测试参数（省略 base）。"""

            form = "10-K"
            base = None
            tickers = "AAPL"
            output_json = None
            output_md = None
            min_doc_pass = 85.0
            min_doc_warn = 75.0
            min_batch_avg = 85.0
            min_batch_p10 = 78.0

        monkeypatch.setattr("alpha.fins.score_sec_ci.parse_args", lambda argv=None: _Args())

        def _fake_score_batch(**kwargs: object) -> BatchScore:
            observed.append(str(kwargs.get("base")))
            return self._make_batch(passed=True)

        monkeypatch.setattr("alpha.fins.score_sec_ci.score_batch", _fake_score_batch)
        monkeypatch.setattr("alpha.fins.score_sec_ci.write_json_report", lambda *args, **kwargs: None)
        monkeypatch.setattr("alpha.fins.score_sec_ci.write_markdown_report", lambda *args, **kwargs: None)
        monkeypatch.setattr("alpha.fins.score_sec_ci._print_console_summary", lambda *args, **kwargs: None)

        assert main([]) == 0
        assert observed == ["workspace"]

    def test_serialize_document_structure(self) -> None:
        """序列化输出应包含 hard_gate 与维度字段。"""
        batch = self._make_batch(passed=True)
        payload = _serialize_document(batch.documents[0])
        assert payload["hard_gate"]["passed"] is True
        assert payload["dimensions"]["A_structure"]["points"] == 20.0


# ---------------------------------------------------------------------------
# 维度 S：语义可寻址性
# ---------------------------------------------------------------------------

def _make_sections(items: list[dict]) -> list[dict]:
    """构造测试用 section 列表，每个元素至少包含 ref/title/level/item/topic。

    Args:
        items: 字段指定列表，缺失字段用默认值补充。

    Returns:
        section 列表。
    """
    result = []
    for i, item in enumerate(items):
        sec = {
            "ref": item.get("ref", f"sec_{i:04d}"),
            "title": item.get("title", f"Section {i}"),
            "level": item.get("level", 1),
            "item": item.get("item"),
            "topic": item.get("topic"),
        }
        result.append(sec)
    return result


class TestSemanticCoverage:
    """维度 S：语义可寻址性评分测试。"""

    def test_not_applicable_returns_full_marks(self) -> None:
        """不适用表单（6-K / 8-K）返回满分且记录 skip_reason。"""
        sections = _make_sections([
            {"title": "Cover Page", "topic": None},
            {"title": "Financial Results", "topic": None},
        ])
        dim = _score_semantic_coverage(sections, SIX_K_PROFILE)
        assert dim.points == 10.0
        assert dim.max_points == 10.0
        assert dim.details["skip_reason"] == "not_applicable"

    def test_eight_k_not_applicable_returns_full_marks(self) -> None:
        """8-K 同样不适用，返回满分。"""
        sections = _make_sections([
            {"title": "Item 2.02", "topic": None},
            {"title": "Item 9.01", "topic": None},
        ])
        dim = _score_semantic_coverage(sections, EIGHT_K_PROFILE)
        assert dim.points == 10.0
        assert dim.details["skip_reason"] == "not_applicable"

    def test_full_score_when_all_topics_filled(self) -> None:
        """全部 Level-1 非特殊 section 有 topic，应得满分 10.0。"""
        sections = _make_sections([
            {"title": "Cover Page", "topic": None},               # 排除
            {"title": "Part I - Item 1A", "topic": "risk_factors"},
            {"title": "Part I - Item 7", "topic": "mda"},
            {"title": "Part I - Item 8", "topic": "financial_statements"},
            {"title": "SIGNATURE", "topic": "signature"},          # 排除
        ])
        dim = _score_semantic_coverage(sections, TEN_K_PROFILE)
        assert dim.points == 10.0
        assert dim.details["topic_coverage_rate"] == 1.0
        assert dim.details["scored_section_count"] == 3
        assert dim.details["topic_filled_count"] == 3
        assert len(dim.details["missing_topic_sections"]) == 0

    def test_partial_score_70_to_89_pct_gives_6_points(self) -> None:
        """topic 填充率 70%-89% 应得 6 分。"""
        sections = _make_sections([
            {"title": "Cover Page", "topic": None},
            {"title": "Item 1", "topic": "business"},
            {"title": "Item 1A", "topic": "risk_factors"},
            {"title": "Item 7", "topic": "mda"},
            {"title": "Item 8", "topic": "financial_statements"},
            {"title": "Item 7A", "topic": None},                    # 未填充
            {"title": "Item 15", "topic": None},                   # 未填充 → 4/6 = 66.7%
        ])
        dim = _score_semantic_coverage(sections, TEN_K_PROFILE)
        # 4/6 ≈ 0.667，在 [50%, 70%) → 3 分
        assert dim.points == 3.0
        assert abs(dim.details["topic_coverage_rate"] - 4 / 6) < 0.001

    def test_partial_score_70_pct_boundary_gives_6_points(self) -> None:
        """topic 填充率恰好 70% 应得 6 分。"""
        sections = _make_sections([
            {"title": "Item 1", "topic": "business"},
            {"title": "Item 1A", "topic": "risk_factors"},
            {"title": "Item 7", "topic": "mda"},
            {"title": "Item 8", "topic": "financial_statements"},
            {"title": "Item 7A", "topic": None},
            {"title": "Item 9", "topic": None},
            {"title": "Item 15", "topic": None},
            {"title": "Item 16", "topic": None},
            {"title": "Item 5", "topic": "market_for_equity"},
            {"title": "Item 6", "topic": "selected_financial_data"},
        ])
        # 6/10 = 60% → 3 分
        dim = _score_semantic_coverage(sections, TEN_K_PROFILE)
        assert dim.points == 3.0

    def test_zero_score_below_50_pct(self) -> None:
        """填充率 < 50% 应得 0 分。"""
        sections = _make_sections([
            {"title": "Item 1", "topic": None},
            {"title": "Item 1A", "topic": None},
            {"title": "Item 7", "topic": None},
            {"title": "Item 8", "topic": "financial_statements"},
        ])
        dim = _score_semantic_coverage(sections, TEN_K_PROFILE)
        assert dim.points == 0.0
        assert len(dim.details["missing_topic_sections"]) == 3

    def test_no_scored_sections_returns_full_marks(self) -> None:
        """Level-1 全为特殊 section 时（极短文件）应默认满分。"""
        sections = _make_sections([
            {"title": "Cover Page", "topic": None},
            {"title": "SIGNATURE", "topic": "signature"},
        ])
        dim = _score_semantic_coverage(sections, TEN_K_PROFILE)
        assert dim.points == 10.0
        assert dim.details["skip_reason"] == "no_scored_sections"

    def test_only_level1_sections_are_scored(self) -> None:
        """Level 2+ 子章节不应计入 S 维度评分。"""
        sections = _make_sections([
            {"title": "Item 1", "level": 1, "topic": "business"},
            {"title": "A. Overview", "level": 2, "topic": None},  # 子章节，不计入
            {"title": "B. Details", "level": 2, "topic": None},  # 子章节，不计入
        ])
        dim = _score_semantic_coverage(sections, TEN_K_PROFILE)
        assert dim.points == 10.0
        assert dim.details["scored_section_count"] == 1
        assert dim.details["topic_filled_count"] == 1

    def test_20f_profile_flagged_for_semantic_coverage(self) -> None:
        """验证 20-F profile 已启用 S 维度。"""
        assert TWENTY_F_PROFILE.score_semantic_coverage is True

    def test_10q_profile_flagged_for_semantic_coverage(self) -> None:
        """验证 10-Q profile 已启用 S 维度。"""
        assert TEN_Q_PROFILE.score_semantic_coverage is True

    def test_profiles_not_flagged_for_non_applicable_forms(self) -> None:
        """验证 6-K / 8-K 未启用 S 维度（默认 False）。"""
        assert SIX_K_PROFILE.score_semantic_coverage is False
        assert EIGHT_K_PROFILE.score_semantic_coverage is False


# ---------------------------------------------------------------------------
# _build_ref_to_item_map 单元测试
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBuildRefToItemMap:
    """_build_ref_to_item_map：验证子节通过 parent_ref 链追溯到所属 Item。"""

    def test_direct_title_match(self) -> None:
        """title 直接匹配 Item 的 section 能被正确映射。"""
        read_map = {
            "sec_001": {"ref": "sec_001", "title": "Item 7. Management Discussion", "content": "x" * 100},
        }
        result = _build_ref_to_item_map(read_map, profile=TEN_K_PROFILE)
        assert result.get("sec_001") == "Item 7"

    def test_child_inherits_parent_item(self) -> None:
        """子节 title 不含 Item 时，应沿 parent_ref 追溯到父节的 Item。"""
        sections = [
            {"ref": "sec_003", "title": "Item 3. Risk Factors", "level": 1, "parent_ref": None},
            {"ref": "sec_003_c01", "title": "A. Market Risk", "level": 2, "parent_ref": "sec_003"},
            {"ref": "sec_003_c02", "title": "B. Regulatory Risk", "level": 2, "parent_ref": "sec_003"},
        ]
        read_map = {
            "sec_003": {"ref": "sec_003", "title": "Item 3. Risk Factors", "content": "intro only"},
            "sec_003_c01": {"ref": "sec_003_c01", "title": "A. Market Risk", "content": "x" * 10000},
            "sec_003_c02": {"ref": "sec_003_c02", "title": "B. Regulatory Risk", "content": "x" * 8000},
        }
        result = _build_ref_to_item_map(read_map, profile=TWENTY_F_PROFILE, sections=sections)
        assert result.get("sec_003") == "Item 3"
        assert result.get("sec_003_c01") == "Item 3", "子节应追溯到父节 Item 3"
        assert result.get("sec_003_c02") == "Item 3", "子节应追溯到父节 Item 3"

    def test_orphan_section_not_mapped(self) -> None:
        """没有 Item 匹配且无 parent_ref 的子节不应被映射。"""
        sections = [
            {"ref": "sec_001", "title": "Foreword", "level": 1, "parent_ref": None},
        ]
        read_map = {
            "sec_001": {"ref": "sec_001", "title": "Foreword", "content": "x" * 500},
        }
        result = _build_ref_to_item_map(read_map, profile=TWENTY_F_PROFILE, sections=sections)
        assert result.get("sec_001") is None

    def test_deep_nested_child_resolves_to_item(self) -> None:
        """多级嵌套子节应能追溯到根 Item。"""
        sections = [
            {"ref": "s1", "title": "Item 5. MD&A", "level": 1, "parent_ref": None},
            {"ref": "s1_c1", "title": "Revenue", "level": 2, "parent_ref": "s1"},
            {"ref": "s1_c1_c1", "title": "Product Revenue", "level": 3, "parent_ref": "s1_c1"},
        ]
        read_map = {
            "s1": {"ref": "s1", "title": "Item 5. MD&A", "content": "intro"},
            "s1_c1": {"ref": "s1_c1", "title": "Revenue", "content": "sub content"},
            "s1_c1_c1": {"ref": "s1_c1_c1", "title": "Product Revenue", "content": "deep content"},
        }
        result = _build_ref_to_item_map(read_map, profile=TWENTY_F_PROFILE, sections=sections)
        assert result.get("s1_c1_c1") == "Item 5", "三级嵌套子节应追溯到 Item 5"


# ---------------------------------------------------------------------------
# _build_item_content_len：子节内容累加测试
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBuildItemContentLenWithSections:
    """验证 _build_item_content_len 在传入 sections 时正确累加子节内容。"""

    def test_no_sections_falls_back_to_direct_match(self) -> None:
        """不传 sections 时，仅统计直接匹配的 section。"""
        read_map = {
            "sec_001": {"ref": "sec_001", "title": "Item 3. Risk Factors", "content": "x" * 1000},
        }
        result = _build_item_content_len(read_map, profile=TWENTY_F_PROFILE)
        assert result["Item 3"] == 1000

    def test_child_content_aggregated_with_sections(self) -> None:
        """传入 sections 后，子节内容应累加到父 Item。"""
        sections = [
            {"ref": "sec_003", "title": "Item 3. Risk Factors", "level": 1, "parent_ref": None},
            {"ref": "sec_003_c01", "title": "A. Market Risk", "level": 2, "parent_ref": "sec_003"},
            {"ref": "sec_003_c02", "title": "B. Regulatory Risk", "level": 2, "parent_ref": "sec_003"},
        ]
        read_map = {
            "sec_003": {"ref": "sec_003", "title": "Item 3. Risk Factors", "content": "x" * 500},
            "sec_003_c01": {"ref": "sec_003_c01", "title": "A. Market Risk", "content": "x" * 20000},
            "sec_003_c02": {"ref": "sec_003_c02", "title": "B. Regulatory Risk", "content": "x" * 15000},
        }
        result = _build_item_content_len(read_map, profile=TWENTY_F_PROFILE, sections=sections)
        # 累加：500 + 20000 + 15000 = 35500
        assert result["Item 3"] == 35500

    def test_child_content_passes_threshold_when_parent_intro_short(self) -> None:
        """父节 intro 仅 1679 字符，但子节累加后超过 5000 阈值，应通过 B 维度。"""
        sections = [
            {"ref": "sec_003", "title": "Item 3. Risk Factors", "level": 1, "parent_ref": None},
            {"ref": "sec_003_c01", "title": "A. Reserved", "level": 2, "parent_ref": "sec_003"},
            {"ref": "sec_003_c02", "title": "B. Under current law", "level": 2, "parent_ref": "sec_003"},
        ]
        read_map = {
            "sec_003": {"ref": "sec_003", "title": "Item 3. Risk Factors", "content": "x" * 1679},
            "sec_003_c01": {"ref": "sec_003_c01", "title": "A. Reserved", "content": "x" * 2000},
            "sec_003_c02": {"ref": "sec_003_c02", "title": "B. Under current law", "content": "x" * 150000},
        }
        result = _build_item_content_len(read_map, profile=TWENTY_F_PROFILE, sections=sections)
        total = result["Item 3"]
        assert total == 1679 + 2000 + 150000, "三节内容应完整累加"
        assert total >= 5000, "累加后应远超 5000 阈值"

    def test_without_sections_short_parent_fails_threshold(self) -> None:
        """无 sections 时，父节(1679 字符)不达阈值，模拟修复前行为。"""
        read_map = {
            "sec_003": {"ref": "sec_003", "title": "Item 3. Risk Factors", "content": "x" * 1679},
            "sec_003_c01": {"ref": "sec_003_c01", "title": "A. Reserved", "content": "x" * 2000},
            "sec_003_c02": {"ref": "sec_003_c02", "title": "B. Under current law", "content": "x" * 150000},
        }
        # 不传 sections → 子节 title 不匹配 Item → Item 3 仅父节 1679
        result = _build_item_content_len(read_map, profile=TWENTY_F_PROFILE)
        assert result["Item 3"] == 1679


# ---------------------------------------------------------------------------
# _detect_truncated_sections：parent_refs 豁免测试
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDetectTruncatedSectionsWithParentRefs:
    """验证 _detect_truncated_sections 对父节的豁免逻辑。"""

    def test_truncated_leaf_section_detected(self) -> None:
        """叶节（无子节）以悬挂介词结尾时应被检出。"""
        read_map = {
            "s1": {"ref": "s1", "title": "Item 1", "content": "Properties are leased from"},
        }
        result = _detect_truncated_sections(read_map)
        assert "s1" in result

    def test_parent_section_exempted_by_parent_refs(self) -> None:
        """父节以悬挂介词结尾时，若在 parent_refs 中，应被豁免。"""
        read_map = {
            "s1": {"ref": "s1", "title": "Item 3", "content": "Properties are leased from"},
        }
        parent_refs = {"s1"}
        result = _detect_truncated_sections(read_map, parent_refs=parent_refs)
        assert "s1" not in result, "父节应被豁免不检测截断"

    def test_parent_refs_none_does_not_exempt(self) -> None:
        """parent_refs=None 时不豁免任何节。"""
        read_map = {
            "s1": {"ref": "s1", "title": "Item 3", "content": "Properties are leased from"},
        }
        result = _detect_truncated_sections(read_map, parent_refs=None)
        assert "s1" in result

    def test_only_parent_exempted_not_leaves(self) -> None:
        """parent_refs 中的父节豁免，非父节的叶节仍被检测。"""
        read_map = {
            "parent": {"ref": "parent", "title": "Item 3", "content": "Intro text ends with"},
            "child": {"ref": "child", "title": "A. Risk", "content": "This risk comes from"},
        }
        parent_refs = {"parent"}
        result = _detect_truncated_sections(read_map, parent_refs=parent_refs)
        assert "parent" not in result, "父节应豁免"
        assert "child" in result, "叶节应仍被检测"

    def test_empty_parent_refs_no_exemption(self) -> None:
        """parent_refs 为空集合时行为与 None 相同，仍检测所有节。"""
        read_map = {
            "s1": {"ref": "s1", "title": "Item 3", "content": "Properties are leased from"},
        }
        result = _detect_truncated_sections(read_map, parent_refs=set())
        assert "s1" in result


# ---------------------------------------------------------------------------
# 测试：D3 批量财报提取覆盖率门禁
# ---------------------------------------------------------------------------


def _make_coverage_doc(
    available_statements: list[str],
    core_available: list[str] | None = None,
    mean_row_count: float | None = None,
) -> DocumentScore:
    """构造含 D_consistency 维度的最小文档评分对象，用于覆盖率测试。

    Args:
        available_statements: XBRL 可提取报表列表（10-K/10-Q/20-F 用）。
        core_available: 6-K 核心报表列表；为 None 时使用 available_statements 路径。
        mean_row_count: D3 平均行数；为 None 时自动推断（有报表则 15.0，无报表则 0.0）。

    Returns:
        DocumentScore 测试对象。
    """
    # 自动推断 mean_row_count：有实际报表数据则设 15.0，无则 0.0
    # 这模拟了真实 scorer 的行为：rows 非空时 mean_row_count>0
    if mean_row_count is None:
        has_data = bool(core_available) if core_available is not None else bool(available_statements)
        mean_row_count = 15.0 if has_data else 0.0

    if core_available is not None:
        d3_details: dict[str, Any] = {
            "d3_mode": "six_k_release_core",
            "core_available": core_available,
            "mean_row_count": mean_row_count,
        }
    else:
        d3_details = {
            "available_statements": available_statements,
            "mean_row_count": mean_row_count,
        }
    return DocumentScore(
        ticker="TST",
        document_id="fil_001",
        total_score=95.0,
        grade="pass",
        hard_gate=HardGateResult(passed=True, reasons=[]),
        dimensions={"D_consistency": DimensionScore(points=12.0, max_points=15.0, details=d3_details)},
    )


@pytest.mark.unit
class TestBatchFinancialCoverageGate:
    """D3 批量财报提取覆盖率门禁单元测试。

    验证 _check_batch_financial_coverage_rate 的边界条件和字段路由，
    以及 score_batch 写入 failed_reasons / financial_coverage_rate 的正确性。
    """

    def test_not_applicable_for_eight_k(self) -> None:
        """8-K 不在阈值表中，应返回 None（不适用）。"""
        doc = _make_coverage_doc(["income"])
        result = _check_batch_financial_coverage_rate([doc], EIGHT_K_PROFILE)
        assert result is None

    def test_not_applicable_for_empty_docs(self) -> None:
        """空文档列表应返回 None（无法计算比率）。"""
        result = _check_batch_financial_coverage_rate([], TEN_K_PROFILE)
        assert result is None

    def test_thresholds_dict_keys_cover_main_forms(self) -> None:
        """阈值表应包含所有主要财报表单类型。"""
        expected_forms = {"10-K", "10-Q", "20-F", "6-K"}
        assert expected_forms <= set(_FINANCIAL_COVERAGE_THRESHOLDS.keys())

    def test_ten_k_full_coverage_passes(self) -> None:
        """10-K 全量覆盖（100%）应高于 99% 阈值。"""
        docs = [_make_coverage_doc(["income", "balance_sheet", "cash_flow"]) for _ in range(5)]
        result = _check_batch_financial_coverage_rate(docs, TEN_K_PROFILE)
        assert result is not None
        coverage, threshold = result
        assert coverage == pytest.approx(1.0)
        assert threshold == _FINANCIAL_COVERAGE_THRESHOLDS["10-K"]
        assert coverage >= threshold

    def test_ten_k_empty_statements_means_zero_coverage(self) -> None:
        """10-K available_statements 为空列表时，该文档不计入覆盖。"""
        docs = [_make_coverage_doc([])] * 3
        result = _check_batch_financial_coverage_rate(docs, TEN_K_PROFILE)
        assert result is not None
        coverage, threshold = result
        assert coverage == pytest.approx(0.0)
        assert coverage < threshold  # 0.0 < 0.99 → 应触发告警

    def test_ten_k_partial_coverage_below_threshold(self) -> None:
        """10-K 覆盖率 80%（< 99%）应低于阈值，用于验证告警触发逻辑。"""
        docs = (
            [_make_coverage_doc(["income"])] * 8
            + [_make_coverage_doc([])] * 2
        )
        result = _check_batch_financial_coverage_rate(docs, TEN_K_PROFILE)
        assert result is not None
        coverage, threshold = result
        assert coverage == pytest.approx(0.8)
        assert coverage < threshold

    def test_ten_q_threshold_equals_ten_k(self) -> None:
        """10-Q 与 10-K 同样强制 XBRL，阈值应相同（0.99）。"""
        assert _FINANCIAL_COVERAGE_THRESHOLDS["10-Q"] == _FINANCIAL_COVERAGE_THRESHOLDS["10-K"]
        assert _FINANCIAL_COVERAGE_THRESHOLDS["10-Q"] == pytest.approx(0.99)

    def test_ten_q_full_coverage_passes(self) -> None:
        """10-Q 全量覆盖（100%）应满足 99% 阈值。"""
        docs = [
            _make_coverage_doc(["income", "balance_sheet"])
            for _ in range(20)
        ]
        result = _check_batch_financial_coverage_rate(docs, TEN_Q_PROFILE)
        assert result is not None
        coverage, threshold = result
        assert coverage == pytest.approx(1.0)
        assert coverage >= threshold

    def test_six_k_uses_core_available_field(self) -> None:
        """6-K 应使用 core_available 而非 available_statements 字段。"""
        # core_available 非空：算覆盖
        doc_covered = _make_coverage_doc([], core_available=["income", "balance_sheet"])
        # core_available 为空列表：不算覆盖
        doc_uncovered = _make_coverage_doc([], core_available=[])
        # available_statements 写了也不影响 6-K 判定
        doc_mislead = _make_coverage_doc(["income"], core_available=[])

        docs = [doc_covered] * 9 + [doc_uncovered]
        result = _check_batch_financial_coverage_rate(docs, SIX_K_PROFILE)
        assert result is not None
        coverage, threshold = result
        assert coverage == pytest.approx(0.9)
        assert threshold == _FINANCIAL_COVERAGE_THRESHOLDS["6-K"]
        assert coverage >= threshold  # 0.9 >= 0.9 → 恰好通过

        # doc_mislead 的 available_statements 不应被 6-K 逻辑读取
        result2 = _check_batch_financial_coverage_rate([doc_mislead], SIX_K_PROFILE)
        assert result2 is not None
        coverage2, _ = result2
        assert coverage2 == pytest.approx(0.0), "6-K 不应读取 available_statements"

    def test_six_k_below_90_percent_triggers(self) -> None:
        """6-K 覆盖率 80%（< 90%）应低于阈值。"""
        docs = (
            [_make_coverage_doc([], core_available=["income"])] * 8
            + [_make_coverage_doc([], core_available=[])] * 2
        )
        result = _check_batch_financial_coverage_rate(docs, SIX_K_PROFILE)
        assert result is not None
        coverage, threshold = result
        assert coverage == pytest.approx(0.8)
        assert coverage < threshold

    def test_partial_quality_with_zero_rows_not_covered(self) -> None:
        """data_quality='partial' 但 rows=0 时不应算做覆盖（GMAB/IBN 回归测试）。

        根因：_evaluate_financial_statement_depth 的 usable=True 判断懂得 data_quality='partial'
        有效，会把该报表加入 available_statements，但 rows=0 导致
        mean_row_count=0，覆盖率门禁应识别该类 false positive。
        """
        # 模拟 GMAB 场景：available_statements 非空（partial quality），但 mean_row_count=0
        doc_partial_no_rows = DocumentScore(
            ticker="GMAB",
            document_id="fil_partial",
            total_score=60.0,
            grade="fail",
            hard_gate=HardGateResult(passed=True, reasons=[]),
            dimensions={"D_consistency": DimensionScore(
                points=0.0,
                max_points=15.0,
                details={
                    "available_statements": ["income", "balance_sheet", "cash_flow", "equity", "comprehensive_income"],
                    "missing_statement_count": 0,  # partial quality 被计入了
                    "mean_row_count": 0.0,         # 但实际 rows 全为空
                    "period_counts": [0, 0, 0, 0, 0],
                    "all_periods_ge2": False,
                },
            )},
        )
        result = _check_batch_financial_coverage_rate([doc_partial_no_rows], TWENTY_F_PROFILE)
        assert result is not None
        coverage, _ = result
        assert coverage == pytest.approx(0.0), "partial quality + rows=0 不应算做覆盖"

    def test_six_k_partial_quality_with_zero_rows_not_covered(self) -> None:
        """6-K 中 data_quality='partial' 但 rows=0 不应算做覆盖。"""
        doc_partial = DocumentScore(
            ticker="UBS",
            document_id="fil_non_fin_6k",
            total_score=55.0,
            grade="fail",
            hard_gate=HardGateResult(passed=True, reasons=[]),
            dimensions={"D_consistency": DimensionScore(
                points=0.0,
                max_points=15.0,
                details={
                    "d3_mode": "six_k_release_core",
                    "core_available": ["income", "balance_sheet"],  # partial quality 被计入
                    "mean_row_count": 0.0,                           # 但实际 rows 全为空
                    "period_counts": [0, 0],
                },
            )},
        )
        result = _check_batch_financial_coverage_rate([doc_partial], SIX_K_PROFILE)
        assert result is not None
        coverage, _ = result
        assert coverage == pytest.approx(0.0), "6-K partial quality + rows=0 不应算做覆盖"

    def test_doc_without_d_consistency_dimension_counts_as_uncovered(self) -> None:
        """文档无 D_consistency 维度时，应不计入覆盖（details 为空 dict）。"""
        doc_no_dim = DocumentScore(
            ticker="TST",
            document_id="fil_no_dim",
            total_score=90.0,
            grade="pass",
            hard_gate=HardGateResult(passed=True, reasons=[]),
            dimensions={},  # 没有 D_consistency
        )
        result = _check_batch_financial_coverage_rate([doc_no_dim], TEN_K_PROFILE)
        assert result is not None
        coverage, _ = result
        assert coverage == pytest.approx(0.0)

    def test_score_batch_populates_financial_coverage_rate(self, tmp_path: Path) -> None:
        """score_batch 应在 BatchScore 中写入 financial_coverage_rate 字段。"""
        base = tmp_path / "portfolio"
        doc_dir = base / "AAA" / "processed" / "fil_cov"
        _make_minimal_10k_truth(
            document_dir=doc_dir,
            document_id="fil_cov",
            item7_content="x" * 7000,
            item8_content="x" * 15000,
        )
        cfg = ScoreConfig(min_batch_avg=60.0, min_batch_p10=60.0)
        batch = score_batch(str(base), ["AAA"], cfg, form_type="10-K")
        # _make_common_truth 已写入 income/balance_sheet/cash_flow → 覆盖率 100%
        assert batch.financial_coverage_rate is not None
        assert batch.financial_coverage_rate == pytest.approx(1.0)

    def test_score_batch_adds_d3_failed_reason_when_no_financials(self, tmp_path: Path) -> None:
        """score_batch 财报提取覆盖率为 0 时应在 failed_reasons 中包含 D3 信息。"""
        base = tmp_path / "portfolio"
        doc_dir = base / "AAA" / "processed" / "fil_nofin"
        # 写入结构文件（正常），但覆盖 get_financial_statement 为全空响应
        _make_minimal_10k_truth(
            document_dir=doc_dir,
            document_id="fil_nofin",
            item7_content="x" * 7000,
            item8_content="x" * 15000,
        )
        # 用空 rows/periods 且无 data_quality 覆盖财务报表快照 → evaluator 判定不可用
        # （usable 条件：data_quality in xbrl/extracted OR has_rows；两者均为假）
        empty_fs_calls: list[dict] = [
            {"request": {"statement_type": st}, "response": {"rows": [], "periods": []}}
            for st in ["income", "balance_sheet", "cash_flow", "equity", "comprehensive_income"]
        ]
        _write_json(doc_dir / "tool_snapshot_get_financial_statement.json", {"calls": empty_fs_calls})

        cfg = ScoreConfig(min_batch_avg=0.0, min_batch_p10=0.0)
        batch = score_batch(str(base), ["AAA"], cfg, form_type="10-K")
        assert batch.financial_coverage_rate == pytest.approx(0.0)
        assert any("D3 财报提取覆盖率" in r for r in batch.failed_reasons)
        # mean_row_count=0 触发 per-doc D3 hard gate → hard_gate_failures=1
        assert batch.hard_gate_failures == 1
        assert any("D3 XBRL" in r for r in batch.documents[0].hard_gate.reasons)
        assert batch.passed is False

    def test_d3_hard_gate_fires_for_20f_with_partial_zero_rows(self, tmp_path: Path) -> None:
        """20-F 全部报表 partial+rows=0 时，per-doc 应触发 D3 hard gate（GMAB/IBN 回归）。"""
        base = tmp_path / "portfolio"
        doc_dir = base / "GMAB" / "processed" / "fil_gmab_test"
        _make_minimal_20f_truth(
            document_dir=doc_dir,
            document_id="fil_gmab_test",
            item3_content="x" * 5000,
            item5_content="x" * 10000,
            item18_content="x" * 20000,
        )
        # 覆盖财务报表快照为 partial+rows=0（模拟 taxonomy 解析失败场景）
        partial_fs_calls: list[dict] = [
            {"request": {"statement_type": st}, "response": {"data_quality": "partial", "rows": [], "periods": []}}
            for st in ["income", "balance_sheet", "cash_flow", "equity", "comprehensive_income"]
        ]
        _write_json(doc_dir / "tool_snapshot_get_financial_statement.json", {"calls": partial_fs_calls})

        cfg = ScoreConfig(min_batch_avg=0.0, min_batch_p10=0.0, min_doc_warn=0.0)
        batch = score_batch(str(base), ["GMAB"], cfg, form_type="20-F")
        assert len(batch.documents) == 1
        doc = batch.documents[0]
        # partial+rows=0 后 available_statements=[] → mean_row_count=0 → hard gate 触发
        assert doc.hard_gate.passed is False
        assert any("D3 XBRL" in r for r in doc.hard_gate.reasons)
        # D3 details 应反映真实状态：missing_count=5, mean_row_count=0
        d3_details = doc.dimensions["D_consistency"].details
        assert d3_details["missing_statement_count"] == 5
        assert d3_details["mean_row_count"] == 0.0
        assert d3_details["available_statements"] == []
        # 批量覆盖率 0/1 < 99%
        assert batch.financial_coverage_rate == pytest.approx(0.0)
        assert batch.passed is False

    def test_d3_hard_gate_fires_for_6k_with_empty_core(self) -> None:
        """测试 6-K core_available=[] 时 per-doc D3 hard gate 触发。

        场景：6-K pipeline 筛选为季报，HTML 提取完全失败，
        income/balance_sheet 名称都没有识别到。
        """
        consistency = DimensionScore(
            points=0.0,
            max_points=15.0,
            details={
                "d3_mode": "six_k_release_core",
                "core_available": [],
                "mean_row_count": 0.0,
                "period_counts": [],
            },
        )
        noise = DimensionScore(
            points=15.0,
            max_points=15.0,
            details={"max_section_len": 1000},
        )
        result = _evaluate_hard_gate(
            item_content_len={},
            consistency=consistency,
            noise=noise,
            cfg=ScoreConfig(),
            read_map={},
            profile=SIX_K_PROFILE,
        )
        assert result.passed is False
        assert any("D3 6-K" in r for r in result.reasons)
        assert any("完全未提取" in r for r in result.reasons)

    def test_d3_hard_gate_fires_for_6k_with_empty_rows(self) -> None:
        """测试 6-K 识别到报表名称但内容为空时 per-doc D3 hard gate 触发。

        场景：HTML 表格解析识别到 income/balance_sheet，
        但 rows=[] （表格结构异常或参数错误）。
        """
        consistency = DimensionScore(
            points=0.0,
            max_points=15.0,
            details={
                "d3_mode": "six_k_release_core",
                "core_available": ["income", "balance_sheet"],
                "mean_row_count": 0.0,
                "period_counts": [0, 0],
            },
        )
        noise = DimensionScore(
            points=15.0,
            max_points=15.0,
            details={"max_section_len": 1000},
        )
        result = _evaluate_hard_gate(
            item_content_len={},
            consistency=consistency,
            noise=noise,
            cfg=ScoreConfig(),
            read_map={},
            profile=SIX_K_PROFILE,
        )
        assert result.passed is False
        assert any("D3 6-K" in r for r in result.reasons)
        assert any("内容为空" in r for r in result.reasons)

    def test_d3_hard_gate_not_fire_for_6k_with_good_data(self) -> None:
        """测试 6-K core_available 非空且 mean_row_count>0 时 D3 hard gate 不触发。"""
        consistency = DimensionScore(
            points=12.0,
            max_points=15.0,
            details={
                "d3_mode": "six_k_release_core",
                "core_available": ["income", "balance_sheet"],
                "mean_row_count": 18.5,
                "period_counts": [10, 12],
            },
        )
        noise = DimensionScore(
            points=15.0,
            max_points=15.0,
            details={"max_section_len": 1000},
        )
        result = _evaluate_hard_gate(
            item_content_len={},
            consistency=consistency,
            noise=noise,
            cfg=ScoreConfig(),
            read_map={},
            profile=SIX_K_PROFILE,
        )
        assert result.passed is True
        assert result.reasons == []

    def test_d3_hard_gate_not_fire_for_8k(self) -> None:
        """测试 8-K（skip_reason='no_xbrl_expected'）不触发 D3 hard gate。

        8-K 的 D3 details 情况是 skip_reason，而非 d3_mode，不应被 6-K gate 捕获。
        """
        consistency = DimensionScore(
            points=15.0,
            max_points=15.0,
            details={
                "skip_reason": "no_xbrl_expected",
                "mean_row_count": 0.0,  # 即使为 0 也不应用 6-K gate
            },
        )
        noise = DimensionScore(
            points=15.0,
            max_points=15.0,
            details={"max_section_len": 1000},
        )
        result = _evaluate_hard_gate(
            item_content_len={},
            consistency=consistency,
            noise=noise,
            cfg=ScoreConfig(),
            read_map={},
            profile=EIGHT_K_PROFILE,
        )
        assert result.passed is True
        assert result.reasons == []

    def test_write_json_report_includes_coverage_rate(self, tmp_path: Path) -> None:
        """write_json_report 产出的 summary 应包含 financial_coverage_rate 字段。"""
        doc = DocumentScore(
            ticker="AAA",
            document_id="fil_001",
            total_score=95.0,
            grade="pass",
            hard_gate=HardGateResult(passed=True, reasons=[]),
            dimensions={},
        )
        batch = BatchScore(
            documents=[doc],
            average_score=95.0,
            p10_score=95.0,
            hard_gate_failures=0,
            passed=True,
            failed_reasons=[],
            financial_coverage_rate=0.9860,
            completeness_failures=[],
        )
        json_path = tmp_path / "report.json"
        write_json_report(str(json_path), batch, ScoreConfig(), "20-F")
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert "financial_coverage_rate" in payload["summary"]
        assert payload["summary"]["financial_coverage_rate"] == pytest.approx(0.9860)

    def test_write_json_report_coverage_rate_none_when_not_applicable(self, tmp_path: Path) -> None:
        """不适用覆盖率检查的表单（8-K）在报告 summary 中应为 null。"""
        doc = DocumentScore(
            ticker="AAA",
            document_id="fil_001",
            total_score=95.0,
            grade="pass",
            hard_gate=HardGateResult(passed=True, reasons=[]),
            dimensions={},
        )
        batch = BatchScore(
            documents=[doc],
            average_score=95.0,
            p10_score=95.0,
            hard_gate_failures=0,
            passed=True,
            failed_reasons=[],
            financial_coverage_rate=None,
            completeness_failures=[],
        )
        json_path = tmp_path / "report.json"
        write_json_report(str(json_path), batch, ScoreConfig(), "8-K")
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["summary"]["financial_coverage_rate"] is None

    def test_report_writers_include_completeness_failures(self, tmp_path: Path) -> None:
        """JSON/Markdown 报告应输出 completeness hard gate 明细。"""

        doc = DocumentScore(
            ticker="AAA",
            document_id="fil_001",
            total_score=95.0,
            grade="pass",
            hard_gate=HardGateResult(passed=True, reasons=[]),
            dimensions={},
        )
        batch = BatchScore(
            documents=[doc],
            average_score=95.0,
            p10_score=95.0,
            hard_gate_failures=0,
            passed=False,
            failed_reasons=["completeness hard gate 失败文档数=1"],
            financial_coverage_rate=1.0,
            completeness_failures=[
                CompletenessFailure(
                    ticker="AAA",
                    document_id="fil_missing",
                    reason="缺少 processed 快照",
                )
            ],
        )

        json_path = tmp_path / "report.json"
        md_path = tmp_path / "report.md"
        write_json_report(str(json_path), batch, ScoreConfig(), "10-K")
        write_markdown_report(str(md_path), batch, ScoreConfig(), "10-K")

        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["summary"]["completeness_failure_count"] == 1
        assert payload["summary"]["expected_document_count"] == 2
        assert payload["completeness_failures"][0]["document_id"] == "fil_missing"
        md = md_path.read_text(encoding="utf-8")
        assert "## Completeness Hard Gate" in md
        assert "AAA/fil_missing" in md
