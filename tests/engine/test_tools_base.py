"""工具基础模块测试：base/tool_contracts。"""
from typing import Any, cast

import pytest

from alpha.engine.exceptions import ConfigError
from alpha.engine.tool_contracts import ToolTruncateSpec, get_strategy_spec
from alpha.engine.tools.base import _resolve_enum_values, build_tool_schema, tool


def test_resolve_enum_values_none():
    assert _resolve_enum_values(None, None) is None


def test_resolve_enum_values_callable_requires_registry():
    with pytest.raises(ConfigError, match="enum resolver requires registry"):
        _resolve_enum_values(lambda r: ["a"], None)


def test_resolve_enum_values_callable_with_registry():
    values = _resolve_enum_values(lambda r: ["a", "b"], registry={})
    assert values == ["a", "b"]


def test_resolve_enum_values_invalid_list():
    with pytest.raises(ConfigError, match="enum values must be a list"):
        _resolve_enum_values("not-a-list", registry={})


def test_resolve_enum_values_callable_returns_none():
    values = _resolve_enum_values(lambda r: None, registry={})
    assert values is None


def test_build_tool_schema_injects_enum():
    params = {
        "type": "object",
        "properties": {"mode": {"type": "string"}},
        "required": [],
    }
    schema = build_tool_schema(
        name="demo",
        description="demo",
        parameters=params,
        enums={"mode": ["a", "b"]},
    )
    props = schema.function.parameters["properties"]
    assert props["mode"]["enum"] == ["a", "b"]


def test_build_tool_schema_invalid_parameters():
    with pytest.raises(ConfigError, match="parameters must be a dict"):
        build_tool_schema(name="demo", description="demo", parameters=cast(Any, "bad"))


def test_build_tool_schema_properties_missing():
    with pytest.raises(ConfigError, match="parameters.properties must be a dict"):
        build_tool_schema(name="demo", description="demo", parameters={"type": "object"})


def test_build_tool_schema_enum_field_missing():
    params = {
        "type": "object",
        "properties": {"mode": {"type": "string"}},
        "required": [],
    }
    with pytest.raises(ConfigError, match="enum field not found"):
        build_tool_schema(
            name="demo",
            description="demo",
            parameters=params,
            enums={"missing": ["a"]},
        )


def test_build_tool_schema_removes_enum_when_none():
    params = {
        "type": "object",
        "properties": {"mode": {"type": "string", "enum": ["x"]}},
        "required": [],
    }
    schema = build_tool_schema(
        name="demo",
        description="demo",
        parameters=params,
        enums={"mode": lambda r: None},
        registry={},
    )
    props = schema.function.parameters["properties"]
    assert "enum" not in props["mode"]


def test_tool_decorator_truncate_dict():
    registry = object()
    parameters = {"type": "object", "properties": {}, "required": []}

    @tool(
        registry,
        name="demo",
        description="demo",
        parameters=parameters,
        truncate={"enabled": True, "strategy": "text_chars", "limits": {"max_chars": 1}},
    )
    def demo_tool():
        return "ok"

    assert demo_tool.__tool_extra__.__truncate__.enabled is True


def test_tool_decorator_invalid_truncate_type():
    registry = object()
    parameters = {"type": "object", "properties": {}, "required": []}

    with pytest.raises(ConfigError, match="truncate must be ToolTruncateSpec or dict"):
        @tool(
            registry,
            name="demo",
            description="demo",
            parameters=parameters,
            truncate=cast(Any, "bad"),
        )
        def demo_tool():
            return "ok"


def test_truncate_spec_errors():
    with pytest.raises(ConfigError, match="truncate.strategy is required"):
        ToolTruncateSpec(enabled=True)

    with pytest.raises(ConfigError, match="unsupported truncate.strategy"):
        ToolTruncateSpec(enabled=True, strategy="unknown", limits={"max_chars": 1})

    with pytest.raises(ConfigError, match="truncate.limits must be a non-empty dict"):
        ToolTruncateSpec(enabled=True, strategy="text_chars", limits=None)

    with pytest.raises(ConfigError, match="truncate.limits must contain only"):
        ToolTruncateSpec(enabled=True, strategy="text_chars", limits={"max_lines": 1})

    with pytest.raises(ConfigError, match="must be a positive integer"):
        ToolTruncateSpec(enabled=True, strategy="text_chars", limits={"max_chars": 0})


def test_get_strategy_spec_unknown():
    assert get_strategy_spec("unknown") == {}
