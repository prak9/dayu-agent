"""web_recovery 恢复语义模型测试。"""

from __future__ import annotations

import pytest

from alpha.engine.tools.web_recovery import (
    RECOVERY_CONTRACT_VERSION,
    ALLOWED_NEXT_ACTIONS,
    ALLOWED_REASONS,
    NEXT_ACTION_CHANGE_SOURCE,
    NEXT_ACTION_CONTINUE_WITHOUT_WEB,
    NEXT_ACTION_RETRY,
    REASON_BLOCKED_BY_SITE_POLICY,
    REASON_CONTENT_CONVERSION_FAILED,
    REASON_EMPTY_CONTENT,
    REASON_HTTP_ERROR,
    REASON_REDIRECT_CHAIN_TOO_LONG,
    REASON_REQUEST_TIMEOUT,
    build_hint,
    normalize_next_action,
    normalize_reason,
)


@pytest.mark.unit
def test_normalize_next_action_returns_allowed_values() -> None:
    """验证 next_action 规范化行为。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    assert normalize_next_action(NEXT_ACTION_RETRY) == NEXT_ACTION_RETRY
    assert normalize_next_action(NEXT_ACTION_CHANGE_SOURCE) == NEXT_ACTION_CHANGE_SOURCE
    assert normalize_next_action(NEXT_ACTION_CONTINUE_WITHOUT_WEB) == NEXT_ACTION_CONTINUE_WITHOUT_WEB
    assert normalize_next_action("invalid") == NEXT_ACTION_CHANGE_SOURCE


@pytest.mark.unit
def test_normalize_reason_returns_allowed_values() -> None:
    """验证 reason 规范化行为。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    assert normalize_reason(REASON_REQUEST_TIMEOUT) == REASON_REQUEST_TIMEOUT
    assert normalize_reason(REASON_HTTP_ERROR) == REASON_HTTP_ERROR
    assert normalize_reason(REASON_BLOCKED_BY_SITE_POLICY) == REASON_BLOCKED_BY_SITE_POLICY
    assert normalize_reason(REASON_REDIRECT_CHAIN_TOO_LONG) == REASON_REDIRECT_CHAIN_TOO_LONG
    assert normalize_reason(REASON_CONTENT_CONVERSION_FAILED) == REASON_CONTENT_CONVERSION_FAILED
    assert normalize_reason(REASON_EMPTY_CONTENT) == REASON_EMPTY_CONTENT
    assert normalize_reason("invalid") == REASON_HTTP_ERROR


@pytest.mark.unit
def test_recovery_enums_are_unique_and_stable() -> None:
    """验证恢复语义枚举集合稳定且无重复。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    assert ALLOWED_NEXT_ACTIONS == {
        NEXT_ACTION_RETRY,
        NEXT_ACTION_CHANGE_SOURCE,
        NEXT_ACTION_CONTINUE_WITHOUT_WEB,
    }
    assert ALLOWED_REASONS == {
        REASON_REQUEST_TIMEOUT,
        REASON_HTTP_ERROR,
        REASON_BLOCKED_BY_SITE_POLICY,
        REASON_REDIRECT_CHAIN_TOO_LONG,
        REASON_CONTENT_CONVERSION_FAILED,
        REASON_EMPTY_CONTENT,
    }


@pytest.mark.unit
def test_recovery_contract_version_is_stable() -> None:
    """验证恢复协议版本号稳定。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    assert RECOVERY_CONTRACT_VERSION == "web_recovery_v1"


@pytest.mark.unit
def test_build_hint_returns_reason_specific_message() -> None:
    """验证按 reason 生成提示文案。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    assert "目标：" in build_hint(REASON_REQUEST_TIMEOUT)
    assert "允许动作：" in build_hint(REASON_REQUEST_TIMEOUT)
    assert "下一步：" in build_hint(REASON_REQUEST_TIMEOUT)
    assert "换来源" in build_hint(REASON_BLOCKED_BY_SITE_POLICY)
    assert "检查链接" in build_hint(REASON_HTTP_ERROR)
