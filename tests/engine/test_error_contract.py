"""error_contract ErrorCode 枚举测试。"""

from __future__ import annotations

from alpha.engine.tools.error_contract import ErrorCode


def test_error_code_values_are_stable_machine_contracts() -> None:
    """验证 ErrorCode 枚举值保持稳定，避免工具恢复契约漂移。"""

    assert ErrorCode.NOT_FOUND.value == "not_found"
    assert ErrorCode.INVALID_ARGUMENT.value == "invalid_argument"
    assert ErrorCode.NOT_SUPPORTED.value == "not_supported"
    assert ErrorCode.PARSE_FAILED.value == "parse_failed"
    assert ErrorCode.REQUEST_TIMEOUT.value == "request_timeout"
    assert ErrorCode.PERMISSION_DENIED.value == "permission_denied"
    assert ErrorCode.HTTP_ERROR.value == "http_error"
    assert ErrorCode.BLOCKED.value == "blocked"
    assert ErrorCode.EMPTY_CONTENT.value == "empty_content"
    assert ErrorCode.CONTENT_CONVERSION_FAILED.value == "content_conversion_failed"
    assert ErrorCode.TOO_MANY_REDIRECTS.value == "too_many_redirects"


def test_error_code_count() -> None:
    """验证 ErrorCode 枚举成员数为 11。"""

    assert len(ErrorCode) == 11


def test_error_code_is_str_subclass() -> None:
    """验证 ErrorCode 可直接当 str 使用。"""

    assert isinstance(ErrorCode.NOT_FOUND, str)
    assert ErrorCode.NOT_FOUND == "not_found"
    assert ErrorCode.TOO_MANY_REDIRECTS.value == "too_many_redirects"
