"""清洗后的欧式等价看涨期权价差推导离散风险中性终价分布。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime

from .json_values import JsonMap, JsonValue, number, require_map

MODEL_VERSION = "discrete-call-spread-risk-neutral-v1"
_REQUIRED_FIELDS = frozenset({"quote_timestamp", "expiration", "spot", "risk_free_rate", "option_style", "price_basis", "calls"})
_ALLOWED_STYLES = frozenset({"european", "european_equivalent"})
_YEAR_DAYS = 365.25
_MIN_CALL_COUNT = 3
_PROBABILITY_TOLERANCE = 1e-10
_ONE_YEAR_MIN_DAYS = 274
_ONE_YEAR_MAX_DAYS = 456


@dataclass(frozen=True, order=True)
class _Call:
    """同一到期日、报价时点及股数口径的看涨期权价格。"""

    strike: float
    price: float


@dataclass(frozen=True)
class _Inputs:
    """经验证的风险中性分布假设与期权网格。"""

    quote_timestamp: datetime
    expiration: date
    spot: float
    rate: float
    style: str
    price_basis: str
    calls: tuple[_Call, ...]


@dataclass(frozen=True)
class _Threshold:
    """价差网格中点及对应上尾质量。"""

    price: float
    tail: float
    left_strike: float
    right_strike: float


def _validate(raw: JsonValue) -> _Inputs:
    """校验时点、口径和网格。参数：原始 JSON。返回：类型化输入。异常：缺数或域不支持。"""
    data = require_map(raw)
    missing, unknown = _REQUIRED_FIELDS - data.keys(), data.keys() - _REQUIRED_FIELDS
    if missing or unknown:
        raise ValueError(f"missing fields: {sorted(missing)}; unknown fields: {sorted(unknown)}")
    quote, expiry = data["quote_timestamp"], data["expiration"]
    if not isinstance(quote, str) or not isinstance(expiry, str):
        raise ValueError("quote_timestamp and expiration must be ISO timestamps/date")
    timestamp = datetime.fromisoformat(quote.replace("Z", "+00:00"))
    expiration = date.fromisoformat(expiry)
    if timestamp.utcoffset() is None:
        raise ValueError("quote_timestamp must include a timezone")
    if expiration <= timestamp.date():
        raise ValueError("expiration must be after valuation_date")
    spot, rate = number(data["spot"], "spot"), number(data["risk_free_rate"], "risk_free_rate")
    if spot <= 0:
        raise ValueError("spot must be positive")
    style, basis = data["option_style"], data["price_basis"]
    if not isinstance(style, str) or style not in _ALLOWED_STYLES:
        raise ValueError("option_style must be european or european_equivalent; raw American prices are unsupported")
    if not isinstance(basis, str) or not basis.strip():
        raise ValueError("price_basis must be a nonempty description")
    grid = data["calls"]
    if not isinstance(grid, list) or len(grid) < _MIN_CALL_COUNT:
        raise ValueError("calls must contain at least three strike prices")
    calls: list[_Call] = []
    for index, raw_call in enumerate(grid):
        call = require_map(raw_call, f"calls[{index}]")
        if set(call) != {"strike", "call_price"}:
            raise ValueError(f"calls[{index}] must contain exactly strike and call_price")
        strike, price = number(call["strike"], "strike"), number(call["call_price"], "call_price")
        if strike <= 0 or price < 0:
            raise ValueError("strikes must be positive and call prices nonnegative")
        calls.append(_Call(strike, price))
    if len({call.strike for call in calls}) != len(calls):
        raise ValueError("duplicate strikes are unsupported")
    return _Inputs(timestamp, expiration, spot, rate, style, basis.strip(), tuple(sorted(calls)))


def calculate(raw: JsonValue) -> JsonMap:
    """计算离散风险中性概率。参数：已清洗期权 JSON。返回：版本化分布。异常：无套利检查或输入失败。"""
    inputs = _validate(raw)
    days = (inputs.expiration - inputs.quote_timestamp.date()).days
    years = days / _YEAR_DAYS
    discount_inverse = math.exp(inputs.rate * years)
    thresholds: list[_Threshold] = []
    adjusted = False
    for left, right in zip(inputs.calls, inputs.calls[1:]):
        tail = discount_inverse * (left.price - right.price) / (right.strike - left.strike)
        midpoint = (left.strike + right.strike) / 2
        if tail < -_PROBABILITY_TOLERANCE or tail > 1 + _PROBABILITY_TOLERANCE:
            raise ValueError(f"vertical-spread probability outside [0,1] near strike {midpoint}")
        tail = min(1.0, max(0.0, tail))
        if thresholds and tail > thresholds[-1].tail:
            if tail > thresholds[-1].tail + _PROBABILITY_TOLERANCE:
                raise ValueError("call prices violate convexity: tail probability rises with strike")
            # 容差内浮点噪声须消除，不能把负的区间概率交付给报告。
            tail = thresholds[-1].tail
            adjusted = True
        thresholds.append(_Threshold(midpoint, tail, left.strike, right.strike))
    buckets: list[JsonValue] = [{"lower_exclusive": None, "upper_inclusive": thresholds[0].price,
                                "probability": 1 - thresholds[0].tail}]
    for lower, upper in zip(thresholds, thresholds[1:]):
        buckets.append({"lower_exclusive": lower.price, "upper_inclusive": upper.price, "probability": lower.tail - upper.tail})
    buckets.append({"lower_exclusive": thresholds[-1].price, "upper_inclusive": None, "probability": thresholds[-1].tail})
    normalized_calls: list[JsonValue] = [{"strike": call.strike, "call_price": call.price} for call in inputs.calls]
    threshold_values: list[JsonValue] = [{
        "terminal_price_threshold": value.price, "return_from_spot": value.price / inputs.spot - 1,
        "probability_above": value.tail, "probability_at_or_below": 1 - value.tail,
        "source_strikes": [value.left_strike, value.right_strike],
    } for value in thresholds]
    result: JsonMap = {
        "status": "ok", "model_version": MODEL_VERSION,
        "inputs": {
            "quote_timestamp": inputs.quote_timestamp.isoformat(), "valuation_date": inputs.quote_timestamp.date().isoformat(),
            "expiration": inputs.expiration.isoformat(), "days_to_expiration": days, "time_years_act_365_25": years,
            "spot": inputs.spot, "risk_free_rate": inputs.rate, "option_style": inputs.style,
            "price_basis": inputs.price_basis, "calls": normalized_calls,
        },
        "horizon_note": "approximately_one_year" if _ONE_YEAR_MIN_DAYS <= days <= _ONE_YEAR_MAX_DAYS else "outside_9_to_15_month_window",
        "threshold_probabilities": threshold_values, "range_probabilities": buckets,
        "interpretation": "Risk-neutral terminal-price probabilities from cleaned European-equivalent calls; not objective forecasts or fundamental scenario weights.",
        "tail_note": "Open-ended edge buckets are probability mass outside the usable strike grid; their internal distribution is not estimated.",
    }
    if adjusted:
        result["rounding_adjustment"] = {"monotonic_tail_clamp": True, "tolerance": _PROBABILITY_TOLERANCE}
    return result
