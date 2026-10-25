"""tool_result 模块单元测试。

覆盖：
- 装信封：build_success / build_error
- 拆信封：is_tool_success / get_error_code / get_error_message / get_value
- LLM 投影：project_for_llm
"""

import json

import pytest

from alpha.engine.tool_result import (
    build_error,
    build_success,
    get_error_code,
    get_error_message,
    get_value,
    is_tool_success,
    project_for_llm,
    validate_tool_result_contract,
)


# ── 装信封 ────────────────────────────────────────────────


class TestBuildSuccess:
    """build_success 构造测试。"""

    def test_minimal(self):
        result = build_success({"name": "AAPL"})
        assert result == {"ok": True, "value": {"name": "AAPL"}}

    def test_with_truncation(self):
        trunc = {"next_action": "fetch_more", "fetch_more_args": {"offset": 100}}
        result = build_success("text", truncation=trunc)
        assert result["ok"] is True
        assert result["value"] == "text"
        assert result["truncation"] == trunc

    def test_with_meta(self):
        result = build_success([], meta={"elapsed": 0.5})
        assert result["meta"] == {"elapsed": 0.5}

    def test_empty_truncation_omitted(self):
        """空 truncation 不出现在信封中。"""
        result = build_success("ok", truncation={})
        assert "truncation" not in result


class TestBuildError:
    """build_error 构造测试。"""

    def test_minimal(self):
        result = build_error("not_found", "文件不存在")
        assert result == {"ok": False, "error": "not_found", "message": "文件不存在"}

    def test_with_hint_and_extra(self):
        result = build_error("rate_limited", "限流", hint="等 30 秒后重试", retryable=True)
        assert result["hint"] == "等 30 秒后重试"
        assert result["retryable"] is True

    def test_with_meta(self):
        result = build_error("tool_execution_timeout", "超时", meta={"elapsed": 30})
        assert result["meta"] == {"elapsed": 30}


# ── 拆信封 ────────────────────────────────────────────────


class TestIsToolSuccess:
    """is_tool_success 判定测试。"""

    def test_true_for_success(self):
        assert is_tool_success({"ok": True, "value": {}}) is True

    def test_false_for_error(self):
        assert is_tool_success({"ok": False, "error": "X", "message": "y"}) is False

    def test_false_for_non_dict(self):
        assert is_tool_success("not a dict") is False

    def test_false_for_missing_ok(self):
        assert is_tool_success({"value": 1}) is False


class TestGetErrorCode:
    """get_error_code 提取测试。"""

    def test_returns_code(self):
        assert get_error_code({"ok": False, "error": "tool_execution_timeout", "message": "t"}) == "tool_execution_timeout"

    def test_none_for_success(self):
        assert get_error_code({"ok": True, "value": {}}) is None

    def test_none_for_non_dict(self):
        assert get_error_code(42) is None

    def test_none_for_empty_code(self):
        assert get_error_code({"ok": False, "error": "  ", "message": "t"}) is None


class TestGetErrorMessage:
    """get_error_message 提取测试。"""

    def test_returns_message(self):
        assert get_error_message({"ok": False, "error": "E", "message": "详情"}) == "详情"

    def test_none_for_success(self):
        assert get_error_message({"ok": True, "value": {}}) is None


class TestGetValue:
    """get_value 提取测试。"""

    def test_returns_value(self):
        assert get_value({"ok": True, "value": [1, 2, 3]}) == [1, 2, 3]

    def test_none_for_error(self):
        assert get_value({"ok": False, "error": "E", "message": "m"}) is None

    def test_none_for_non_dict(self):
        assert get_value("string") is None

    def test_returns_none_value(self):
        """value 字段本身为 None 时返回 None。"""
        assert get_value({"ok": True, "value": None}) is None


class TestValidateToolResultContract:
    """validate_tool_result_contract 校验测试。"""

    def test_accepts_success_and_error_envelope(self):
        assert validate_tool_result_contract(build_success({"a": 1})) is None
        assert validate_tool_result_contract(build_error("err", "msg")) is None

    def test_rejects_legacy_success_shape(self):
        error = validate_tool_result_contract({"success": True, "data": {"x": 1}})
        assert error == 'tool result must contain boolean field "ok"'

    def test_rejects_missing_value_on_success(self):
        error = validate_tool_result_contract({"ok": True})
        assert error == 'successful tool result must contain field "value"'


# ── LLM 投影 ─────────────────────────────────────────────


class TestProjectForLlm:
    """project_for_llm 投影测试。"""

    def test_error_projection(self):
        """错误结果只保留 error/message/hint。"""
        result = build_error("tool_execution_timeout", "超时", hint="重试", retryable=True)
        proj = project_for_llm(result)
        assert proj == {"error": "tool_execution_timeout", "message": "超时", "hint": "重试"}
        assert "retryable" not in proj

    def test_success_dict_flatten(self):
        """value 为 dict 时展开到顶层。"""
        result = build_success({"name": "AAPL", "price": 150})
        proj = project_for_llm(result)
        assert proj == {"name": "AAPL", "price": 150}
        assert "ok" not in proj
        assert "value" not in proj

    def test_success_text_wrap(self):
        """value 为非 dict 时包装在 content 中。"""
        result = build_success("一段文本")
        proj = project_for_llm(result)
        assert proj == {"content": "一段文本"}

    def test_truncation_filter(self):
        """truncation 只保留 LLM 可执行字段。"""
        trunc = {
            "next_action": "fetch_more",
            "fetch_more_args": {"offset": 100},
            "internal_debug": "should_be_removed",
        }
        result = build_success({}, truncation=trunc)
        proj = project_for_llm(result)
        assert proj["truncation"] == {
            "next_action": "fetch_more",
            "fetch_more_args": {"offset": 100},
        }
        assert "internal_debug" not in proj.get("truncation", {})

    def test_budget_injection(self):
        """budget 追加到投影中。"""
        result = build_success({"k": "v"})
        proj = project_for_llm(result, budget=5)
        assert proj["tool_calls_remaining"] == 5

    def test_budget_on_error(self):
        """错误投影也带 budget。"""
        result = build_error("err", "msg")
        proj = project_for_llm(result, budget=3)
        assert proj["tool_calls_remaining"] == 3

    def test_no_truncation_key_when_empty(self):
        """truncation 内无 LLM 字段时不出现 truncation 键。"""
        result = build_success({}, truncation={"internal_only": 1})
        proj = project_for_llm(result)
        assert "truncation" not in proj

    def test_no_budget_when_none(self):
        """budget=None 时不出现 tool_calls_remaining。"""
        result = build_success({})
        proj = project_for_llm(result)
        assert "tool_calls_remaining" not in proj

    def test_error_missing_hint_omitted(self):
        """没有 hint 的错误投影不出现 hint 键。"""
        result = build_error("err", "msg")
        proj = project_for_llm(result)
        assert "hint" not in proj

    def test_bytes_projection_uses_base64_shape(self):
        """bytes 投影为固定 base64 结构，且可 JSON 序列化。"""
        result = build_success(b"abc")
        proj = project_for_llm(result)
        assert proj["content_base64"] == "YWJj"
        assert proj["content_encoding"] == "base64"
        json.dumps(proj, ensure_ascii=False)

    def test_tuple_and_set_projection_are_json_safe(self):
        """tuple/set 投影为稳定 JSON-safe 结构。"""
        result = build_success({"items": (1, 2), "tags": {"b", "a"}})
        proj = project_for_llm(result)
        assert proj["items"] == [1, 2]
        assert proj["tags"] == ["a", "b"]
        json.dumps(proj, ensure_ascii=False)

    def test_invalid_contract_projects_to_invalid_result(self):
        """非法信封投影为 invalid_result，而不是隐式兼容旧口径。"""
        proj = project_for_llm({"success": True, "data": {"value": "x"}})
        assert proj["error"] == "invalid_result"
