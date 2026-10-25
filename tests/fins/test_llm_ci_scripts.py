"""`utils/llm_ci_*` 脚本的轻量回归测试。"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESS_SCRIPT_PATH = REPO_ROOT / "utils" / "llm_ci_process.py"
SCORE_SCRIPT_PATH = REPO_ROOT / "utils" / "llm_ci_score.py"


def _load_module_from_path(name: str, path: Path) -> ModuleType:
    """按路径加载测试目标模块。

    Args:
        name: 模块名。
        path: 脚本路径。

    Returns:
        已加载模块对象。

    Raises:
        ImportError: 模块 spec 不存在时抛出。
    """

    spec = spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块: {path}")
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
def test_llm_ci_process_aggregate_document_ids_by_ticker_dedupes_and_preserves_order() -> None:
    """验证文档选择项会按 ticker 聚合并稳定去重。"""

    module = _load_module_from_path("workspace_tmp_llm_ci_process", PROCESS_SCRIPT_PATH)
    entries = [
        module.DocumentSelectorEntry(ticker="TSM", document_id="fil_2"),
        module.DocumentSelectorEntry(ticker="TSM", document_id="fil_1"),
        module.DocumentSelectorEntry(ticker="TSM", document_id="fil_2"),
        module.DocumentSelectorEntry(ticker="BILI", document_id="fil_a"),
    ]

    grouped = module._aggregate_document_ids_by_ticker(entries)

    assert grouped == {
        "BILI": ("fil_a",),
        "TSM": ("fil_2", "fil_1"),
    }


@pytest.mark.unit
def test_llm_ci_process_split_document_ids_for_job_uses_stable_chunks() -> None:
    """验证大批文档会按稳定顺序切成多个子批次。"""

    module = _load_module_from_path("workspace_tmp_llm_ci_process_split", PROCESS_SCRIPT_PATH)

    batches = module._split_document_ids_for_job(
        ("fil_1", "fil_2", "fil_3", "fil_4", "fil_5"),
        max_documents_per_job=2,
    )

    assert batches == (
        ("fil_1", "fil_2"),
        ("fil_3", "fil_4"),
        ("fil_5",),
    )


@pytest.mark.unit
def test_llm_ci_process_build_jobs_prefers_document_mapping() -> None:
    """验证存在文档映射时只按映射构造作业。"""

    module = _load_module_from_path("workspace_tmp_llm_ci_process_jobs", PROCESS_SCRIPT_PATH)

    jobs = module._build_jobs(
        tickers=["AAPL", "TSM"],
        document_ids_by_ticker={"TSM": ("fil_1", "fil_2")},
    )

    assert jobs == [module.ProcessJob(ticker="TSM", document_ids=("fil_1", "fil_2"), batch_index=1)]


@pytest.mark.unit
def test_llm_ci_process_build_jobs_splits_large_document_batches() -> None:
    """验证单个 ticker 的超大文档集合会拆成多个 process 作业。"""

    module = _load_module_from_path("workspace_tmp_llm_ci_process_large_jobs", PROCESS_SCRIPT_PATH)
    jobs = module._build_jobs(
        tickers=["TSM"],
        document_ids_by_ticker={"TSM": ("fil_1", "fil_2", "fil_3")},
        max_documents_per_job=2,
    )

    assert jobs == [
        module.ProcessJob(ticker="TSM", document_ids=("fil_1", "fil_2"), batch_index=1),
        module.ProcessJob(ticker="TSM", document_ids=("fil_3",), batch_index=2),
    ]


@pytest.mark.unit
def test_llm_ci_process_group_jobs_by_ticker_keeps_same_ticker_batches_serialized() -> None:
    """验证同一 ticker 的批次会被分到同一串行组内。"""

    module = _load_module_from_path("workspace_tmp_llm_ci_process_grouped_jobs", PROCESS_SCRIPT_PATH)
    jobs = [
        module.ProcessJob(ticker="NVS", document_ids=("fil_3",), batch_index=2),
        module.ProcessJob(ticker="AAPL", document_ids=("fil_a",), batch_index=1),
        module.ProcessJob(ticker="NVS", document_ids=("fil_1", "fil_2"), batch_index=1),
    ]

    grouped_jobs = module._group_jobs_by_ticker(jobs)

    assert grouped_jobs == (
        (module.ProcessJob(ticker="AAPL", document_ids=("fil_a",), batch_index=1),),
        (
            module.ProcessJob(ticker="NVS", document_ids=("fil_1", "fil_2"), batch_index=1),
            module.ProcessJob(ticker="NVS", document_ids=("fil_3",), batch_index=2),
        ),
    )


@pytest.mark.unit
def test_llm_ci_process_detects_failed_documents_from_cli_summary() -> None:
    """验证脚本会把 CLI 日志中的 failed filings 识别为真实失败。"""

    module = _load_module_from_path("workspace_tmp_llm_ci_process_failed_log", PROCESS_SCRIPT_PATH)
    log_text = (
        "全量处理结果\n"
        "- ticker: NVS\n"
        "失败的 filings:\n"
        "  - fil_0001370368-25-000004 | status=failed | reason=commit_batch failed\n"
    )

    assert module._count_reported_failed_documents(log_text) == 1

    result = module.ProcessRunResult(
        ticker="NVS",
        document_ids=("fil_0001370368-25-000004",),
        command=("python", "-m", "alpha.cli"),
        return_code=0,
        duration_seconds=1.0,
        timed_out=False,
        log_path="/tmp/NVS.log",
        batch_index=1,
        reported_failed_documents=1,
    )

    assert module._is_successful_result(result) is False


def test_llm_ci_score_resolve_forms_normalizes_amendment_suffix() -> None:
    """验证 `SC 13G/A` 会归一化为 `SC 13G`。"""

    module = _load_module_from_path("workspace_tmp_llm_ci_score_forms", SCORE_SCRIPT_PATH)

    forms = module._resolve_forms("SC 13G/A,20-F")

    assert forms == ["SC 13G", "20-F"]


@pytest.mark.unit
def test_llm_ci_score_build_form_summary_uses_probe_for_missing_documents() -> None:
    """验证 form 摘要会把未进 score JSON 的文档映射回探针原因。"""

    module = _load_module_from_path("workspace_tmp_llm_ci_score_summary", SCORE_SCRIPT_PATH)
    universe = [
        module.FilingUniverseDocument(ticker="TSM", document_id="fil_1", form_type="20-F"),
        module.FilingUniverseDocument(ticker="TSM", document_id="fil_2", form_type="20-F"),
    ]
    probe_results = [
        module.ProbeResult(
            ticker="TSM",
            document_id="fil_1",
            form_type="20-F",
            status=module.PROBE_READY,
            detail="可进入 score_sec_ci 评分",
        ),
        module.ProbeResult(
            ticker="TSM",
            document_id="fil_2",
            form_type="20-F",
            status=module.PROBE_MISSING_PROCESSED,
            detail="processed manifest 中不存在该文档",
        ),
    ]
    payload = module.LoadedScorePayload(
        summary=module.ScoreSummaryRecord(
            average_score=97.0,
            p10_score=97.0,
            hard_gate_failures=0,
            document_count=1,
        ),
        documents=(
            module.ScoreDocumentRecord(
                ticker="TSM",
                document_id="fil_1",
                total_score=97.0,
            ),
        ),
    )

    summary = module._build_form_summary(
        form_type="20-F",
        score_payload=payload,
        probe_results=probe_results,
        universe_documents=universe,
        return_code=0,
    )

    assert summary.missing_from_score_count == 1
    assert summary.missing_processed_count == 1
    assert summary.missing_from_score == (
        module.MissingDocumentGap(
            ticker="TSM",
            document_id="fil_2",
            status=module.PROBE_MISSING_PROCESSED,
            detail="processed manifest 中不存在该文档",
        ),
    )


@pytest.mark.unit
def test_llm_ci_score_build_overall_summary_aggregates_document_scores() -> None:
    """验证 overall 摘要按文档分数聚合而不是按 form 平均值二次平均。"""

    module = _load_module_from_path("workspace_tmp_llm_ci_score_overall", SCORE_SCRIPT_PATH)
    form_summaries = [
        module.FormSummary(
            form_type="20-F",
            avg=98.0,
            p10=98.0,
            hard_gate_failures=0,
            document_count=1,
            universe_document_count=2,
            missing_from_score_count=1,
            missing_processed_count=1,
            missing_snapshot_count=0,
            invalid_snapshot_count=0,
            score_return_code=0,
            missing_from_score=tuple(),
        ),
        module.FormSummary(
            form_type="10-K",
            avg=90.0,
            p10=88.0,
            hard_gate_failures=2,
            document_count=2,
            universe_document_count=2,
            missing_from_score_count=0,
            missing_processed_count=0,
            missing_snapshot_count=0,
            invalid_snapshot_count=0,
            score_return_code=1,
            missing_from_score=tuple(),
        ),
    ]
    payloads = [
        module.LoadedScorePayload(
            summary=None,
            documents=(
                module.ScoreDocumentRecord(ticker="TSM", document_id="fil_1", total_score=98.0),
            ),
        ),
        module.LoadedScorePayload(
            summary=None,
            documents=(
                module.ScoreDocumentRecord(ticker="AAPL", document_id="fil_a", total_score=92.0),
                module.ScoreDocumentRecord(ticker="AAPL", document_id="fil_b", total_score=88.0),
            ),
        ),
    ]

    summary = module._build_overall_summary(
        form_summaries=form_summaries,
        form_payloads=payloads,
    )

    assert summary.overall_avg == 92.67
    assert summary.overall_hard_gate_failures == 2
    assert summary.overall_document_count == 3
    assert summary.overall_universe_document_count == 4
    assert summary.overall_missing_from_score_count == 1
    assert summary.forms_included == ("20-F", "10-K")
