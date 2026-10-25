"""argument_validator 模块单元测试。

该文件覆盖 `ArgumentValidator` 的低频错误分支与边界分支，
重点包括：
- 无 schema 情况下的通用限制检查
- type=None 场景的 enum 与限制校验
- integer/number/boolean 的异常输入分支
- array/object 的特殊输入处理（tuple、默认值、额外字段）
"""

from __future__ import annotations

from typing import Any, cast

from alpha.engine.argument_validator import ArgumentValidator
from alpha.engine.tool_result import validate_tool_result_contract


def test_union_types_preserve_json_value_before_attempting_coercion() -> None:
    """联合类型先保留已有JSON类型，防止修订数字字符串或空值。参数：无。返回：无。异常：断言失败。"""
    validator = ArgumentValidator()
    for value in [None, "100", "true", {"x": 1}, [1], 100, False]:
        result = validator.validate_and_coerce({"value": value}, parameters={
            "type": "object", "properties": {"value": {"type": ["string", "object", "array", "number", "boolean", "null"],
            "additionalProperties": True, "items": {}}}, "required": ["value"], "additionalProperties": False})
        assert result["ok"] is True
        assert result["arguments"]["value"] == value
        assert type(result["arguments"]["value"]) is type(value)


class _NotStringableNumber:
    """用于测试 number 类型不匹配的辅助对象。"""


def _build_validator() -> ArgumentValidator:
    """创建参数校验器实例。

    Args:
        无。

    Returns:
        ArgumentValidator: 新建校验器实例。

    Raises:
        无。
    """
    return ArgumentValidator()


def test_validate_and_coerce_without_schema_hits_generic_limit_paths() -> None:
    """验证无 schema 时会递归执行通用限制检查并返回错误。

    Args:
        无。

    Returns:
        None。

    Raises:
        AssertionError: 当错误结构或错误原因不符合预期时抛出。
    """
    validator = _build_validator()
    payload = {
        "outer": {
            "inner": "x" * (validator.SCHEMA_MAX_STRING_LENGTH + 1),
        }
    }

    result = validator.validate_and_coerce(payload, parameters=None)

    assert result["ok"] is False
    issues = result["meta"]["issues"]
    assert issues[0]["reason"] == "string_too_long"
    assert issues[0]["path"] == "$.outer.inner"
    assert "Shorten $.outer.inner" in result["hint"]
    assert validate_tool_result_contract(result) is None


def test_validate_and_coerce_without_schema_returns_success_for_valid_payload() -> None:
    """验证无 schema 且参数未超限时直接返回成功结果。

    Args:
        无。

    Returns:
        None。

    Raises:
        AssertionError: 当返回值与预期不一致时抛出。
    """
    validator = _build_validator()
    payload = {"ok": "short"}

    result = validator.validate_and_coerce(payload, parameters=cast(Any, "invalid schema object"))

    assert result == {"ok": True, "arguments": payload}


def test_coerce_value_with_none_type_checks_limits_and_enum() -> None:
    """验证 schema 未声明 type 时的限制检查与 enum 分支。

    Args:
        无。

    Returns:
        None。

    Raises:
        AssertionError: 当校验结果不符合预期时抛出。
    """
    validator = _build_validator()

    ok_enum, _, issues_enum = validator._coerce_value("A", {"enum": ["B"]}, path="$")
    assert ok_enum is False
    assert issues_enum[0]["reason"] == "enum_mismatch"

    too_long = "x" * (validator.SCHEMA_MAX_STRING_LENGTH + 1)
    ok_long, _, issues_long = validator._coerce_value(too_long, {}, path="$")
    assert ok_long is False
    assert issues_long[0]["reason"] == "string_too_long"

    ok_plain, coerced_plain, issues_plain = validator._coerce_value("ok", {}, path="$")
    assert ok_plain is True
    assert coerced_plain == "ok"
    assert issues_plain == []


def test_coerce_value_for_numeric_and_boolean_edge_cases() -> None:
    """验证 integer/number/boolean 的关键边界输入分支。

    Args:
        无。

    Returns:
        None。

    Raises:
        AssertionError: 当类型转换行为不符合预期时抛出。
    """
    validator = _build_validator()

    ok_bool_int, _, issues_bool_int = validator._coerce_value_for_type(True, {"type": "integer"}, path="$")
    assert ok_bool_int is False
    assert issues_bool_int[0]["expected"] == "integer"

    ok_float_int, coerced_float_int, _ = validator._coerce_value_for_type(2.0, {"type": "integer"}, path="$")
    assert ok_float_int is True
    assert coerced_float_int == 2

    ok_list_int, _, issues_list_int = validator._coerce_value_for_type([1], {"type": "integer"}, path="$")
    assert ok_list_int is False
    assert issues_list_int[0]["expected"] == "integer"

    ok_bool_number, _, issues_bool_number = validator._coerce_value_for_type(False, {"type": "number"}, path="$")
    assert ok_bool_number is False
    assert issues_bool_number[0]["expected"] == "number"

    ok_int_number, coerced_int_number, _ = validator._coerce_value_for_type(3, {"type": "number"}, path="$")
    assert ok_int_number is True
    assert coerced_int_number == 3

    ok_bad_number, _, issues_bad_number = validator._coerce_value_for_type("bad", {"type": "number"}, path="$")
    assert ok_bad_number is False
    assert issues_bad_number[0]["expected"] == "number"

    ok_bool_from_int, coerced_bool_from_int, _ = validator._coerce_value_for_type(1, {"type": "boolean"}, path="$")
    assert ok_bool_from_int is True
    assert coerced_bool_from_int is True


def test_coerce_value_for_unsupported_type_returns_error() -> None:
    """验证未知 schema type 会返回 unsupported_type 错误。

    Args:
        无。

    Returns:
        None。

    Raises:
        AssertionError: 当错误类型不符合预期时抛出。
    """
    validator = _build_validator()

    ok, _, issues = validator._coerce_value_for_type("value", {"type": "mystery"}, path="$")

    assert ok is False
    assert issues[0]["reason"] == "unsupported_type"
    assert issues[0]["expected"] == "mystery"


def test_coerce_array_supports_tuple_and_rejects_non_list() -> None:
    """验证 array 分支支持 tuple 输入并拒绝非法非列表输入。

    Args:
        无。

    Returns:
        None。

    Raises:
        AssertionError: 当数组转换逻辑不符合预期时抛出。
    """
    validator = _build_validator()

    ok_tuple, coerced_tuple, issues_tuple = validator._coerce_array(
        (1, 2),
        {"type": "array", "items": {"type": "integer"}},
        path="$",
    )
    assert ok_tuple is True
    assert coerced_tuple == [1, 2]
    assert issues_tuple == []

    ok_non_list, _, issues_non_list = validator._coerce_array("not_list", {"type": "array"}, path="$")
    assert ok_non_list is False
    assert issues_non_list[0]["expected"] == "array"

    ok_no_items_schema, coerced_no_items_schema, issues_no_items_schema = validator._coerce_array(
        ["a", "b"],
        {"type": "array", "items": "invalid"},
        path="$",
    )
    assert ok_no_items_schema is True
    assert coerced_no_items_schema == ["a", "b"]
    assert issues_no_items_schema == []


def test_coerce_object_handles_defaults_and_additional_properties() -> None:
    """验证 object 分支的默认值填充、额外字段与类型错误处理。

    Args:
        无。

    Returns:
        None。

    Raises:
        AssertionError: 当对象转换结果不符合预期时抛出。
    """
    validator = _build_validator()

    ok_non_dict, _, issues_non_dict = validator._coerce_object("x", {"type": "object"}, path="$")
    assert ok_non_dict is False
    assert issues_non_dict[0]["expected"] == "object"

    ok_default, coerced_default, issues_default = validator._coerce_object(
        {},
        {
            "type": "object",
            "properties": {"name": {"type": "string", "default": "anonymous"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        path="$",
    )
    assert ok_default is True
    assert issues_default == []
    assert coerced_default["name"] == "anonymous"

    ok_additional, coerced_additional, issues_additional = validator._coerce_object(
        {"extra": 123},
        {
            "type": "object",
            "properties": "invalid_properties",
            "required": [],
            "additionalProperties": True,
        },
        path="$",
    )
    assert ok_additional is True
    assert issues_additional == []
    assert coerced_additional == {"extra": 123}


def test_object_additional_property_generic_limit_violation_returns_error() -> None:
    """验证允许额外字段时仍会执行额外字段通用限制检查。

    Args:
        无。

    Returns:
        None。

    Raises:
        AssertionError: 当额外字段超限未被识别时抛出。
    """
    validator = _build_validator()
    long_text = "x" * (validator.SCHEMA_MAX_STRING_LENGTH + 1)

    ok, _, issues = validator._coerce_object(
        {"extra": long_text},
        {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": True,
        },
        path="$",
    )

    assert ok is False
    assert issues[0]["reason"] == "string_too_long"


def test_not_stringable_number_class_exists_for_type_completeness() -> None:
    """占位测试，确保辅助类型在静态分析中被引用。

    Args:
        无。

    Returns:
        None。

    Raises:
        AssertionError: 当辅助类型无法实例化时抛出。
    """
    obj = _NotStringableNumber()
    assert isinstance(obj, _NotStringableNumber)


def test_validate_and_coerce_additional_properties_returns_repair_hint() -> None:
    """验证 additional_properties 错误会返回 drop_unsupported_fields repair_hint。"""

    validator = _build_validator()
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "document_id": {"type": "string"},
            "ref": {"type": "string"},
        },
        "required": ["ticker", "document_id", "ref"],
        "additionalProperties": False,
    }

    result = validator.validate_and_coerce(
        {
            "ticker": "AAPL",
            "document_id": "fil_1",
            "ref": "s_0001",
            "within_section_ref": "s_0002",
        },
        parameters=schema,
    )

    assert result["ok"] is False
    detail = result["meta"]
    repair_hint = detail["repair_hint"]
    assert repair_hint["action"] == "drop_unsupported_fields"
    assert repair_hint["unsupported_fields"] == ["within_section_ref"]
    assert "ticker" in repair_hint["allowed_fields"]
    assert "Remove unsupported fields and retry: within_section_ref." in result["hint"]


def test_validate_and_coerce_missing_required_returns_repair_hint() -> None:
    """验证 missing_required 错误会返回 add_required_fields repair_hint。"""

    validator = _build_validator()
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "document_id": {"type": "string"},
            "ref": {"type": "string"},
        },
        "required": ["ticker", "document_id", "ref"],
        "additionalProperties": False,
    }

    result = validator.validate_and_coerce(
        {
            "ticker": "AAPL",
            "document_id": "fil_1",
        },
        parameters=schema,
    )

    assert result["ok"] is False
    detail = result["meta"]
    repair_hint = detail["repair_hint"]
    assert repair_hint["action"] == "add_required_fields"
    assert repair_hint["required_fields"] == ["ref"]
    assert "Add required fields and retry: ref." in result["hint"]


def test_validate_and_coerce_combines_missing_and_unsupported_field_hint() -> None:
    """验证字符串 hint 会同时覆盖缺失字段与多余字段。"""

    validator = _build_validator()
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer"},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    result = validator.validate_and_coerce(
        {
            "queries": ["AAPL", "MSFT"],
            "max_results": 10,
        },
        parameters=schema,
    )

    assert result["ok"] is False
    assert "Remove unsupported fields and retry: queries." in result["hint"]
    assert "Add required fields and retry: query." in result["hint"]
    assert "Allowed fields: max_results, query." in result["hint"]
    assert validate_tool_result_contract(result) is None
