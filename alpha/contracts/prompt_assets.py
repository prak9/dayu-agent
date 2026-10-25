"""Prompt 资产原始文件 schema。

该模块定义 scene manifest 与 task prompt contract 在文件边界上的稳定结构，
供 startup 读取层、prompt 解析层与测试夹具共享，避免继续把 prompt 资产当作
宽泛的 ``dict[str, object]`` 深层索引。
"""

from __future__ import annotations

from typing import Literal, NotRequired, Required, TypedDict, TypeAlias


PromptInputTypeName: TypeAlias = Literal[
    "scalar",
    "markdown_block",
    "list_block",
    "mapping_block",
    "json_block",
]


class TaskPromptInputAsset(TypedDict, total=False):
    """Task prompt 单个输入字段的原始 schema。"""

    name: Required[str]
    type: Required[PromptInputTypeName]
    required: NotRequired[bool]
    description: NotRequired[str]


class TaskPromptContractAsset(TypedDict, total=False):
    """Task prompt sidecar contract 的原始 schema。"""

    prompt_name: Required[str]
    version: Required[str]
    inputs: Required[list[TaskPromptInputAsset]]


class SceneModelAsset(TypedDict, total=False):
    """Scene manifest 中 ``model`` 子结构的原始 schema。"""

    default_name: Required[str]
    allowed_names: Required[list[str]]
    temperature_profile: Required[str]


class SceneAgentRuntimeAsset(TypedDict, total=False):
    """Scene manifest 中 ``runtime.agent`` 子结构的原始 schema。"""

    max_iterations: NotRequired[int]
    max_consecutive_failed_tool_batches: NotRequired[int]


class SceneRunnerRuntimeAsset(TypedDict, total=False):
    """Scene manifest 中 ``runtime.runner`` 子结构的原始 schema。"""

    tool_timeout_seconds: NotRequired[float]


class SceneRuntimeAsset(TypedDict, total=False):
    """Scene manifest 中 ``runtime`` 子结构的原始 schema。"""

    agent: NotRequired[SceneAgentRuntimeAsset]
    runner: NotRequired[SceneRunnerRuntimeAsset]


class SceneToolSelectionAsset(TypedDict, total=False):
    """Scene manifest 中 ``tool_selection`` 子结构的原始 schema。"""

    mode: Required[str]
    tool_tags_any: NotRequired[list[str]]


class SceneConversationAsset(TypedDict):
    """Scene manifest 中 ``conversation`` 子结构的原始 schema。"""

    enabled: bool


class SceneDefaultsAsset(TypedDict, total=False):
    """Scene manifest 中 ``defaults`` 子结构的原始 schema。"""

    missing_fragment_policy: NotRequired[str]


class SceneFragmentAsset(TypedDict, total=False):
    """Scene manifest 中单个 fragment 的原始 schema。"""

    id: Required[str]
    type: Required[str]
    path: Required[str]
    order: Required[int]
    required: NotRequired[bool]
    context_keys: NotRequired[list[str]]
    skip_if_context_missing: NotRequired[bool]
    enabled: NotRequired[bool]
    tool_filters: NotRequired[dict[str, list[str]]]


class SceneManifestAsset(TypedDict, total=False):
    """Scene manifest 顶层原始 schema。"""

    scene: Required[str]
    model: Required[SceneModelAsset]
    runtime: NotRequired[SceneRuntimeAsset]
    version: NotRequired[str]
    description: NotRequired[str]
    extends: NotRequired[list[str]]
    defaults: NotRequired[SceneDefaultsAsset]
    fragments: Required[list[SceneFragmentAsset]]
    context_slots: Required[list[str]]
    conversation: NotRequired[SceneConversationAsset]
    tool_selection: Required[SceneToolSelectionAsset]


__all__ = [
    "PromptInputTypeName",
    "SceneAgentRuntimeAsset",
    "SceneConversationAsset",
    "SceneDefaultsAsset",
    "SceneFragmentAsset",
    "SceneManifestAsset",
    "SceneModelAsset",
    "SceneRunnerRuntimeAsset",
    "SceneRuntimeAsset",
    "SceneToolSelectionAsset",
    "TaskPromptContractAsset",
    "TaskPromptInputAsset",
]