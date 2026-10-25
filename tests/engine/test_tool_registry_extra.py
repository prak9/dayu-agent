"""ToolRegistry 额外分支覆盖测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from alpha.contracts.protocols import ToolExecutionContext
from alpha.engine import ToolRegistry
from alpha.engine.tool_contracts import ToolTruncateSpec
from alpha.prompting import build_prompt_tool_snapshot


def _simple_schema(name: str) -> dict[str, Any]:
    """构造最小可执行工具 schema。

    Args:
        name: 工具名称。

    Returns:
        可用于注册工具的最小 schema。

    Raises:
        无。
    """

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "test",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }


def _register_tool(
    registry: ToolRegistry,
    name: str,
    func: Any,
    *,
    execution_context_param_name: str | None = None,
) -> None:
    """注册测试工具并附加最小元数据。

    Args:
        registry: 工具注册表实例。
        name: 工具名称。
        func: 工具函数。

    Returns:
        无。

    Raises:
        ConfigError: schema 非法时抛出。
    """

    cast(Any, func).__tool_extra__ = type(
        "ToolExtra",
        (),
        {
            "__file_path_params__": [],
            "__truncate__": None,
            "__tags__": {"alpha"},
            "__execution_context_param_name__": execution_context_param_name,
        },
    )()
    registry.register(name, func, _simple_schema(name))


def test_build_prompt_tool_snapshot_contains_registered_tools_and_paths() -> None:
    """验证 prompt 工具快照会汇总工具名、标签与允许路径。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    registry = ToolRegistry()
    root = Path.cwd()
    registry.register_allowed_paths([root])

    def _tool() -> str:
        return "ok"

    _register_tool(registry, "demo_tool", _tool)
    _register_tool(registry, "fetch_more", _tool)
    registry.tool_descriptors["demo_tool"].tags = {"alpha"}

    snapshot = build_prompt_tool_snapshot(registry, supports_tool_calling=True)

    assert snapshot.tool_names == frozenset({"demo_tool"})
    assert snapshot.tool_tags == frozenset({"alpha"})
    assert snapshot.allowed_paths == (str(root.resolve()),)
    assert snapshot.supports_tool_calling is True


def test_execute_exception_wrapping_paths() -> None:
    """验证 execute 的多种异常包装分支。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    registry = ToolRegistry()

    def _raise_file_not_found() -> None:
        raise FileNotFoundError("x")

    def _raise_permission() -> None:
        raise PermissionError("x")

    def _raise_type_error() -> None:
        raise TypeError("x")

    def _raise_runtime() -> None:
        raise RuntimeError("x")

    _register_tool(registry, "missing_tool", _raise_file_not_found)
    _register_tool(registry, "permission_tool", _raise_permission)
    _register_tool(registry, "type_tool", _raise_type_error)
    _register_tool(registry, "runtime_tool", _raise_runtime)

    assert registry.execute("missing_tool", {})["error"] == "file_not_found"
    assert registry.execute("permission_tool", {})["error"] == "permission_denied"
    assert registry.execute("type_tool", {})["error"] == "invalid_argument"
    assert registry.execute("runtime_tool", {})["error"] == "execution_error"


def test_apply_truncation_noop_and_extract_helpers() -> None:
    """验证截断 noop 分支与提取 helper 异常分支。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    registry = ToolRegistry()
    tm = registry._truncation_manager

    raw_text = "abc"

    class _InvalidSpec:
        """测试用无效策略对象。"""

        enabled = True
        strategy = "unknown"
        limits = {"max_chars": 1}

    invalid_strategy_spec = cast(ToolTruncateSpec, _InvalidSpec())
    result, trunc = tm.apply_truncation(
        name="demo",
        arguments={},
        value=raw_text,
        context=None,
        truncate_spec=invalid_strategy_spec,
    )
    assert trunc is None
    assert result == raw_text

    class _InvalidLimitSpec:
        """测试用无效限制对象。"""

        enabled = True
        strategy = "text_chars"
        limits = {"max_chars": 0}

    invalid_limit_spec = cast(ToolTruncateSpec, _InvalidLimitSpec())
    result2, trunc2 = tm.apply_truncation(
        name="demo",
        arguments={},
        value=raw_text,
        context=None,
        truncate_spec=invalid_limit_spec,
    )
    assert trunc2 is None
    assert result2 == raw_text

    text_none, _, _ = tm._extract_text_target({"a": 1})
    assert text_none is None

    list_none, _, _ = tm._extract_list_target({"a": 1})
    assert list_none is None

    binary_none, _, _ = tm._extract_binary_target("%%not-base64%%")
    assert binary_none is None


def test_coerce_value_for_type_extra_branches() -> None:
    """覆盖 schema coercion 的补充分支。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    registry = ToolRegistry()
    av = registry._argument_validator

    ok_bool, value_bool, issues_bool = av._coerce_value_for_type("true", {"type": "boolean"}, "$.flag")
    assert ok_bool is True
    assert value_bool is True
    assert issues_bool == []

    ok_number, value_number, _ = av._coerce_value_for_type("3.14", {"type": "number"}, "$.num")
    assert ok_number is True
    assert value_number == 3.14

    ok_array, _, issues_array = av._coerce_value_for_type(
        [1, 2, 3],
        {"type": "array", "maxItems": 2},
        "$.arr",
    )
    assert ok_array is False
    assert issues_array[0]["reason"] == "array_too_large"

    ok_object, _, issues_object = av._coerce_value_for_type(
        {"x": 1},
        {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]},
        "$.obj",
    )
    assert ok_object is False
    assert any(issue["reason"] == "missing_required" for issue in issues_object)


# ── Response Middleware Tests ─────────────────────────────────────


def test_response_middleware_called_on_success() -> None:
    """验证 middleware 在工具执行成功后被调用且能修改 result。"""

    registry = ToolRegistry()

    def _tool() -> str:
        return "hello"

    _register_tool(registry, "demo_tool", _tool)

    captured: list[tuple[str, dict]] = []

    def _mw(
        tool_name: str,
        result: dict[str, Any],
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        captured.append((tool_name, result))
        result["injected"] = True
        return result

    registry.register_response_middleware(_mw)

    result = registry.execute("demo_tool", {})
    assert result["ok"] is True
    assert result["injected"] is True
    assert len(captured) == 1
    assert captured[0][0] == "demo_tool"


def test_response_middleware_not_called_on_failure() -> None:
    """验证工具执行失败时 middleware 不被调用。"""

    registry = ToolRegistry()

    def _bad_tool() -> None:
        raise RuntimeError("boom")

    _register_tool(registry, "failing_tool", _bad_tool)

    called = {"value": False}

    def _mw(
        tool_name: str,
        result: dict[str, Any],
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        called["value"] = True
        return result

    registry.register_response_middleware(_mw)

    result = registry.execute("failing_tool", {})
    assert result["ok"] is False
    assert called["value"] is False


def test_response_middleware_chain_order() -> None:
    """验证多个 middleware 按注册顺序链式执行。"""

    registry = ToolRegistry()

    def _tool() -> str:
        return "ok"

    _register_tool(registry, "demo_tool", _tool)

    order: list[str] = []

    def _mw_a(
        tool_name: str,
        result: dict[str, Any],
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        order.append("A")
        return result

    def _mw_b(
        tool_name: str,
        result: dict[str, Any],
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        order.append("B")
        return result

    registry.register_response_middleware(_mw_a)
    registry.register_response_middleware(_mw_b)

    registry.execute("demo_tool", {})
    assert order == ["A", "B"]


def test_no_middleware_leaves_result_unchanged() -> None:
    """验证无 middleware 时 result 原样返回。"""

    registry = ToolRegistry()

    def _tool() -> str:
        return "raw"

    _register_tool(registry, "demo_tool", _tool)

    result = registry.execute("demo_tool", {})
    assert result["ok"] is True
    assert "injected" not in result


def test_execute_injects_explicit_execution_context() -> None:
    """验证显式声明 execution_context 参数名的工具会收到强类型上下文。"""

    registry = ToolRegistry()
    captured: dict[str, ToolExecutionContext] = {}

    def _tool(*, execution_context: ToolExecutionContext) -> str:
        captured["context"] = execution_context
        return "ok"

    _register_tool(
        registry,
        "demo_tool",
        _tool,
        execution_context_param_name="execution_context",
    )
    context = ToolExecutionContext(
        run_id="run_test",
        iteration_id="iteration_test",
        tool_call_id="call_test",
        index_in_iteration=1,
        timeout_seconds=9.5,
    )

    result = registry.execute("demo_tool", {}, context=context)

    assert result["ok"] is True
    assert captured["context"] == context
