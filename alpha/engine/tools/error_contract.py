"""统一工具错误码枚举模块。

定义跨工具统一的 ``ErrorCode`` 枚举，供 ``tool_result.build_error``、
``ToolBusinessError`` 及工具实现使用。

用法::

    from alpha.engine.tools.error_contract import ErrorCode

    raise ToolBusinessError(
        code=ErrorCode.NOT_FOUND,
        message="Document 'xyz' not found for ticker 'AAPL'",
        hint="Verify the document_id via list_documents",
    )
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """工具统一错误码枚举。

    Attributes:
        NOT_FOUND: 资源不存在（文件/文档/章节/表格）。
        INVALID_ARGUMENT: 参数校验失败。
        NOT_SUPPORTED: 当前处理器/文档不支持该操作。
        PARSE_FAILED: 文件/数据解析失败。
        REQUEST_TIMEOUT: 操作超时。
        PERMISSION_DENIED: 权限不足或路径不在白名单。
        HTTP_ERROR: HTTP 请求失败。
        BLOCKED: 被站点策略阻止。
        EMPTY_CONTENT: 内容为空。
        CONTENT_CONVERSION_FAILED: 内容转换失败。
        TOO_MANY_REDIRECTS: 重定向链过长。
    """

    NOT_FOUND = "not_found"
    INVALID_ARGUMENT = "invalid_argument"
    NOT_SUPPORTED = "not_supported"
    PARSE_FAILED = "parse_failed"
    REQUEST_TIMEOUT = "request_timeout"
    PERMISSION_DENIED = "permission_denied"
    HTTP_ERROR = "http_error"
    BLOCKED = "blocked"
    EMPTY_CONTENT = "empty_content"
    CONTENT_CONVERSION_FAILED = "content_conversion_failed"
    TOO_MANY_REDIRECTS = "too_many_redirects"
