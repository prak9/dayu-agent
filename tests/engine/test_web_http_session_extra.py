"""`web_http_session` 额外覆盖测试。"""

from __future__ import annotations

import time
from typing import cast

import pytest
import requests
from requests.adapters import HTTPAdapter

from alpha.engine.tools import web_http_session as module


@pytest.mark.unit
def test_create_retry_and_no_retry_sessions_apply_expected_defaults() -> None:
    """HTTP session 工厂应配置重试和无重试两种默认策略。"""

    retry_session = module._create_retry_session()
    retry_adapter = retry_session.get_adapter("https://")

    source_session = requests.Session()
    source_session.headers.update({"X-Test": "1"})
    source_session.cookies.set("token", "abc")
    source_session.max_redirects = 5
    no_retry_session = module._create_no_retry_session(source_session=source_session)
    no_retry_adapter = no_retry_session.get_adapter("https://")

    assert retry_session.max_redirects == 8
    assert cast(HTTPAdapter, retry_adapter).max_retries.total == 3
    assert no_retry_session.headers["X-Test"] == "1"
    assert no_retry_session.cookies.get("token") == "abc"
    assert no_retry_session.max_redirects == 5
    assert cast(HTTPAdapter, no_retry_adapter).max_retries.total == 0


@pytest.mark.unit
def test_get_web_sessions_cache_global_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    """全局 session getter 应缓存构造结果。"""

    retry_calls: list[str] = []
    no_retry_calls: list[str] = []
    retry_session = requests.Session()
    no_retry_session = requests.Session()

    monkeypatch.setattr(module, "_WEB_SESSION", None)
    monkeypatch.setattr(module, "_WEB_NO_RETRY_SESSION", None)
    monkeypatch.setattr(module, "_create_retry_session", lambda: retry_calls.append("retry") or retry_session)
    monkeypatch.setattr(module, "_create_no_retry_session", lambda source_session=None: no_retry_calls.append("no_retry") or no_retry_session)

    assert module._get_web_session() is retry_session
    assert module._get_web_session() is retry_session
    assert module._get_no_retry_web_session() is no_retry_session
    assert module._get_no_retry_web_session() is no_retry_session
    assert retry_calls == ["retry"]
    assert no_retry_calls == ["no_retry"]


@pytest.mark.unit
def test_timeout_helpers_and_prepare_call_session_cover_budget_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    """timeout helper 应覆盖预算收敛和 session 选择分支。"""

    assert module._safe_timeout(0.1) == 1.0
    assert module._normalize_timeout_budget(None) is None
    assert module._normalize_timeout_budget(-1.0) == 0.0

    deadline = module._compute_deadline_monotonic(1.5)
    assert deadline is not None and deadline >= time.monotonic()
    assert module._compute_deadline_monotonic(None) is None

    session = requests.Session()
    no_retry_session = requests.Session()
    monkeypatch.setattr(module, "_get_no_retry_web_session", lambda: no_retry_session)

    prepared_session, should_close = module._prepare_call_session(session, timeout_budget=3.0)
    passthrough_session, passthrough_close = module._prepare_call_session(session, timeout_budget=None)

    assert prepared_session is no_retry_session
    assert should_close is False
    assert passthrough_session is session
    assert passthrough_close is False

    assert module._resolve_timeout_budget(5.0, timeout_budget=2.0, deadline_monotonic=None, reserve_seconds=0.5) == 1.5

    with pytest.raises(requests.Timeout):
        module._resolve_timeout_budget(
            5.0,
            deadline_monotonic=time.monotonic(),
            reserve_seconds=0.1,
        )