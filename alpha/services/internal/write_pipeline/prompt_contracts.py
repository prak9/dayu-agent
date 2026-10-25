"""Task prompt contract 解析与渲染。

该模块负责：
- 解析 task prompt sidecar contract YAML。
- 校验 prompt 输入字段的完整性与类型。
- 将显式字段渲染为稳定的 fenced code block，避免再把 Markdown 塞进黑盒 JSON。

所有写作领域语义都停留在 write pipeline 内，不泄漏到 engine 包。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, cast

from alpha.contracts.prompt_assets import TaskPromptContractAsset, TaskPromptInputAsset
from alpha.prompt_template_rendering import replace_template_variables

_SUPPORTED_INPUT_TYPES = {"scalar", "markdown_block", "list_block", "mapping_block", "json_block"}
_VARIABLE_PATTERN = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")
_BACKTICK_RUN_PATTERN = re.compile(r"`{3,}")


@dataclass(frozen=True)
class PromptInputSpec:
    """Prompt 输入字段定义。

    Args:
        name: 字段名。
        input_type: 输入类型。
        required: 是否必填。
        description: 字段说明。

    Returns:
        无。

    Raises:
        无。
    """

    name: str
    input_type: str
    required: bool
    description: str = ""

    @property
    def template_variable_name(self) -> str:
        """返回模板变量名。

        Args:
            无。

        Returns:
            prompt 模板中应使用的变量名。

        Raises:
            无。
        """

        if self.input_type == "scalar":
            return self.name
        if self.name.endswith("_block"):
            return self.name
        return f"{self.name}_block"


@dataclass(frozen=True)
class TaskPromptContract:
    """Task prompt contract。

    Args:
        prompt_name: prompt 名称。
        version: contract 版本。
        inputs: 输入字段定义列表。

    Returns:
        无。

    Raises:
        无。
    """

    prompt_name: str
    version: str
    inputs: list[PromptInputSpec]


def parse_task_prompt_contract(raw_data: object, *, task_name: str) -> TaskPromptContract:
    """解析 task prompt sidecar contract。

    Args:
        raw_data: YAML 解析后的原始对象。
        task_name: task 名称，仅用于错误提示。

    Returns:
        `TaskPromptContract` 对象。

    Raises:
        ValueError: 当 contract 结构非法时抛出。
    """

    if not isinstance(raw_data, dict):
        raise ValueError(f"task prompt contract {task_name!r} 必须是映射")
    raw_contract = cast(TaskPromptContractAsset, raw_data)

    prompt_name = _require_non_empty_string(raw_contract, key="prompt_name", task_name=task_name)
    version = _require_non_empty_string(raw_contract, key="version", task_name=task_name)
    if prompt_name != task_name:
        raise ValueError(f"task prompt contract {task_name!r} 的 prompt_name 必须与 task 名一致")

    raw_inputs = raw_contract.get("inputs")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise ValueError(f"task prompt contract {task_name!r} 的 inputs 必须为非空列表")

    inputs: list[PromptInputSpec] = []
    seen_names: set[str] = set()
    for raw_spec in raw_inputs:
        if not isinstance(raw_spec, dict):
            raise ValueError(f"task prompt contract {task_name!r} 的 inputs 项必须为映射")
        typed_spec = cast(TaskPromptInputAsset, raw_spec)
        name = _require_non_empty_string(typed_spec, key="name", task_name=task_name)
        if name in seen_names:
            raise ValueError(f"task prompt contract {task_name!r} 出现重复输入字段 {name!r}")
        input_type = _require_non_empty_string(typed_spec, key="type", task_name=task_name)
        if input_type not in _SUPPORTED_INPUT_TYPES:
            raise ValueError(f"task prompt contract {task_name!r} 的字段 {name!r} 类型 {input_type!r} 不受支持")
        required_value = typed_spec.get("required", True)
        if not isinstance(required_value, bool):
            raise ValueError(f"task prompt contract {task_name!r} 的字段 {name!r} required 必须为布尔值")
        description_value = typed_spec.get("description", "")
        if description_value is None:
            description_value = ""
        if not isinstance(description_value, str):
            raise ValueError(f"task prompt contract {task_name!r} 的字段 {name!r} description 必须为字符串")
        seen_names.add(name)
        inputs.append(
            PromptInputSpec(
                name=name,
                input_type=input_type,
                required=required_value,
                description=description_value.strip(),
            )
        )

    return TaskPromptContract(prompt_name=prompt_name, version=version, inputs=inputs)


def render_task_prompt(
    *,
    prompt_template: str,
    prompt_contract: TaskPromptContract,
    prompt_inputs: dict[str, Any],
) -> str:
    """按 contract 渲染 task prompt。

    Args:
        prompt_template: prompt 模板文本。
        prompt_contract: prompt contract。
        prompt_inputs: 显式输入字段。

    Returns:
        渲染后的 prompt 文本。

    Raises:
        ValueError: 当字段缺失、未知、类型错误或存在未替换变量时抛出。
    """

    _validate_prompt_inputs(prompt_contract=prompt_contract, prompt_inputs=prompt_inputs)
    template_variables: dict[str, str] = {}
    for spec in prompt_contract.inputs:
        value = prompt_inputs.get(spec.name)
        template_variables[spec.template_variable_name] = _render_input_value(spec=spec, value=value)

    rendered = replace_template_variables(prompt_template, template_variables)
    unresolved = sorted({match.group(1) for match in _VARIABLE_PATTERN.finditer(rendered)})
    if unresolved:
        unresolved_text = ", ".join(unresolved)
        raise ValueError(
            f"task prompt {prompt_contract.prompt_name!r} 渲染后仍存在未替换变量: {unresolved_text}"
        )
    return rendered


def _validate_prompt_inputs(*, prompt_contract: TaskPromptContract, prompt_inputs: dict[str, Any]) -> None:
    """校验 prompt 输入字段是否与 contract 一致。

    Args:
        prompt_contract: prompt contract。
        prompt_inputs: 传入字段字典。

    Returns:
        无。

    Raises:
        ValueError: 当缺失必填字段或出现未知字段时抛出。
    """

    expected_names = {spec.name for spec in prompt_contract.inputs}
    provided_names = set(prompt_inputs.keys())
    unknown_names = sorted(provided_names - expected_names)
    if unknown_names:
        raise ValueError(
            f"task prompt {prompt_contract.prompt_name!r} 收到未声明字段: {', '.join(unknown_names)}"
        )

    missing_names = [
        spec.name
        for spec in prompt_contract.inputs
        if spec.required and spec.name not in prompt_inputs
    ]
    if missing_names:
        raise ValueError(
            f"task prompt {prompt_contract.prompt_name!r} 缺少必填字段: {', '.join(missing_names)}"
        )


def _render_input_value(*, spec: PromptInputSpec, value: Any) -> str:
    """按字段类型渲染单个输入值。

    Args:
        spec: 字段定义。
        value: 原始输入值。

    Returns:
        渲染后的文本。

    Raises:
        ValueError: 当输入类型不匹配时抛出。
    """

    if spec.input_type == "scalar":
        return _render_scalar_value(spec=spec, value=value)
    if spec.input_type == "markdown_block":
        if not isinstance(value, str):
            raise ValueError(f"字段 {spec.name!r} 必须为字符串，以渲染 markdown_block")
        return _wrap_code_block(body=value, language="markdown")
    if spec.input_type == "list_block":
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(f"字段 {spec.name!r} 必须为字符串列表，以渲染 list_block")
        body = json.dumps(value, ensure_ascii=False, indent=2)
        return _wrap_code_block(body=body, language="json")
    if spec.input_type == "mapping_block":
        if not isinstance(value, dict):
            raise ValueError(f"字段 {spec.name!r} 必须为映射，以渲染 mapping_block")
        body = json.dumps(value, ensure_ascii=False, indent=2)
        return _wrap_code_block(body=body, language="json")
    if spec.input_type == "json_block":
        try:
            body = json.dumps(value, ensure_ascii=False, indent=2)
        except TypeError as exc:
            raise ValueError(f"字段 {spec.name!r} 无法序列化为 JSON: {exc}") from exc
        return _wrap_code_block(body=body, language="json")
    raise ValueError(f"字段 {spec.name!r} 的类型 {spec.input_type!r} 不受支持")


def _render_scalar_value(*, spec: PromptInputSpec, value: Any) -> str:
    """渲染标量值。

    Args:
        spec: 字段定义。
        value: 原始值。

    Returns:
        字符串形式的标量值。

    Raises:
        ValueError: 当值类型不支持时抛出。
    """

    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise ValueError(f"字段 {spec.name!r} 必须为字符串、数字、布尔值或 None，以渲染 scalar")


def _wrap_code_block(*, body: str, language: str) -> str:
    """为长文本字段包裹 fenced code block。

    Args:
        body: 待包裹正文。
        language: 代码块语言标记。

    Returns:
        带 fenced code block 的文本。

    Raises:
        无。
    """

    fence = _build_fence(body)
    if body:
        return f"{fence}{language}\n{body}\n{fence}"
    return f"{fence}{language}\n{fence}"


def _build_fence(body: str) -> str:
    """根据正文内容生成安全的代码围栏。

    Args:
        body: 待包裹正文。

    Returns:
        不与正文冲突的反引号围栏字符串。

    Raises:
        无。
    """

    max_run_length = 0
    for match in _BACKTICK_RUN_PATTERN.finditer(body):
        max_run_length = max(max_run_length, len(match.group(0)))
    return "`" * max(3, max_run_length + 1)


def _require_non_empty_string(raw_data: Mapping[str, object], *, key: str, task_name: str) -> str:
    """读取并校验非空字符串字段。

    Args:
        raw_data: 原始映射。
        key: 字段名。
        task_name: task 名称，仅用于错误提示。

    Returns:
        去除首尾空白后的字符串。

    Raises:
        ValueError: 当字段缺失或为空时抛出。
    """

    value = raw_data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"task prompt contract {task_name!r} 的 {key} 必须为非空字符串")
    return value.strip()
