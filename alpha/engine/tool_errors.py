"""工具业务错误模块。

定义 ``ToolBusinessError``，供工具实现在业务逻辑失败时抛出，
由 ToolRegistry 统一捕获并转换为标准错误信封。

用法::

    from alpha.engine.tool_errors import ToolBusinessError

    # 在工具实现中
    raise ToolBusinessError(
        code="not_found",
        message="Document 'xyz' not found for ticker 'AAPL'",
        hint="Verify the document_id via list_documents",
    )
"""

from __future__ import annotations

from typing import Any


class ToolBusinessError(Exception):
    """工具业务层错误。

    当工具执行成功但业务逻辑不满足时抛出（如资源未找到、参数无效等），
    由 ToolRegistry 捕获并转换为 ``build_error()`` 标准信封。

    Attributes:
        code: 错误码（对应 ``ErrorCode`` 枚举值，如 ``"not_found"``）。
        message: 人类可读的错误说明。
        hint: LLM 可执行的恢复建议。
        extra: 附加上下文字段。
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str = "",
        **extra: Any,
    ) -> None:
        """初始化业务错误。

        Args:
            code: 错误码字符串。
            message: 错误说明。
            hint: 恢复建议（可选）。
            **extra: 附加上下文。
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.extra = extra
