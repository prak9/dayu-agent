"""UI 层终端展示辅助函数。"""

from __future__ import annotations

from alpha.contracts.fins import FinsCommandName, FinsResultData
from alpha.fins.cli_formatters import format_cli_result as _format_fins_cli_result


def format_fins_cli_result(command: FinsCommandName, result: FinsResultData) -> str:
    """格式化财报 CLI 结果。

    Args:
        command: 财报命令名。
        result: 财报强类型结果。

    Returns:
        面向终端阅读的文本。

    Raises:
        无。
    """

    return _format_fins_cli_result(command, result)


__all__ = ["format_fins_cli_result"]
