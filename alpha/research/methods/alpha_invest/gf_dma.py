"""invest GF-DMA v1 的确定模块映射；未经校准的总分始终禁用。"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .json_values import JsonMap, JsonValue, finite_number, require_map

MODEL_VERSION = "gf-dma-v1"
_SLOPE_EPSILON = 0.00001
_GROWTH_EPSILON = 0.01
_SCORE_MAX = 100.0
_SCORE_PRECISION = 2
_RATIO_PRECISION = 6
_DIVERGENCE_BASE_SCORE = 90.0
_PULLBACK_BONUS = 5.0
_HEALTHY_PULLBACK_MINIMUM = -0.15
_MIN_REVISION_INPUTS = 2
_MIN_FIVE_DAY_DAILY_SLOPE = -0.2
_DIVERGENCE_NAMES = ("d20", "d50", "d100", "d200", "z20")
_GROWTH_ANCHORS = ((-1.0, 10.0), (0.0, 35.0), (0.5, 75.0), (0.8, 90.0), (1.0, 100.0), (1.3, 90.0), (2.0, 60.0), (2.5, 35.0), (4.0, 10.0))
_PARALLEL_ANCHORS = ((-1.0, 10.0), (0.0, 30.0), (0.5, 60.0), (0.8, 85.0), (1.0, 100.0), (1.2, 90.0), (1.8, 65.0), (2.5, 35.0), (4.0, 10.0))
_REVISION_ANCHORS = ((-0.10, 10.0), (-0.05, 35.0), (0.0, 60.0), (0.05, 85.0), (0.10, 100.0))
_STRETCH_ANCHORS = {
    "d20": ((0.05, 0.0), (0.12, 15.0), (0.20, 35.0), (0.40, 60.0)),
    "d50": ((0.30, 0.0), (0.50, 20.0)),
    "d100": ((0.50, 0.0), (0.80, 15.0)),
    "d200": ((1.00, 0.0), (1.50, 10.0)),
    "z20": ((2.0, 0.0), (3.0, 10.0), (4.0, 20.0), (5.0, 35.0)),
}
_BREAKDOWN_CAPS = {"d50": 25.0, "d100": 20.0, "d200": 25.0}
_BREAKDOWN_SCALE = 100.0


@dataclass(frozen=True)
class _Module:
    """单模块观测与未经校准的启发式分数。"""

    score: float | None
    reason: str
    observations: JsonMap


def _section(data: JsonMap, name: str) -> JsonMap:
    """读取可选模块输入。参数：数据、模块名。返回：对象或空。异常：无。"""
    value = data.get(name)
    return value if isinstance(value, dict) else {}


def _interpolate(value: float, anchors: tuple[tuple[float, float], ...]) -> float:
    """在版本化锚点间插值并截断边界。参数：值、锚点。返回：分数。异常：锚点无区间时 AssertionError。"""
    if value <= anchors[0][0]:
        return anchors[0][1]
    if value >= anchors[-1][0]:
        return anchors[-1][1]
    for (left, left_value), (right, right_value) in zip(anchors, anchors[1:]):
        if left <= value <= right:
            return left_value + (value - left) / (right - left) * (right_value - left_value)
    raise AssertionError("unreachable interpolation range")


def _module(score: float, reason: str, observations: JsonMap) -> _Module:
    """按版本精度限制分数。参数：分数、解释、观测。返回：模块。异常：无。"""
    return _Module(round(min(_SCORE_MAX, max(0.0, score)), _SCORE_PRECISION), reason, observations)


def _growth_match(data: JsonMap) -> _Module:
    """计算基本面与均线速度比。参数：模块集合。返回：模块。异常：无。"""
    values = _section(data, "growth_match")
    fundamental = finite_number(values.get("fundamental_speed_63d"))
    speeds = values.get("dma_speeds_63d")
    if fundamental is None:
        return _Module(None, "fundamental_speed_63d is missing or non-finite", {})
    if fundamental <= _GROWTH_EPSILON:
        return _Module(None, "fundamental speed is non-positive or too close to zero for a stable ratio", {"fundamental_speed_63d": fundamental})
    if not isinstance(speeds, dict):
        return _Module(None, "dma_speeds_63d must contain comparable 50 and 100 values", {})
    dma50, dma100 = finite_number(speeds.get("50")), finite_number(speeds.get("100"))
    if dma50 is None or dma100 is None:
        return _Module(None, "both 50DMA and 100DMA 63-day speeds are required", {})
    ratio50, ratio100 = dma50 / fundamental, dma100 / fundamental
    primary = statistics.median((ratio50, ratio100))
    return _module(_interpolate(primary, _GROWTH_ANCHORS),
                   "median 50/100DMA speed divided by positive comparable fundamental speed", {
                       "fundamental_speed_63d": fundamental, "dma_speeds_63d": {"50": dma50, "100": dma100},
                       "ratios": {"50": round(ratio50, _RATIO_PRECISION), "100": round(ratio100, _RATIO_PRECISION)},
                       "primary_ratio": round(primary, _RATIO_PRECISION),
                   })


def _divergence(data: JsonMap) -> _Module:
    """计算伸展与回撤映射并校验基本面门槛。参数：模块集合。返回：模块。异常：无。"""
    values = _section(data, "divergence")
    numbers: dict[str, float] = {}
    missing: list[str] = []
    for name in _DIVERGENCE_NAMES:
        value = finite_number(values.get(name))
        if value is None:
            missing.append(name)
        else:
            numbers[name] = value
    if missing:
        return _Module(None, "missing or non-finite divergence inputs: " + ", ".join(missing), {})
    stable, revisions = values.get("fundamentals_stable_or_improving"), values.get("revisions_nonnegative")
    if not isinstance(stable, bool) or not isinstance(revisions, bool):
        return _Module(None, "both divergence fundamental/revision gates must be boolean", {})
    observations: JsonMap = {key: value for key, value in numbers.items()}
    invalid = [name for name in _DIVERGENCE_NAMES[:-1] if numbers[name] <= -1.0]
    if invalid:
        return _Module(None, "positive price and SMA require decimal divergence > -1: " + ", ".join(invalid), observations)
    d20, d50, d100, d200, z20 = (numbers[name] for name in _DIVERGENCE_NAMES)
    if (d20 > 0) != (z20 > 0) or (d20 < 0) != (z20 < 0):
        return _Module(None, "d20 and z20 must have the same sign, including zero, for positive SMA20/ATR20", observations)
    penalties = {name: _interpolate(numbers[name], anchors) for name, anchors in _STRETCH_ANCHORS.items()}
    bonus, breakdown = 0.0, 0.0
    if stable and revisions:
        if (d20 < 0 <= d50) or (_HEALTHY_PULLBACK_MINIMUM <= d50 < 0 and d100 >= 0 and d200 >= 0):
            bonus = _PULLBACK_BONUS
    else:
        breakdown = sum(min(cap, max(0.0, -numbers[name]) * _BREAKDOWN_SCALE) for name, cap in _BREAKDOWN_CAPS.items())
    observations.update({
        "fundamentals_stable_or_improving": stable, "revisions_nonnegative": revisions,
        "penalties": {key: round(value, _SCORE_PRECISION) for key, value in penalties.items()},
        "breakdown_penalty": round(breakdown, _SCORE_PRECISION), "pullback_bonus": bonus,
    })
    return _module(_DIVERGENCE_BASE_SCORE - sum(penalties.values()) - breakdown + bonus,
                   "versioned price/DMA/ATR stretch and pullback mapping", observations)


def _parallel(data: JsonMap) -> _Module:
    """计算相对正斜率均线的速度。参数：模块集合。返回：模块。异常：无。"""
    values = _section(data, "parallel")
    price_slope, dma_slope = finite_number(values.get("price_daily_slope_5d")), finite_number(values.get("dma50_daily_slope_5d"))
    if price_slope is None or dma_slope is None:
        return _Module(None, "both normalized five-day daily slopes are required", {})
    observations: JsonMap = {"price_daily_slope_5d": price_slope, "dma50_daily_slope_5d": dma_slope}
    invalid = [name for name, value in (("price_daily_slope_5d", price_slope), ("dma50_daily_slope_5d", dma_slope))
               if value <= _MIN_FIVE_DAY_DAILY_SLOPE]
    if invalid:
        return _Module(None, "positive price and SMA require normalized five-day daily slope > -0.2: " + ", ".join(invalid), observations)
    if abs(dma_slope) <= _SLOPE_EPSILON:
        return _Module(None, "50DMA daily slope is near zero; EscapeRatio is unstable", observations)
    if dma_slope < 0:
        return _Module(None, "parallel-health scoring requires a positive 50DMA slope; two negative slopes are not healthy", observations)
    ratio = price_slope / dma_slope
    observations["escape_ratio"] = round(ratio, _RATIO_PRECISION)
    return _module(_interpolate(ratio, _PARALLEL_ANCHORS), "price slope relative to a positive, non-flat 50DMA slope", observations)


def _revision(data: JsonMap) -> _Module:
    """计算同口径预期修正的中位数映射。参数：模块集合。返回：模块。异常：无。"""
    values = _section(data, "revision")
    available: dict[str, float] = {}
    for name in ("revenue_30d", "eps_30d", "guide_vs_consensus"):
        value = finite_number(values.get(name))
        if value is not None:
            available[name] = value
    observations: JsonMap = {key: value for key, value in available.items()}
    if len(available) < _MIN_REVISION_INPUTS:
        return _Module(None, "at least two comparable revision inputs are required", observations)
    primary = statistics.median(available.values())
    observations["median_revision"] = round(primary, _RATIO_PRECISION)
    return _module(_interpolate(primary, _REVISION_ANCHORS), "median of at least two comparable 30-day revision/guide gaps", observations)


def calculate(raw: JsonValue) -> JsonMap:
    """计算模块但禁用未经校准总分。参数：JSON 输入。返回：观测及 N/A。异常：非对象时 ValueError。"""
    data = require_map(raw)
    modules = {"growth_match": _growth_match(data), "divergence": _divergence(data), "parallel": _parallel(data), "revision": _revision(data)}
    rendered: JsonMap = {name: {"score": module.score, "reason": module.reason, "observations": module.observations}
                         for name, module in modules.items()}
    missing: list[JsonValue] = [name for name, module in modules.items() if module.score is None]
    return {
        "heuristic_version": MODEL_VERSION, "calibration": "uncalibrated heuristic; validate on point-in-time holdout data",
        "aggregate_enabled": False,
        "aggregate_status": "disabled until module mappings, valid domains, and aggregate weights are calibrated on point-in-time holdout data",
        "scorable": False, "health_score": None, "state": "N/A", "missing_modules": missing, "modules": rendered,
    }
