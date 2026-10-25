"""写作流水线执行选项辅助函数。"""

from __future__ import annotations

from dataclasses import replace

from alpha.execution.options import ExecutionOptions


def build_execution_options_with_model_override(
    *,
    execution_options: ExecutionOptions | None,
    model_name: str | None,
) -> ExecutionOptions | None:
    """基于显式模型覆盖构建执行选项。

    Args:
        execution_options: 原始请求级执行选项。
        model_name: 目标模型名；为空时表示移除请求级模型覆盖。

    Returns:
        去除旧模型覆盖后重新应用新模型覆盖的执行选项；若最终无任何覆盖则返回 ``None`` 或去模型后的原对象。

    Raises:
        无。
    """

    normalized_model_name = str(model_name or "").strip()
    stripped_options = execution_options
    if stripped_options is not None:
        stripped_options = replace(stripped_options, model_name=None)
    if not normalized_model_name:
        return stripped_options
    if stripped_options is None:
        return ExecutionOptions(model_name=normalized_model_name)
    return replace(stripped_options, model_name=normalized_model_name)


def build_execution_options_with_scene_overrides(
    *,
    execution_options: ExecutionOptions | None,
    model_name: str | None,
    web_provider: str | None,
) -> ExecutionOptions | None:
    """同时应用模型与联网 provider 覆盖。

    Args:
        execution_options: 原始请求级执行选项。
        model_name: 目标模型名；为空时表示移除请求级模型覆盖。
        web_provider: 当前 scene 需要使用的联网 provider；为空时保留原值。

    Returns:
        合并后的 scene 级执行选项；若最终无任何覆盖则返回 ``None``。

    Raises:
        无。
    """

    resolved_options = build_execution_options_with_model_override(
        execution_options=execution_options,
        model_name=model_name,
    )
    normalized_web_provider = str(web_provider or "").strip()
    if not normalized_web_provider:
        return resolved_options
    if resolved_options is None:
        return ExecutionOptions(web_provider=normalized_web_provider)
    return replace(resolved_options, web_provider=normalized_web_provider)


__all__ = [
    "build_execution_options_with_model_override",
    "build_execution_options_with_scene_overrides",
]
