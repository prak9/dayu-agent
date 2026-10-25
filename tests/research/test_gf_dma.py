"""GF-DMA 模块的缺数、门槛及总分禁用测试。"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import cast

import pytest

from alpha.research.methods.alpha_invest.gf_dma import calculate
from alpha.research.methods.alpha_invest.json_values import JsonMap, JsonValue, require_map


def _inputs() -> JsonMap:
    """构造纯假设模块。参数：无。返回：输入。异常：无。"""
    return {
        "growth_match": {"fundamental_speed_63d": 0.2, "dma_speeds_63d": {"50": 0.18, "100": 0.22}},
        "divergence": {"d20": 0.03, "d50": 0.1, "d100": 0.2, "d200": 0.3, "z20": 0.5,
                       "fundamentals_stable_or_improving": True, "revisions_nonnegative": True},
        "parallel": {"price_daily_slope_5d": 0.001, "dma50_daily_slope_5d": 0.001},
        "revision": {"revenue_30d": 0.05, "eps_30d": 0.05, "guide_vs_consensus": 0.05},
    }


def _module(inputs: JsonMap, name: str) -> JsonMap:
    """读取单模块输出。参数：输入、模块名。返回：输出。异常：输入非法。"""
    return require_map(require_map(calculate(inputs)["modules"])[name])


def test_all_inputs_still_do_not_enable_aggregate() -> None:
    """模块齐全也不制造未经校准的总分。参数：无。返回：无。异常：断言失败。"""
    result = calculate(_inputs())
    assert result["heuristic_version"] == "gf-dma-v1"
    assert result["aggregate_enabled"] is False and result["scorable"] is False
    assert result["health_score"] is None and result["state"] == "N/A"
    assert result["missing_modules"] == []
    assert _module(_inputs(), "growth_match")["score"] == 100
    assert _module(_inputs(), "parallel")["score"] == 100
    assert _module(_inputs(), "revision")["score"] == 85


def test_unknowns_remain_unscored() -> None:
    """空输入不退化成零值。参数：无。返回：无。异常：断言失败。"""
    result = calculate({})
    assert set(cast(list[str], result["missing_modules"])) == {"growth_match", "divergence", "parallel", "revision"}
    with pytest.raises(ValueError):
        calculate([])


@pytest.mark.parametrize("module,values", [
    ("growth_match", []), ("growth_match", {"fundamental_speed_63d": None}),
    ("growth_match", {"fundamental_speed_63d": 0}),
    ("growth_match", {"fundamental_speed_63d": 0.2}),
    ("growth_match", {"fundamental_speed_63d": 0.2, "dma_speeds_63d": {"50": 0.1}}),
    ("parallel", {"price_daily_slope_5d": math.nan}),
    ("parallel", {"price_daily_slope_5d": -0.2, "dma50_daily_slope_5d": 0.001}),
    ("parallel", {"price_daily_slope_5d": 0.01, "dma50_daily_slope_5d": 0.000001}),
    ("parallel", {"price_daily_slope_5d": -0.01, "dma50_daily_slope_5d": -0.001}),
    ("revision", {"revenue_30d": 0.01}),
    ("divergence", {"d20": 0.1}),
    ("divergence", {"d20": 0.1, "d50": 0, "d100": 0, "d200": 0, "z20": 1}),
    ("divergence", {"d20": -1, "d50": 0, "d100": 0, "d200": 0, "z20": -1,
                    "fundamentals_stable_or_improving": True, "revisions_nonnegative": True}),
    ("divergence", {"d20": 0.1, "d50": 0, "d100": 0, "d200": 0, "z20": -1,
                    "fundamentals_stable_or_improving": True, "revisions_nonnegative": True}),
])
def test_invalid_module_domains_return_na(module: str, values: JsonValue) -> None:
    """不符合模块域的观测不估分。参数：模块名、值。返回：无。异常：断言失败。"""
    result = _module({**_inputs(), module: values}, module)
    assert result["score"] is None and result["reason"]


@pytest.mark.parametrize("ratio,expected", [(-2, 10), (0.25, 55), (0.9, 95), (1.15, 95), (1.65, 75), (3, 26.67), (5, 10)])
def test_growth_interpolation_boundaries(ratio: float, expected: float) -> None:
    """锚点中间值与上下界可核查。参数：比率、预期。返回：无。异常：断言失败。"""
    result = _module({"growth_match": {"fundamental_speed_63d": 0.2, "dma_speeds_63d": {"50": 0.2 * ratio, "100": 0.2 * ratio}}}, "growth_match")
    assert result["score"] == pytest.approx(expected)


def test_pullback_gates_distinguish_health_from_breakdown() -> None:
    """同价格回撤因基本面门槛不同而有明确不同解释。参数：无。返回：无。异常：断言失败。"""
    divergence: JsonMap = {"d20": -0.03, "d50": -0.05, "d100": 0.1, "d200": 0.2, "z20": -1,
                           "fundamentals_stable_or_improving": True, "revisions_nonnegative": True}
    healthy = _module({"divergence": divergence}, "divergence")
    broken = _module({"divergence": {**divergence, "revisions_nonnegative": False}}, "divergence")
    assert require_map(healthy["observations"])["pullback_bonus"] == 5
    assert require_map(broken["observations"])["breakdown_penalty"] == 5
    stretched = _module({"divergence": {**divergence, "d20": 0.3, "d50": 0.5, "d100": 0.8, "d200": 1.5, "z20": 5}}, "divergence")
    assert stretched["score"] == 0


def test_original_invest_golden_cases() -> None:
    """冻结原 skill 模块结果，防止锚点迁移漂移。参数：无。返回：无。异常：断言失败。"""
    fixture = require_map(cast(JsonValue, json.loads((Path(__file__).parents[1] / "fixtures" / "invest" / "gf_dma_cases.json").read_text())))
    cases = fixture["cases"]
    assert isinstance(cases, list)
    for value in cases:
        case = require_map(value)
        assert calculate(case["input"]) == case["expected"]
