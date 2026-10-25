"""invest 数据契约迁移的冻结行为与缺数、口径、时点校验。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from alpha.research.methods.alpha_invest.json_values import JsonMap, JsonValue, require_map
from alpha.research.methods.alpha_invest.validate_data import validate


def _metric(metric_id: str, value: JsonValue) -> JsonMap:
    """构造纯假设来源记录。参数：指标 ID、值。返回：记录。异常：无。"""
    return {
        "id": metric_id, "name": metric_id, "value": value, "unit": "USD million", "currency": "USD",
        "period": "FY2023", "basis": "GAAP", "classification": "reported_fact", "missing_reason": None,
        "source": {"reference": "https://example.com/filing", "document_type": "10-K",
                   "published_at": "2024-02-01T10:00:00Z", "available_at": "2024-02-01T12:00:00Z", "locator": "p. 42"},
    }


def _codes(result: JsonMap) -> set[str]:
    """提取结构化问题码。参数：校验结果。返回：代码集合。异常：结果结构非法。"""
    findings = result["findings"]
    assert isinstance(findings, list)
    return {str(require_map(item)["code"]) for item in findings}


def test_original_invest_validator_cases() -> None:
    """原 skill 测试的冻结输入输出保持一致。参数：无。返回：无。异常：断言失败。"""
    fixture = require_map(cast(JsonValue, json.loads((Path(__file__).parents[1] / "fixtures" / "invest" / "validation_cases.json").read_text())))
    cases = fixture["cases"]
    assert isinstance(cases, list)
    for raw in cases:
        case = require_map(raw)
        assert validate(require_map(case["input"])) == case["expected"], case["test"]


@pytest.mark.parametrize("field,value,code", [
    ("id", "", "invalid_id"), ("name", "", "invalid_name"), ("unit", "", "invalid_unit"),
    ("period", "", "invalid_period"), ("basis", "", "invalid_basis"),
    ("currency", [], "invalid_currency"), ("classification", "unknown", "invalid_classification"),
    ("value", "100", "invalid_value"), ("value", None, "missing_reason_required"),
    ("source", None, "missing_source"),
])
def test_invalid_metric_fields_become_findings(field: str, value: JsonValue, code: str) -> None:
    """坏字段不被自动转为有效数字或零。参数：字段、值、代码。返回：无。异常：断言失败。"""
    result = validate({"metrics": [{**_metric("x", 100), field: value}]})
    assert result["status"] == "fail" and code in _codes(result)


@pytest.mark.parametrize("field,value,code", [
    ("reference", "", "invalid_source_reference"), ("document_type", "", "invalid_source_document_type"),
    ("locator", [], "invalid_source_locator"), ("published_at", None, "invalid_published_at"),
    ("available_at", "2024-01-01T12:00:00Z", "availability_before_publication"),
])
def test_invalid_source_fields_remain_visible(field: str, value: JsonValue, code: str) -> None:
    """来源缺口不被隐藏。参数：字段、值、代码。返回：无。异常：断言失败。"""
    metric = _metric("x", 100)
    source = require_map(metric["source"])
    result = validate({"metrics": [{**metric, "source": {**source, field: value}}]})
    assert result["status"] == "fail" and code in _codes(result)


@pytest.mark.parametrize("check_name,code", [
    ("sums", "invalid_sums"), ("growth_rates", "invalid_growth_rates"),
    ("probability_groups", "invalid_probability_groups"), ("basis_groups", "invalid_basis_groups"),
    ("period_differences", "invalid_period_differences"),
])
def test_malformed_check_containers_fail(check_name: str, code: str) -> None:
    """坏校验容器不被跳过后标通过。参数：校验名、代码。返回：无。异常：断言失败。"""
    result = validate({"schema_version": 2, "metrics": [_metric("x", 1)], "checks": {check_name: {}}})
    assert result["status"] == "fail" and code in _codes(result)


@pytest.mark.parametrize("check_name,code", [
    ("sums", "invalid_sum_check"), ("growth_rates", "invalid_growth_check"),
    ("probability_groups", "invalid_probability_check"), ("basis_groups", "invalid_basis_check"),
    ("period_differences", "invalid_difference"),
])
def test_malformed_check_items_fail(check_name: str, code: str) -> None:
    """坏校验项输出可定位问题。参数：校验名、代码。返回：无。异常：断言失败。"""
    result = validate({"schema_version": 2, "metrics": [_metric("x", 1)], "checks": {check_name: [None]}})
    assert result["status"] == "fail" and code in _codes(result)
