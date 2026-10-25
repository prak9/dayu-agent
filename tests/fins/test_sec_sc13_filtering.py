"""`sec_sc13_filtering` 真源边界测试。"""

from __future__ import annotations

import datetime as dt

from alpha.fins.downloaders.sec_downloader import Sc13PartyRoles
from alpha.fins.pipelines.sec_filing_collection import FilingRecord
from alpha.fins.pipelines.sec_sc13_filtering import (
    evaluate_sc13_direction,
    keep_latest_sc13_per_filer,
    should_warn_missing_sc13,
)


def _make_filing(
    *,
    form_type: str = "SC 13D",
    filing_date: str = "2025-01-15",
    accession_number: str = "0001234567-25-000001",
    filer_key: str | None = "005-12345",
) -> FilingRecord:
    """构造测试用 filing。"""

    return FilingRecord(
        form_type=form_type,
        filing_date=filing_date,
        report_date=None,
        accession_number=accession_number,
        primary_document="primary.htm",
        filer_key=filer_key,
    )


def test_evaluate_sc13_direction_requires_subject_match() -> None:
    """subject 不是目标 ticker 时必须过滤。"""

    result = evaluate_sc13_direction(
        module="test",
        filing=_make_filing(),
        roles=Sc13PartyRoles(filed_by_cik="111111", subject_cik="222222"),
        target_cik="320193",
    )

    assert result is False


def test_evaluate_sc13_direction_rejects_self_holding() -> None:
    """ticker 自己持股别人时必须过滤。"""

    result = evaluate_sc13_direction(
        module="test",
        filing=_make_filing(),
        roles=Sc13PartyRoles(filed_by_cik="320193", subject_cik="320193"),
        target_cik="320193",
    )

    assert result is False


def test_evaluate_sc13_direction_keeps_external_holder() -> None:
    """别人持股我时应保留。"""

    result = evaluate_sc13_direction(
        module="test",
        filing=_make_filing(),
        roles=Sc13PartyRoles(filed_by_cik="111111", subject_cik="320193"),
        target_cik="320193",
    )

    assert result is True


def test_keep_latest_sc13_per_filer_prefers_latest_same_filer() -> None:
    """同一 filer 的 SC13 仅保留最新一份。"""

    filings = [
        _make_filing(filing_date="2025-01-15", accession_number="0001234567-25-000001"),
        _make_filing(filing_date="2025-03-01", accession_number="0001234567-25-000002"),
        _make_filing(form_type="10-K", accession_number="0001234567-25-000100", filer_key=None),
    ]

    result = keep_latest_sc13_per_filer(filings)

    assert [item.accession_number for item in result] == [
        "0001234567-25-000100",
        "0001234567-25-000002",
    ]


def test_should_warn_missing_sc13_only_when_requested_and_absent() -> None:
    """仅当请求了 SC13 且结果里缺失时才发 warning。"""

    requested = {"SC 13D": dt.date(2025, 1, 1), "10-K": dt.date(2021, 1, 1)}
    absent_result = should_warn_missing_sc13(requested, [_make_filing(form_type="10-K")])
    present_result = should_warn_missing_sc13(requested, [_make_filing(form_type="SC 13G")])
    unrequested_result = should_warn_missing_sc13({"10-K": dt.date(2021, 1, 1)}, [_make_filing(form_type="10-K")])

    assert absent_result is True
    assert present_result is False
    assert unrequested_result is False