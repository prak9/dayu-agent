"""条件 PE 计算与原 invest 模型的算术一致性及输入边界。"""

from __future__ import annotations

import math
import json
from pathlib import Path
from typing import cast

import pytest

from alpha.research.methods.alpha_invest.json_values import JsonMap, JsonValue, finite_number, require_map, number
from alpha.research.methods.alpha_invest.pe_implied_growth import calculate


def _inputs() -> JsonMap:
    """构造纯假设输入。参数：无。返回：假设。异常：无。"""
    return {"base_eps": 1, "years": 5, "cost_of_equity": 0.1, "cash_conversion": 1,
            "terminal_cash_conversion": 1, "terminal_growth": 0, "growth": 0}


def test_zero_growth_perpetuity_and_inverse_round_trip() -> None:
    """零增长永续及正增长正逆算相符。参数：无。返回：无。异常：断言失败。"""
    forward = calculate(_inputs())
    assert require_map(forward["valuation"])["base_pe"] == pytest.approx(10)
    assert require_map(forward["valuation"])["price"] == pytest.approx(10)
    assumptions = {**_inputs(), "growth": 0.2, "cash_conversion": 0.4, "terminal_cash_conversion": 0.8}
    result = calculate(assumptions)
    target = require_map(result["valuation"])["base_pe"]
    inverse = {key: value for key, value in assumptions.items() if key != "growth"}
    inverse["pe"] = target
    restored = calculate(inverse)
    assert restored["growth"] == pytest.approx(0.2, abs=1e-9)
    assert restored["model_version"] == "conditional-pe-fcfe-v1"


def test_forward_pe_basis_and_sensitive_assumptions() -> None:
    """远期 EPS 桥接与敏感性保持显式。参数：无。返回：无。异常：断言失败。"""
    inverse = {key: value for key, value in _inputs().items() if key != "growth"}
    result = calculate({**inverse, "pe": 8, "pe_basis": "forward", "forward_eps_ratio": 1.25,
                        "scenarios": [{"name": "higher_rate", "overrides": {"cost_of_equity": 0.15}}]})
    assert result["target_base_pe"] == 10
    assert result["growth"] == pytest.approx(0, abs=1e-9)
    scenarios = result["scenarios"]
    assert isinstance(scenarios, list)
    scenario_result = require_map(require_map(scenarios[0])["result"])
    assert number(scenario_result["growth"], "growth") > 0


def test_unbracketed_is_not_economic_impossibility() -> None:
    """数值边界不包根明确返回状态。参数：无。返回：无。异常：断言失败。"""
    inverse = {key: value for key, value in _inputs().items() if key != "growth"}
    result = calculate({**inverse, "pe": 1000, "growth_bounds": [-0.1, 0.1]})
    assert result["status"] == "unbracketed" and result["valuation"] is None
    assert "not proof" in str(result["reason"])


def test_growth_at_discount_rate_has_no_singularity() -> None:
    """增长等于折现率时可直接求和。参数：无。返回：无。异常：断言失败。"""
    result = calculate({**_inputs(), "growth": 0.1})
    valuation = require_map(result["valuation"])
    assert valuation["period_pv_per_base_eps"] == pytest.approx(5)
    assert valuation["terminal_pv_per_base_eps"] == pytest.approx(10)
    contraction = calculate({**_inputs(), "growth": -0.1, "terminal_growth": 0.02})
    diagnostics = require_map(contraction["diagnostics"])
    assert diagnostics["contraction_then_terminal_recovery"] is True
    assert require_map(diagnostics["first_stage"])["required_incremental_equity_return"] is None


@pytest.mark.parametrize("overrides", [
    {"base_eps": None}, {"base_eps": 0}, {"base_eps": True}, {"years": 1.5}, {"years": 101},
    {"cost_of_equity": 0}, {"terminal_growth": 0.1}, {"terminal_growth": -1}, {"growth": -1},
    {"cash_conversion": -0.1}, {"terminal_cash_conversion": 1.1},
    {"cash_conversion": 0, "terminal_cash_conversion": 0}, {"growth": math.inf}, {"unknown": 1},
    {"pe": 10}, {"pe_basis": "invalid"}, {"forward_eps_ratio": 1.2}, {"pe_basis": "forward"},
    {"growth_bounds": [-0.9, 1]}, {"scenarios": {}},
    {"scenarios": [{"name": "", "overrides": {"years": 10}}]},
    {"scenarios": [{"name": "x", "overrides": {"base_eps": 2}}]},
    {"scenarios": [{"name": "x", "overrides": {} }]}, {"scenarios": ["invalid"]},
    {"scenarios": [{"name": "x"}]},
    {"scenarios": [{"name": "x", "overrides": {"years": 10}}, {"name": "x", "overrides": {"years": 20}}]},
])
def test_rejects_unknowns_incompatible_inputs_and_invalid_scenarios(overrides: JsonMap) -> None:
    """不将缺数、非法比例或混合口径静默修正。参数：覆盖输入。返回：无。异常：断言失败。"""
    with pytest.raises(ValueError):
        calculate({**_inputs(), **overrides})


@pytest.mark.parametrize("overrides", [{"pe": 0}, {"pe": 10, "growth_bounds": [1]},
                                       {"pe": 10, "growth_bounds": [0.2, 0.1]},
                                       {"pe": 10, "pe_basis": "forward", "forward_eps_ratio": 0}])
def test_inverse_input_boundaries(overrides: JsonMap) -> None:
    """逆推参数独立校验。参数：覆盖输入。返回：无。异常：断言失败。"""
    inputs = {key: value for key, value in _inputs().items() if key != "growth"}
    with pytest.raises(ValueError):
        calculate({**inputs, **overrides})


def test_json_value_boundaries_and_missing_required_fields() -> None:
    """公共 JSON 边界拒绝未验证类型。参数：无。返回：无。异常：断言失败。"""
    for raw in (None, [], "bad"):
        with pytest.raises(ValueError):
            calculate(raw)
    with pytest.raises(ValueError):
        calculate({"growth": 0})
    invalid_numbers: tuple[JsonValue, ...] = (None, "", True, [], math.nan, math.inf)
    assert all(finite_number(value) is None for value in invalid_numbers)


def test_original_invest_golden_cases() -> None:
    """冻结原 skill 脚本的纯假设输出，防止移植算术漂移。参数：无。返回：无。异常：断言失败。"""
    fixture = require_map(cast(JsonValue, json.loads((Path(__file__).parents[1] / "fixtures" / "invest" / "pe_cases.json").read_text())))
    cases = fixture["cases"]
    assert isinstance(cases, list)
    for case in cases:
        record = require_map(case)
        result = calculate(record["input"])
        assert {key: result[key] for key in ("status", "growth", "valuation")} == record["expected"]
