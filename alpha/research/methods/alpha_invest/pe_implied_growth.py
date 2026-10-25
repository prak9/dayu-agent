"""invest conditional-pe-fcfe-v1：固定股数口径的条件 EPS 增长门槛计算。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .json_values import JsonMap, JsonValue, number, require_map

MODEL_VERSION = "conditional-pe-fcfe-v1"
_MAX_YEARS = 100
_MAX_ITERATIONS = 200
_SOLVER_RELATIVE_TOLERANCE = 1e-10
_RETENTION_EPSILON = 1e-12
_DEFAULT_LOWER_GROWTH = -0.99
_DEFAULT_UPPER_GROWTH = 1.0
_ECONOMIC_FIELDS = frozenset({"base_eps", "years", "cost_of_equity", "cash_conversion", "terminal_cash_conversion", "terminal_growth"})
_OPTIONAL_FIELDS = frozenset({"pe", "growth", "pe_basis", "forward_eps_ratio", "growth_bounds", "scenarios"})
_SENSITIVITY_FIELDS = _ECONOMIC_FIELDS - {"base_eps"}


@dataclass(frozen=True)
class _Inputs:
    """经验证、可比较的经济假设与逆推边界。"""

    base_eps: float
    years: int
    cost_of_equity: float
    cash_conversion: float
    terminal_cash_conversion: float
    terminal_growth: float
    target_base_pe: float | None
    growth: float | None
    lower_growth: float
    upper_growth: float


def _validate(raw: JsonMap) -> _Inputs:
    """校验条件估值域。参数：原始对象。返回：类型化假设。异常：缺数、口径或取值非法。"""
    missing = _ECONOMIC_FIELDS - raw.keys()
    unknown = raw.keys() - _ECONOMIC_FIELDS - _OPTIONAL_FIELDS
    if missing or unknown:
        raise ValueError(f"missing fields: {sorted(missing)}; unknown fields: {sorted(unknown)}")
    eps = number(raw["base_eps"], "base_eps")
    years = number(raw["years"], "years")
    rate = number(raw["cost_of_equity"], "cost_of_equity")
    terminal_growth = number(raw["terminal_growth"], "terminal_growth")
    conversion = number(raw["cash_conversion"], "cash_conversion")
    terminal_conversion = number(raw["terminal_cash_conversion"], "terminal_cash_conversion")
    if eps <= 0 or not years.is_integer() or not 1 <= years <= _MAX_YEARS:
        raise ValueError("base_eps must be positive and years must be an integer in 1..100")
    if rate <= 0 or terminal_growth <= -1 or rate <= terminal_growth:
        raise ValueError("require cost_of_equity > 0, terminal_growth > -1 and cost_of_equity > terminal_growth")
    if not 0 <= conversion <= 1 or not 0 <= terminal_conversion <= 1 or conversion == terminal_conversion == 0:
        raise ValueError("cash conversions must lie in [0,1] and cannot both be zero")
    if ("pe" in raw) == ("growth" in raw):
        raise ValueError("supply exactly one of pe (inverse) or growth (forward)")
    pe = number(raw["pe"], "pe") if "pe" in raw else None
    growth = number(raw["growth"], "growth") if "growth" in raw else None
    if pe is not None and pe <= 0 or growth is not None and growth <= -1:
        raise ValueError("pe must be positive; growth must exceed -1")
    basis = raw.get("pe_basis", "base")
    if basis not in ("base", "forward"):
        raise ValueError("pe_basis must be base or forward")
    if basis == "forward":
        if pe is None or "forward_eps_ratio" not in raw:
            raise ValueError("forward PE requires pe and explicit forward_eps_ratio = EPS1/EPS0")
        ratio = number(raw["forward_eps_ratio"], "forward_eps_ratio")
        if ratio <= 0:
            raise ValueError("forward_eps_ratio must be positive")
        pe *= ratio
        if not math.isfinite(pe):
            raise ValueError("converted base PE is nonfinite")
    elif "forward_eps_ratio" in raw:
        raise ValueError("forward_eps_ratio is only applicable to forward PE")
    if growth is not None and "growth_bounds" in raw:
        raise ValueError("growth_bounds only apply to inverse calculation")
    bounds = raw.get("growth_bounds", [_DEFAULT_LOWER_GROWTH, _DEFAULT_UPPER_GROWTH])
    if not isinstance(bounds, list) or len(bounds) != 2:
        raise ValueError("growth_bounds must contain two numbers")
    lower, upper = number(bounds[0], "growth_bounds"), number(bounds[1], "growth_bounds")
    if not -1 < lower < upper:
        raise ValueError("require -1 < lower growth bound < upper growth bound")
    return _Inputs(eps, int(years), rate, conversion, terminal_conversion, terminal_growth, pe, growth, lower, upper)


def _value(inputs: _Inputs, growth: float) -> tuple[float, float, float]:
    """计算折现价值。参数：已验证假设、增长率。返回：基期 PE、显性期 PV、终值 PV。异常：数值溢出。"""
    ratio = (1 + growth) / (1 + inputs.cost_of_equity)
    # 直接求和覆盖增长等于折现率的情形，无几何级数奇点。
    period = inputs.cash_conversion * math.fsum(ratio ** year for year in range(1, inputs.years + 1))
    terminal = inputs.terminal_cash_conversion * (1 + inputs.terminal_growth) / (inputs.cost_of_equity - inputs.terminal_growth) * ratio ** inputs.years
    pe = period + terminal
    if not math.isfinite(pe) or pe <= 0:
        raise ValueError("valuation overflow/underflow; rescale inputs or narrow growth bounds")
    return pe, period, terminal


def _reinvestment(growth: float, conversion: float) -> JsonMap:
    """解释再投资要求。参数：增长率、现金转化率。返回：条件诊断。异常：无。"""
    retention = 1 - conversion
    if growth < 0:
        required, reason = None, "Contraction is not a positive reinvestment-return estimate."
    elif retention <= _RETENTION_EPSILON:
        required, reason = None, "No identifiable reinvestment denominator; explain another growth mechanism if growth is positive."
    else:
        required, reason = growth / retention, "Conditional on growth funded by net equity reinvestment; not measured ROE."
    return {"equity_reinvestment_rate_proxy": retention, "required_incremental_equity_return": required, "reason": reason}


def _run_case(raw: JsonMap) -> JsonMap:
    """计算单组假设。参数：原始假设。返回：计算结果及不收敛状态。异常：输入或数值非法。"""
    inputs = _validate(raw)
    normalized = {key: value for key, value in raw.items() if key != "scenarios"}
    normalized["pe_basis"] = raw.get("pe_basis", "base")
    output: JsonMap = {"inputs": normalized, "status": "ok", "growth": None, "valuation": None}
    if inputs.target_base_pe is not None:
        target = inputs.target_base_pe
        lower, upper = inputs.lower_growth, inputs.upper_growth
        attainable = [_value(inputs, bound)[0] for bound in (lower, upper)]
        normalized["growth_bounds"] = [lower, upper]
        solver: JsonMap = {"bounds": [lower, upper], "pe_at_bounds": list(attainable)}
        output.update(target_base_pe=target, solver=solver)
        if not attainable[0] <= target <= attainable[1]:
            output.update(status="unbracketed", reason="No root inside these numerical bounds; not proof of economic impossibility.")
            return output
        growth = lower
        for iteration in range(_MAX_ITERATIONS):
            growth = (lower + upper) / 2
            residual = _value(inputs, growth)[0] - target
            if abs(residual) <= _SOLVER_RELATIVE_TOLERANCE * target:
                solver.update(iterations=iteration + 1, residual_pe=residual)
                break
            if residual < 0:
                lower = growth
            else:
                upper = growth
        else:
            output.update(status="not_converged", reason="No validated root within iteration budget.")
            return output
    else:
        assert inputs.growth is not None
        growth = inputs.growth
    pe, period, terminal = _value(inputs, growth)
    multiplier = (1 + growth) ** inputs.years
    price, end_eps = inputs.base_eps * pe, inputs.base_eps * multiplier
    if not all(math.isfinite(value) for value in (price, end_eps, multiplier)):
        raise ValueError("price or terminal-year EPS overflow")
    output.update(growth=growth, valuation={
        "base_pe": pe, "period_pv_per_base_eps": period, "terminal_pv_per_base_eps": terminal,
        "terminal_value_share": terminal / pe, "price": price, "eps_end_year": end_eps, "eps_end_multiple": multiplier,
    }, diagnostics={
        "first_stage": _reinvestment(growth, inputs.cash_conversion),
        "terminal_stage": _reinvestment(inputs.terminal_growth, inputs.terminal_cash_conversion),
        "contraction_then_terminal_recovery": growth < 0 < inputs.terminal_growth,
    })
    return output


def calculate(raw: JsonValue) -> JsonMap:
    """运行基准及显式敏感性。参数：JSON 输入。返回：版本化条件估值。异常：非法参数或数值溢出。"""
    data = require_map(raw)
    result = _run_case(data)
    result["model_version"] = MODEL_VERSION
    result["interpretation"] = "Conditional EPS-growth hurdle, not observed consensus, probability, or a buy signal. Fixed share basis; no separate nonoperating assets."
    scenarios = data.get("scenarios", [])
    if not isinstance(scenarios, list):
        raise ValueError("scenarios must be a list")
    names: set[str] = set()
    outputs: list[JsonValue] = []
    for scenario in scenarios:
        fields = require_map(scenario, "scenario")
        if set(fields) != {"name", "overrides"}:
            raise ValueError("each scenario requires name and overrides")
        name, overrides = fields["name"], require_map(fields["overrides"], "overrides")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("scenario names must be nonempty and unique")
        names.add(name)
        if not overrides or not set(overrides) <= _SENSITIVITY_FIELDS:
            raise ValueError(f"scenario overrides must use {sorted(_SENSITIVITY_FIELDS)}")
        outputs.append({"name": name, "overrides": overrides, "result": _run_case({**data, **overrides})})
    if outputs:
        result["scenarios"] = outputs
    return result
