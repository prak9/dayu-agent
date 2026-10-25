"""风险中性离散分布的无套利、口径与浮点边界测试。"""

from __future__ import annotations

import math

import pytest

from alpha.research.methods.alpha_invest.json_values import JsonMap, number, require_map
from alpha.research.methods.alpha_invest.option_distribution import calculate


def _inputs() -> JsonMap:
    """构造无真实标的的纯假设网格。参数：无。返回：输入。异常：无。"""
    return {"quote_timestamp": "2026-01-01T12:00:00Z", "expiration": "2027-01-01", "spot": 100,
            "risk_free_rate": 0, "option_style": "european_equivalent", "price_basis": "synthetic split-adjusted common-share basis",
            "calls": [{"strike": 80, "call_price": 30}, {"strike": 100, "call_price": 20}, {"strike": 120, "call_price": 14}]}


def test_discrete_distribution_conserves_mass_and_exposes_risk_neutral_scope() -> None:
    """价差概率和区间质量相符且和为一。参数：无。返回：无。异常：断言失败。"""
    result = calculate(_inputs())
    thresholds = result["threshold_probabilities"]
    buckets = result["range_probabilities"]
    assert isinstance(thresholds, list) and isinstance(buckets, list)
    assert [require_map(value)["probability_above"] for value in thresholds] == pytest.approx([0.5, 0.3])
    assert [require_map(value)["probability"] for value in buckets] == pytest.approx([0.5, 0.2, 0.3])
    assert sum(number(require_map(value)["probability"], "probability") for value in buckets) == pytest.approx(1)
    assert result["horizon_note"] == "approximately_one_year"
    assert "not objective" in str(result["interpretation"])
    assert "internal distribution is not estimated" in str(result["tail_note"])


def test_rate_discount_sorted_grid_and_shorter_horizon() -> None:
    """显式折现、排序和非一年期限标签可复算。参数：无。返回：无。异常：断言失败。"""
    inputs = _inputs()
    grid = inputs["calls"]
    assert isinstance(grid, list)
    result = calculate({**inputs, "risk_free_rate": 0.05, "expiration": "2026-07-01", "calls": list(reversed(grid))})
    assert result["horizon_note"] == "outside_9_to_15_month_window"
    normalized = require_map(result["inputs"])
    assert normalized["calls"] == grid
    thresholds = result["threshold_probabilities"]
    assert isinstance(thresholds, list)
    expected_tail = math.exp(0.05 * 181 / 365.25) * 0.5
    assert require_map(thresholds[0])["probability_above"] == pytest.approx(expected_tail)


def test_rounding_noise_cannot_produce_negative_bucket_probability() -> None:
    """容差内凸性噪声不得变成负概率。参数：无。返回：无。异常：断言失败。"""
    result = calculate({**_inputs(), "calls": [
        {"strike": 80, "call_price": 30}, {"strike": 100, "call_price": 20},
        {"strike": 120, "call_price": 9.9999999999},
    ]})
    buckets = result["range_probabilities"]
    assert isinstance(buckets, list)
    probabilities = [number(require_map(value)["probability"], "probability") for value in buckets]
    assert min(probabilities) >= 0 and sum(probabilities) == pytest.approx(1)
    assert require_map(result["rounding_adjustment"])["monotonic_tail_clamp"] is True


@pytest.mark.parametrize("overrides", [
    {"quote_timestamp": None}, {"quote_timestamp": "invalid"}, {"quote_timestamp": "2026-01-01T12:00:00"},
    {"expiration": None}, {"expiration": "invalid"}, {"expiration": "2025-01-01"}, {"spot": 0},
    {"spot": None}, {"spot": True}, {"risk_free_rate": math.nan}, {"option_style": "american"},
    {"option_style": []}, {"price_basis": ""}, {"calls": []}, {"calls": {}}, {"unknown": 1},
    {"calls": [None, {}, {}]},
    {"calls": [{"strike": 80, "call_price": 30}, {"strike": 100, "call_price": 20}, {"strike": 120}]},
    {"calls": [{"strike": 0, "call_price": 30}, {"strike": 100, "call_price": 20}, {"strike": 120, "call_price": 14}]},
    {"calls": [{"strike": 80, "call_price": -1}, {"strike": 100, "call_price": 20}, {"strike": 120, "call_price": 14}]},
    {"calls": [{"strike": 100, "call_price": 30}, {"strike": 100, "call_price": 20}, {"strike": 120, "call_price": 14}]},
    {"calls": [{"strike": 80, "call_price": 30}, {"strike": 100, "call_price": 25}, {"strike": 120, "call_price": 10}]},
    {"calls": [{"strike": 80, "call_price": 10}, {"strike": 100, "call_price": 20}, {"strike": 120, "call_price": 5}]},
])
def test_rejects_unusable_quotes_and_incompatible_basis(overrides: JsonMap) -> None:
    """缺失或套利网格不生成概率。参数：覆盖输入。返回：无。异常：断言失败。"""
    with pytest.raises(ValueError):
        calculate({**_inputs(), **overrides})


def test_missing_required_fields_and_non_mapping() -> None:
    """输入结构必须完整。参数：无。返回：无。异常：断言失败。"""
    with pytest.raises(ValueError):
        calculate({})
    with pytest.raises(ValueError):
        calculate([])
