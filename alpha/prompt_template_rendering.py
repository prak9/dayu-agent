"""跨层共享的 Prompt 文本模板渲染能力。

本模块只承载纯文本模板变量替换，不依赖 Engine、Service、Host 的任何运行时语义。
"""

from __future__ import annotations

import re
from typing import Any


def replace_template_variables(text: str, variables: dict[str, Any]) -> str:
    """替换模板中的 `{{variable}}` 变量。

    Args:
        text: 包含模板变量的原始文本。
        variables: 变量名到变量值的映射。

    Returns:
        已完成变量替换的文本；未知变量保持原样。

    Raises:
        无。
    """

    def _replace_match(match: re.Match[str]) -> str:
        """替换单个命中的模板变量。

        Args:
            match: 正则匹配对象。

        Returns:
            当前变量应替换成的文本；未知变量保持原样。

        Raises:
            无。
        """

        variable_name = match.group(1)
        if variable_name in variables:
            return str(variables[variable_name])
        return match.group(0)

    return re.sub(r"\{\{([a-zA-Z0-9_]+)\}\}", _replace_match, text)


__all__ = ["replace_template_variables"]
