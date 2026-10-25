# -*- coding: utf-8 -*-
"""ToolRegistry 能力快照与 PromptComposer 组合测试。"""

from typing import Any, cast

from alpha.startup.config_file_resolver import ConfigFileResolver
from alpha.startup.prompt_assets import FilePromptAssetStore
from alpha.engine.tool_registry import ToolRegistry
from alpha.prompting import (
    PromptComposeContext,
    PromptComposer,
    build_prompt_assembly_plan,
    build_prompt_tool_snapshot,
    load_scene_definition,
)


def test_build_prompt_tool_snapshot_contains_directories_and_flags(tmp_path):
    """验证工具快照会携带路径和工具开关。"""

    registry = ToolRegistry()
    registry.register_allowed_paths([tmp_path])

    snapshot = build_prompt_tool_snapshot(registry, supports_tool_calling=True)

    assert str(tmp_path.resolve()) in snapshot.allowed_paths
    assert snapshot.supports_tool_calling is True


def test_get_tool_names_and_tags_excludes_fetch_more():
    """验证 tool_names/tool_tags 不包含 fetch_more。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    registry = ToolRegistry()

    def dummy_tool() -> str:
        return "ok"

    cast_tool = cast(Any, dummy_tool)
    cast_tool.__tool_tags__ = {"alpha", "beta"}
    schema = {
        "type": "function",
        "function": {
            "name": "dummy_tool",
            "description": "demo",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
    registry.register("dummy_tool", dummy_tool, schema)

    names = registry.get_tool_names()
    tags = registry.get_tool_tags()
    assert "dummy_tool" in names
    assert "fetch_more" not in names
    assert "alpha" in tags


def test_empty_registry_does_not_expose_fetch_more_until_first_tool_registered():
    """验证空 registry 不暴露 fetch_more，首个工具注册后才自动出现。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    registry = ToolRegistry()

    assert registry.list_tools() == []
    assert registry.get_schemas() == []

    def dummy_tool() -> str:
        return "ok"

    schema = {
        "type": "function",
        "function": {
            "name": "dummy_tool",
            "description": "demo",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
    registry.register("dummy_tool", dummy_tool, schema)

    names = registry.list_tools()
    assert "dummy_tool" in names
    assert "fetch_more" in names


def test_prompt_composer_renders_fins_guidance_rules():
    """验证基于 snapshot 的组合结果会渲染当前 fins 工具规则。"""

    registry = ToolRegistry()

    def dummy_fins_tool() -> str:
        return "ok"

    cast_fins_tool = cast(Any, dummy_fins_tool)
    cast_fins_tool.__tool_tags__ = {"fins"}
    schema = {
        "type": "function",
        "function": {
            "name": "dummy_fins_tool",
            "description": "demo",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
    registry.register("dummy_fins_tool", dummy_fins_tool, schema)

    snapshot = build_prompt_tool_snapshot(registry, supports_tool_calling=True)
    composer = PromptComposer()
    plan = build_prompt_assembly_plan(asset_store=FilePromptAssetStore(ConfigFileResolver()), scene_name="interactive")
    manifest = load_scene_definition(FilePromptAssetStore(ConfigFileResolver()), "interactive")
    composed = composer.compose(
        plan=plan,
        context=PromptComposeContext(values={"directories": "workspace/test"}),
        tool_snapshot=snapshot,
        prompt_contributions={
            "fins_default_subject": "# 当前分析对象\n你正在分析的是 TEST。",
            "base_user": "# 用户与运行时上下文\n当前时间：2026年03月13日。",
        },
        context_slots=manifest.context_slots,
    )

    assert "优先用 `list_documents` 返回的 `recommended_documents`" in composed.system_message
    assert "后续所有 fins 工具优先复用这次返回里的 `company.ticker`" not in composed.system_message
    assert "交互执行契约" in composed.system_message
