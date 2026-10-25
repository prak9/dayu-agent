"""
参数校验器 — 基于 JSON Schema 对工具参数做校验与强制转换

从 ToolRegistry 拆分而来，封装所有与参数校验相关的逻辑：
- 深度限制检查
- 字符串长度 / 数组大小的通用限制
- 按 schema 类型做强制类型转换
- 必填字段与默认值填充
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from alpha.engine.tool_result import build_error


class ArgumentValidator:
    """工具参数校验与强制转换器。

    负责将 LLM 传入的 arguments 按照 tool schema 做类型校验和安全截断。
    无实例状态，所有限制值均为类级常量。

    Attributes:
        SCHEMA_MAX_STRING_LENGTH: 单个字符串参数的最大长度。
        SCHEMA_MAX_ARRAY_ITEMS: 单个数组参数的最大元素数量。
        ARGUMENTS_MAX_DEPTH: 参数嵌套最大深度。
    """

    SCHEMA_MAX_STRING_LENGTH: int = 4096
    SCHEMA_MAX_ARRAY_ITEMS: int = 1000
    ARGUMENTS_MAX_DEPTH: int = 8

    def validate_and_coerce(
        self,
        arguments: Any,
        parameters: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """基于 schema 对 arguments 做校验/规整/默认值填充。

        Args:
            arguments: LLM 传入的参数（应为 dict，否则直接报错）。
            parameters: 工具 schema 中 function.parameters 部分。
                        为 ``None`` 时仅做通用限制检查。

        Returns:
            校验成功: ``{"ok": True, "arguments": coerced_dict}``
            校验失败: ``{"ok": False, "error": "<code>", "message": "...", "hint": ...}``
        """
        if not isinstance(arguments, dict):
            return self._build_argument_error(
                "arguments 必须是对象",
                [{"path": "$", "reason": "type_mismatch", "expected": "object"}],
            )

        depth = self._calculate_depth(arguments)
        if depth > self.ARGUMENTS_MAX_DEPTH:
            return self._build_argument_error(
                "arguments 结构过深",
                [{"path": "$", "reason": "depth_exceeded",
                  "max_depth": self.ARGUMENTS_MAX_DEPTH, "actual_depth": depth}],
            )

        if not isinstance(parameters, dict):
            # 无 schema 定义，仅做通用限制
            issues = self._check_generic_limits(arguments)
            if issues:
                return self._build_argument_error("arguments 超出限制", issues)
            return {"ok": True, "arguments": arguments}

        ok, coerced, issues = self._coerce_value(arguments, parameters, path="$")
        if not ok:
            return self._build_argument_error("arguments 校验失败", issues)
        return {"ok": True, "arguments": coerced}

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _build_argument_error(
        self, message: str, issues: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """构造标准参数错误结构。

        Args:
            message: 错误摘要信息。
            issues: 参数校验问题列表。

        Returns:
            标准化错误响应；在可推断修复动作时附带 `repair_hint`。

        Raises:
            无。
        """
        detail: Dict[str, Any] = {"issues": issues}
        repair_hint = self._build_repair_hint(issues)
        if repair_hint is not None:
            detail["repair_hint"] = repair_hint
        return build_error(
            "invalid_argument",
            message,
            hint=self._build_argument_hint_text(issues=issues),
            meta=detail,
        )

    def _build_argument_hint_text(self, *, issues: List[Dict[str, Any]]) -> str:
        """将结构化参数错误压缩成 LLM 易执行的字符串提示。

        Args:
            issues: 参数校验问题列表。

        Returns:
            面向 LLM 的扁平字符串提示。

        Raises:
            无。
        """
        if not issues:
            return "Fix arguments to match the tool schema and retry."

        unsupported_fields: List[str] = []
        allowed_fields: List[str] = []
        missing_required_fields: List[str] = []
        generic_messages: List[str] = []

        for issue in issues:
            reason = issue.get("reason")
            if reason == "additional_properties":
                fields = issue.get("fields")
                if isinstance(fields, list):
                    unsupported_fields.extend(str(field) for field in fields)
                allowed = issue.get("allowed_fields")
                if isinstance(allowed, list):
                    allowed_fields.extend(str(field) for field in allowed)
                continue

            if reason == "missing_required":
                path = issue.get("path")
                if isinstance(path, str) and path:
                    missing_required_fields.append(path.rsplit(".", 1)[-1])
                continue

            generic_messages.append(self._format_issue_for_hint(issue))

        hint_parts: List[str] = []
        if unsupported_fields:
            normalized_unsupported = ", ".join(sorted(set(unsupported_fields)))
            hint_parts.append(f"Remove unsupported fields and retry: {normalized_unsupported}.")
        if missing_required_fields:
            normalized_missing = ", ".join(sorted(set(missing_required_fields)))
            hint_parts.append(f"Add required fields and retry: {normalized_missing}.")
        if allowed_fields:
            normalized_allowed = ", ".join(sorted(set(allowed_fields)))
            hint_parts.append(f"Allowed fields: {normalized_allowed}.")
        hint_parts.extend(message for message in generic_messages if message)

        if hint_parts:
            return " ".join(hint_parts)
        return "Fix arguments to match the tool schema and retry."

    def _format_issue_for_hint(self, issue: Dict[str, Any]) -> str:
        """把单条 issue 格式化为简短字符串提示。

        Args:
            issue: 单条参数校验问题。

        Returns:
            单条字符串提示；无法识别时返回通用提示。

        Raises:
            无。
        """
        path = str(issue.get("path", "$"))
        reason = str(issue.get("reason", "invalid"))

        if reason == "type_mismatch":
            expected = str(issue.get("expected", "expected type"))
            return f"Set {path} to {expected} and retry."
        if reason == "enum_mismatch":
            allowed = issue.get("allowed")
            if isinstance(allowed, list) and allowed:
                rendered_allowed = ", ".join(str(item) for item in allowed)
                return f"Set {path} to one of: {rendered_allowed}."
            return f"Set {path} to an allowed value and retry."
        if reason == "string_too_long":
            max_length = issue.get("max_length")
            if max_length is not None:
                return f"Shorten {path} to at most {max_length} characters and retry."
            return f"Shorten {path} and retry."
        if reason == "string_too_short":
            min_length = issue.get("min_length")
            if min_length is not None:
                return f"Extend {path} to at least {min_length} characters and retry."
            return f"Extend {path} and retry."
        if reason == "array_too_large":
            max_items = issue.get("max_items")
            if max_items is not None:
                return f"Reduce {path} to at most {max_items} items and retry."
            return f"Reduce {path} item count and retry."
        if reason == "array_too_small":
            min_items = issue.get("min_items")
            if min_items is not None:
                return f"Expand {path} to at least {min_items} items and retry."
            return f"Expand {path} item count and retry."
        if reason == "depth_exceeded":
            max_depth = issue.get("max_depth")
            if max_depth is not None:
                return f"Reduce argument nesting to at most {max_depth} levels and retry."
            return "Reduce argument nesting depth and retry."
        if reason == "unsupported_type":
            expected = str(issue.get("expected", "supported schema type"))
            return f"Adjust {path} to a supported schema type; current schema expects {expected}."
        return f"Fix {path} ({reason}) and retry."

    def _build_repair_hint(self, issues: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """根据参数校验问题生成可执行修复提示。

        Args:
            issues: 参数校验问题列表。

        Returns:
            修复提示字典；若无法推断有效修复动作则返回 `None`。

        Raises:
            无。
        """
        if not issues:
            return None

        additional_fields: List[str] = []
        allowed_fields: List[str] = []
        missing_required_paths: List[str] = []

        for issue in issues:
            reason = issue.get("reason")
            if reason == "additional_properties":
                fields = issue.get("fields")
                if isinstance(fields, list):
                    additional_fields.extend(str(field) for field in fields)
                issue_allowed_fields = issue.get("allowed_fields")
                if isinstance(issue_allowed_fields, list):
                    allowed_fields.extend(str(field) for field in issue_allowed_fields)
            elif reason == "missing_required":
                path = issue.get("path")
                if isinstance(path, str):
                    missing_required_paths.append(path)

        if additional_fields:
            normalized_extra = sorted(set(additional_fields))
            normalized_allowed = sorted(set(allowed_fields))
            hint: Dict[str, Any] = {
                "action": "drop_unsupported_fields",
                "unsupported_fields": normalized_extra,
                "message": "Remove unsupported fields from arguments and retry.",
            }
            if normalized_allowed:
                hint["allowed_fields"] = normalized_allowed
            return hint

        if missing_required_paths:
            missing_fields = []
            for path in missing_required_paths:
                field_name = path.rsplit(".", 1)[-1]
                missing_fields.append(field_name)
            return {
                "action": "add_required_fields",
                "required_fields": sorted(set(missing_fields)),
                "message": "Add all required fields and retry.",
            }

        return None

    def _calculate_depth(self, value: Any, current: int = 1) -> int:
        """递归计算嵌套深度。"""
        if isinstance(value, dict) and value:
            return max(self._calculate_depth(v, current + 1) for v in value.values())
        if isinstance(value, list) and value:
            return max(self._calculate_depth(v, current + 1) for v in value)
        return current

    def _check_generic_limits(
        self, value: Any, path: str = "$"
    ) -> List[Dict[str, Any]]:
        """对无 schema 的值做字符串长度和数组大小的通用安全检查。"""
        issues: List[Dict[str, Any]] = []
        if isinstance(value, str):
            max_len = self.SCHEMA_MAX_STRING_LENGTH
            if len(value) > max_len:
                issues.append({
                    "path": path,
                    "reason": "string_too_long",
                    "max_length": max_len,
                    "actual_length": len(value),
                })
        elif isinstance(value, list):
            max_items = self.SCHEMA_MAX_ARRAY_ITEMS
            if len(value) > max_items:
                issues.append({
                    "path": path,
                    "reason": "array_too_large",
                    "max_items": max_items,
                    "actual_items": len(value),
                })
            for idx, item in enumerate(value):
                issues.extend(self._check_generic_limits(item, f"{path}[{idx}]"))
        elif isinstance(value, dict):
            for key, item in value.items():
                issues.extend(self._check_generic_limits(item, f"{path}.{key}"))
        return issues

    def _coerce_value(
        self,
        value: Any,
        schema: Dict[str, Any],
        *,
        path: str,
    ) -> tuple[bool, Any, List[Dict[str, Any]]]:
        """按 schema 对单个值做类型校验与转换。"""
        schema_type = schema.get("type")
        if isinstance(schema_type, list):
            # 联合类型先匹配输入本来的 JSON 类型，避免 "100"、False、null 被字符串分支改写。
            native_type = (
                "null" if value is None else "boolean" if isinstance(value, bool)
                else "integer" if isinstance(value, int) else "number" if isinstance(value, float)
                else "string" if isinstance(value, str) else "array" if isinstance(value, list)
                else "object" if isinstance(value, dict) else None
            )
            preferred = [candidate for candidate in schema_type if candidate == native_type or (native_type == "integer" and candidate == "number")]
            alternatives = [candidate for candidate in schema_type if candidate not in preferred]
            collected: List[Dict[str, Any]] = []
            for candidate in preferred + alternatives:
                ok, coerced, issues = self._coerce_value(
                    value, {**schema, "type": candidate}, path=path,
                )
                if ok:
                    return True, coerced, []
                collected.extend(issues)
            return False, None, collected

        if schema_type is None:
            # 未指定类型，仅做通用限制
            issues = self._check_generic_limits(value, path)
            if issues:
                return False, None, issues
            if "enum" in schema and value not in schema["enum"]:
                return False, None, [{
                    "path": path,
                    "reason": "enum_mismatch",
                    "allowed": schema["enum"],
                    "actual": value,
                }]
            return True, value, []

        ok, coerced, issues = self._coerce_value_for_type(value, schema, path)
        if not ok:
            return False, None, issues
        if "enum" in schema and coerced not in schema["enum"]:
            return False, None, [{
                "path": path,
                "reason": "enum_mismatch",
                "allowed": schema["enum"],
                "actual": coerced,
            }]
        return True, coerced, []

    def _coerce_value_for_type(
        self,
        value: Any,
        schema: Dict[str, Any],
        path: str,
    ) -> tuple[bool, Any, List[Dict[str, Any]]]:
        """按具体 schema type 做深层类型转换。"""
        schema_type = schema.get("type")

        if schema_type == "null":
            if value is None:
                return True, None, []
            return False, None, [{"path": path, "reason": "type_mismatch", "expected": "null"}]

        if schema_type == "string":
            if not isinstance(value, str):
                value = str(value)
            max_len = schema.get("maxLength", self.SCHEMA_MAX_STRING_LENGTH)
            min_len = schema.get("minLength")
            if min_len is not None and len(value) < min_len:
                return False, None, [{
                    "path": path,
                    "reason": "string_too_short",
                    "min_length": min_len,
                    "actual_length": len(value),
                }]
            if len(value) > max_len:
                return False, None, [{
                    "path": path,
                    "reason": "string_too_long",
                    "max_length": max_len,
                    "actual_length": len(value),
                }]
            return True, value, []

        if schema_type == "integer":
            if isinstance(value, bool):
                return False, None, [{"path": path, "reason": "type_mismatch", "expected": "integer"}]
            if isinstance(value, int):
                return True, value, []
            if isinstance(value, float) and value.is_integer():
                return True, int(value), []
            if isinstance(value, str):
                try:
                    return True, int(value), []
                except ValueError:
                    return False, None, [{"path": path, "reason": "type_mismatch", "expected": "integer"}]
            return False, None, [{"path": path, "reason": "type_mismatch", "expected": "integer"}]

        if schema_type == "number":
            if isinstance(value, bool):
                return False, None, [{"path": path, "reason": "type_mismatch", "expected": "number"}]
            if isinstance(value, (int, float)):
                return True, value, []
            if isinstance(value, str):
                try:
                    return True, float(value), []
                except ValueError:
                    return False, None, [{"path": path, "reason": "type_mismatch", "expected": "number"}]
            return False, None, [{"path": path, "reason": "type_mismatch", "expected": "number"}]

        if schema_type == "boolean":
            if isinstance(value, bool):
                return True, value, []
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in ("true", "false"):
                    return True, lowered == "true", []
            if isinstance(value, int) and value in (0, 1):
                return True, bool(value), []
            return False, None, [{"path": path, "reason": "type_mismatch", "expected": "boolean"}]

        if schema_type == "array":
            return self._coerce_array(value, schema, path)

        if schema_type == "object":
            return self._coerce_object(value, schema, path)

        return False, None, [{"path": path, "reason": "unsupported_type", "expected": schema_type}]

    def _coerce_array(
        self,
        value: Any,
        schema: Dict[str, Any],
        path: str,
    ) -> tuple[bool, Any, List[Dict[str, Any]]]:
        """校验并转换 array 类型参数。"""
        if isinstance(value, tuple):
            value = list(value)
        if not isinstance(value, list):
            return False, None, [{"path": path, "reason": "type_mismatch", "expected": "array"}]

        max_items = schema.get("maxItems", self.SCHEMA_MAX_ARRAY_ITEMS)
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            return False, None, [{
                "path": path,
                "reason": "array_too_small",
                "min_items": min_items,
                "actual_items": len(value),
            }]
        if len(value) > max_items:
            return False, None, [{
                "path": path,
                "reason": "array_too_large",
                "max_items": max_items,
                "actual_items": len(value),
            }]

        items_schema = schema.get("items")
        if not isinstance(items_schema, dict):
            return True, value, []

        coerced_items: List[Any] = []
        issues: List[Dict[str, Any]] = []
        for idx, item in enumerate(value):
            ok, coerced, item_issues = self._coerce_value(
                item, items_schema, path=f"{path}[{idx}]",
            )
            if not ok:
                issues.extend(item_issues)
            else:
                coerced_items.append(coerced)
        if issues:
            return False, None, issues
        return True, coerced_items, []

    def _coerce_object(
        self,
        value: Any,
        schema: Dict[str, Any],
        path: str,
    ) -> tuple[bool, Any, List[Dict[str, Any]]]:
        """校验并转换 object 类型参数。"""
        if not isinstance(value, dict):
            return False, None, [{"path": path, "reason": "type_mismatch", "expected": "object"}]

        properties = schema.get("properties", {})
        required = schema.get("required", [])
        allow_additional = schema.get("additionalProperties", False)
        if not isinstance(properties, dict):
            properties = {}

        issues: List[Dict[str, Any]] = []
        coerced_obj: Dict[str, Any] = {}

        # 检查必填字段
        for key in required:
            if key not in value:
                default = properties.get(key, {}).get("default")
                if default is not None:
                    coerced_obj[key] = default
                else:
                    issues.append({
                        "path": f"{path}.{key}",
                        "reason": "missing_required",
                    })

        # 按 schema 逐字段校验
        for key, prop_schema in properties.items():
            if key in value:
                ok, coerced, prop_issues = self._coerce_value(
                    value[key], prop_schema, path=f"{path}.{key}",
                )
                if not ok:
                    issues.extend(prop_issues)
                else:
                    coerced_obj[key] = coerced
            else:
                default = prop_schema.get("default")
                if default is not None:
                    coerced_obj[key] = default

        # 额外字段处理
        extra_keys = [k for k in value.keys() if k not in properties]
        if extra_keys and not allow_additional:
            issues.append({
                "path": path,
                "reason": "additional_properties",
                "fields": extra_keys,
                "allowed_fields": sorted(properties.keys()),
            })
        elif extra_keys and allow_additional:
            for key in extra_keys:
                extra_issues = self._check_generic_limits(value[key], f"{path}.{key}")
                if extra_issues:
                    issues.extend(extra_issues)
                else:
                    coerced_obj[key] = value[key]

        if issues:
            return False, None, issues
        return True, coerced_obj, []
