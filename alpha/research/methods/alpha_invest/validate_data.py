"""invest 数据契约 v1/v2 的来源、时点与算术校验；不证明原始证据支持度。"""

from __future__ import annotations

from datetime import date, datetime
from typing import TypeGuard, cast

from .json_values import JsonMap, JsonValue, finite_number as finite_value, number

CLASSIFICATIONS = {"reported_fact", "management_guidance", "consensus", "analyst_assumption"}
_SCHEMA_V1 = 1
_SCHEMA_V2 = 2
_SUPPORTED_SCHEMA_VERSIONS = (_SCHEMA_V1, _SCHEMA_V2)
_DEFAULT_TOLERANCE = 0.001
_GROWTH_ZERO_TOLERANCE = 1e-12


def _parse_date(value: JsonValue) -> date:
    """读取日期。参数：JSON 值。返回：日期。异常：类型或格式非法时 ValueError。"""
    if not isinstance(value, str):
        raise ValueError("statement date must be text")
    return date.fromisoformat(value)


def finite_number(value: JsonValue) -> TypeGuard[int | float]:
    """判定有限数字并排除布尔值。参数：value JSON 值。返回：类型守卫。异常：极大整数可能 OverflowError。"""
    return finite_value(value) is not None


def parse_time(value: JsonValue) -> datetime | None:
    """读取精确时间。参数：value JSON 值。返回：带时区时间或空。异常：无，非法时间返回空。"""
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def add_finding(
    findings: list[dict[str, JsonValue]],
    code: str,
    message: str,
    *,
    location: str,
    severity: str = "error",
) -> None:
    """记录问题。参数：findings 问题列表、code 代码、message 解释、location 定位、severity 级别。返回：无。异常：无。"""
    findings.append(
        {"severity": severity, "code": code, "location": location, "message": message}
    )


def nonempty_string(value: JsonValue) -> TypeGuard[str]:
    """判定非空文本。参数：value JSON 值。返回：字符串类型守卫。异常：无。"""
    return isinstance(value, str) and bool(value.strip())


def source_time_bounds(source: JsonMap, field: str, version: int,
                       findings: list[dict[str, JsonValue]], location: str) -> tuple[datetime, datetime] | None:
    """读取来源时间范围。参数：source 来源、field 时间字段、version 契约版本、findings 问题、location 定位。返回：闭区间或空。异常：无。"""
    value = source.get(field)
    exact = parse_time(value)
    if exact is not None:
        return exact, exact
    if version == _SCHEMA_V2 and field in source:
        if value is None and nonempty_string(source.get("time_missing_reason")):
            add_finding(findings, "unknown_source_time", f"{field} is unknown",
                        location=location, severity="warning")
            return None
        if isinstance(value, dict):
            earliest = parse_time(value.get("earliest"))
            latest = parse_time(value.get("latest"))
            if earliest is not None and latest is not None and earliest <= latest and nonempty_string(value.get("reason")):
                return earliest, latest
    add_finding(findings, f"invalid_{field}",
                "expected a zoned timestamp; v2 also accepts justified time bounds or explicit unknown",
                location=location)
    return None


def validate_metric(
    metric: JsonValue,
    index: int,
    decision_time: datetime | None,
    findings: list[dict[str, JsonValue]],
    version: int = _SCHEMA_V1,
) -> str | None:
    """校验指标。参数：metric 记录、index 序号、decision_time 截止日、findings 问题、version 契约版本。返回：指标 ID 或空。异常：极大数值可能 OverflowError。"""
    location = f"metrics[{index}]"
    if not isinstance(metric, dict):
        add_finding(findings, "invalid_metric", "metric must be an object", location=location)
        return None
    metric_id = metric.get("id")
    if not nonempty_string(metric_id):
        add_finding(findings, "invalid_id", "id must be a non-empty string", location=f"{location}.id")
        return None

    for field in ("name", "unit", "period", "basis"):
        if not nonempty_string(metric.get(field)):
            add_finding(
                findings,
                f"invalid_{field}",
                f"{field} must be a non-empty string",
                location=f"{location}.{field}",
            )
    if "currency" not in metric or (
        metric.get("currency") is not None and not nonempty_string(metric.get("currency"))
    ):
        add_finding(
            findings,
            "invalid_currency",
            "currency must be a non-empty string or explicit null",
            location=f"{location}.currency",
        )
    classification = metric.get("classification")
    if not isinstance(classification, str) or classification not in CLASSIFICATIONS:
        add_finding(
            findings,
            "invalid_classification",
            "classification must distinguish fact, guidance, consensus, or analyst assumption",
            location=f"{location}.classification",
        )

    value = metric.get("value")
    if value is None:
        if not nonempty_string(metric.get("missing_reason")):
            add_finding(
                findings,
                "missing_reason_required",
                "a null value needs a non-empty missing_reason; unknown is not zero",
                location=f"{location}.missing_reason",
            )
    elif not finite_number(value):
        add_finding(
            findings,
            "invalid_value",
            "value must be a finite number or null",
            location=f"{location}.value",
        )

    source = metric.get("source")
    if not isinstance(source, dict):
        add_finding(findings, "missing_source", "source must be an object", location=f"{location}.source")
        return str(metric_id)
    for field in ("reference", "document_type"):
        if not nonempty_string(source.get(field)):
            add_finding(
                findings,
                f"invalid_source_{field}",
                f"source.{field} must be a non-empty string",
                location=f"{location}.source.{field}",
            )
    if "locator" not in source or (
        source.get("locator") is not None and not nonempty_string(source.get("locator"))
    ):
        add_finding(
            findings,
            "invalid_source_locator",
            "source.locator must be a non-empty string or explicit null",
            location=f"{location}.source.locator",
        )

    published = source_time_bounds(source, "published_at", version, findings, f"{location}.source.published_at")
    available = source_time_bounds(source, "available_at", version, findings, f"{location}.source.available_at")
    if published is not None and available is not None and available[1] < published[0]:
        add_finding(
            findings,
            "availability_before_publication",
            "available_at cannot precede published_at",
            location=f"{location}.source.available_at",
        )
    # 文档公开时间和实际可用时间都不得穿越历史截止日。
    if decision_time is not None and any(bounds is not None and bounds[0] > decision_time for bounds in (published, available)):
        add_finding(
            findings,
            "point_in_time_violation",
            "source became available after the historical decision time",
            location=f"{location}.source.available_at",
        )
    elif decision_time is not None and any(bounds is None or bounds[1] > decision_time for bounds in (published, available)):
        add_finding(findings, "point_in_time_unresolved", "time bounds cannot establish availability by the cutoff",
                    location=f"{location}.source")
    return str(metric_id)


def resolve_metrics(
    ids: JsonValue,
    metrics: dict[str, dict[str, JsonValue]],
    findings: list[dict[str, JsonValue]],
    location: str,
) -> list[dict[str, JsonValue]] | None:
    """解析指标引用。参数：ids 引用列表、metrics 指标表、findings 问题、location 定位。返回：指标列表或空。异常：无。"""
    if not isinstance(ids, list) or not ids or not all(nonempty_string(item) for item in ids):
        add_finding(findings, "invalid_metric_refs", "metric references must be a non-empty array", location=location)
        return None
    missing = [item for item in ids if item not in metrics]
    if missing:
        add_finding(
            findings,
            "unknown_metric_ref",
            "unknown metric ids: " + ", ".join(str(item) for item in missing),
            location=location,
        )
        return None
    return [metrics[item] for item in cast(list[str], ids)]


def comparable(metrics: list[dict[str, JsonValue]], fields: tuple[str, ...]) -> bool:
    """比较字段口径。参数：metrics 指标列表、fields 字段。返回：是否全部可比。异常：无。"""
    for field in fields:
        values = [metric.get(field) for metric in metrics]
        if not all(nonempty_string(value) or (field == "currency" and value is None) for value in values):
            return False
        if any(value != values[0] for value in values[1:]):
            return False
    return True


def tolerance(check: dict[str, JsonValue], findings: list[dict[str, JsonValue]], location: str) -> float | None:
    """读取非负容差。参数：check 校验项、findings 问题、location 定位。返回：容差或空。异常：极大数值可能 OverflowError。"""
    value = check.get("tolerance", _DEFAULT_TOLERANCE)
    if not finite_number(value) or float(value) < 0:
        add_finding(findings, "invalid_tolerance", "tolerance must be non-negative", location=location)
        return None
    return float(value)


def check_sums(
    checks: JsonValue,
    metrics: dict[str, dict[str, JsonValue]],
    findings: list[dict[str, JsonValue]],
) -> int:
    """校验加总。参数：checks 校验项、metrics 指标表、findings 问题。返回：实际算术检查数。异常：极大数值可能 OverflowError。"""
    if not isinstance(checks, list):
        add_finding(findings, "invalid_sums", "checks.sums must be an array", location="checks.sums")
        return 0
    run = 0
    for index, check in enumerate(checks):
        location = f"checks.sums[{index}]"
        if not isinstance(check, dict):
            add_finding(findings, "invalid_sum_check", "sum check must be an object", location=location)
            continue
        total_id = check.get("total")
        referenced = resolve_metrics(check.get("components"), metrics, findings, f"{location}.components")
        if not nonempty_string(total_id) or total_id not in metrics:
            add_finding(findings, "unknown_metric_ref", "total must name a metric", location=f"{location}.total")
            continue
        if referenced is None:
            continue
        involved = referenced + [metrics[total_id]]
        if not comparable(involved, ("unit", "currency", "period", "basis")):
            add_finding(
                findings,
                "incompatible_basis",
                "sum inputs must share unit, currency, period, and basis",
                location=location,
            )
            continue
        if any(metric.get("value") is None or not finite_number(metric.get("value")) for metric in involved):
            add_finding(findings, "evidence_missing", "sum contains an unknown value", location=location)
            continue
        allowed = tolerance(check, findings, f"{location}.tolerance")
        if allowed is None:
            continue
        component_sum = sum(number(metric["value"], "metric.value") for metric in referenced)
        total = number(metrics[total_id]["value"], "total.value")
        run += 1
        if abs(component_sum - total) > allowed * max(1.0, abs(total)):
            add_finding(
                findings,
                "sum_mismatch",
                f"components sum to {component_sum:g}, total is {total:g}",
                location=location,
            )
    return run


def check_growth_rates(
    checks: JsonValue,
    metrics: dict[str, dict[str, JsonValue]],
    findings: list[dict[str, JsonValue]],
) -> int:
    """校验增长率。参数：checks 校验项、metrics 指标表、findings 问题。返回：实际算术检查数。异常：极大数值可能 OverflowError。"""
    if not isinstance(checks, list):
        add_finding(findings, "invalid_growth_rates", "checks.growth_rates must be an array", location="checks.growth_rates")
        return 0
    run = 0
    for index, check in enumerate(checks):
        location = f"checks.growth_rates[{index}]"
        if not isinstance(check, dict):
            add_finding(findings, "invalid_growth_check", "growth check must be an object", location=location)
            continue
        ids = [check.get("prior"), check.get("current")]
        referenced = resolve_metrics(ids, metrics, findings, location)
        if referenced is None:
            continue
        if not comparable(referenced, ("unit", "currency", "basis")):
            add_finding(
                findings,
                "incompatible_basis",
                "growth inputs must share unit, currency, and basis",
                location=location,
            )
            continue
        if any(metric.get("value") is None or not finite_number(metric.get("value")) for metric in referenced):
            add_finding(findings, "evidence_missing", "growth check contains an unknown value", location=location)
            continue
        prior = number(referenced[0]["value"], "prior.value")
        current = number(referenced[1]["value"], "current.value")
        if abs(prior) <= _GROWTH_ZERO_TOLERANCE:
            add_finding(findings, "invalid_growth_base", "growth cannot use a zero prior value", location=location)
            continue
        expected = check.get("expected")
        if not finite_number(expected):
            add_finding(findings, "invalid_expected_growth", "expected must be a decimal number", location=f"{location}.expected")
            continue
        allowed = tolerance(check, findings, f"{location}.tolerance")
        if allowed is None:
            continue
        calculated = current / prior - 1.0
        run += 1
        if abs(calculated - float(expected)) > allowed:
            add_finding(
                findings,
                "growth_mismatch",
                f"calculated growth is {calculated:.6f}, expected is {float(expected):.6f}",
                location=location,
            )
    return run


def check_probabilities(
    checks: JsonValue,
    metrics: dict[str, dict[str, JsonValue]],
    findings: list[dict[str, JsonValue]],
) -> int:
    """校验概率质量。参数：checks 校验项、metrics 指标表、findings 问题。返回：实际算术检查数。异常：极大数值可能 OverflowError。"""
    if not isinstance(checks, list):
        add_finding(findings, "invalid_probability_groups", "checks.probability_groups must be an array", location="checks.probability_groups")
        return 0
    run = 0
    for index, check in enumerate(checks):
        location = f"checks.probability_groups[{index}]"
        if not isinstance(check, dict):
            add_finding(findings, "invalid_probability_check", "probability check must be an object", location=location)
            continue
        referenced = resolve_metrics(check.get("items"), metrics, findings, f"{location}.items")
        if referenced is None:
            continue
        if any(metric.get("value") is None or not finite_number(metric.get("value")) for metric in referenced):
            add_finding(findings, "evidence_missing", "probability group contains an unknown value", location=location)
            continue
        values = [number(metric["value"], "metric.value") for metric in referenced]
        if any(value < 0 or value > 1 for value in values):
            add_finding(findings, "invalid_probability", "each probability must be within [0, 1]", location=location)
            continue
        target = check.get("target", 1.0)
        allowed = tolerance(check, findings, f"{location}.tolerance")
        if not finite_number(target) or allowed is None:
            add_finding(findings, "invalid_probability_target", "target must be numeric", location=f"{location}.target")
            continue
        run += 1
        if abs(sum(values) - float(target)) > allowed:
            add_finding(
                findings,
                "probability_sum_mismatch",
                f"probabilities sum to {sum(values):.6f}, target is {float(target):.6f}",
                location=location,
            )
    return run


def check_basis_groups(
    checks: JsonValue,
    metrics: dict[str, dict[str, JsonValue]],
    findings: list[dict[str, JsonValue]],
) -> int:
    """校验可比组。参数：checks 校验项、metrics 指标表、findings 问题。返回：实际比较次数。异常：无。"""
    if not isinstance(checks, list):
        add_finding(findings, "invalid_basis_groups", "checks.basis_groups must be an array", location="checks.basis_groups")
        return 0
    allowed_fields = {"unit", "currency", "period", "basis", "classification"}
    run = 0
    for index, check in enumerate(checks):
        location = f"checks.basis_groups[{index}]"
        if not isinstance(check, dict):
            add_finding(findings, "invalid_basis_check", "basis check must be an object", location=location)
            continue
        referenced = resolve_metrics(check.get("items"), metrics, findings, f"{location}.items")
        fields = check.get("fields")
        if (
            not isinstance(fields, list)
            or not fields
            or not all(isinstance(field, str) and field in allowed_fields for field in fields)
        ):
            add_finding(
                findings,
                "invalid_basis_fields",
                "fields must select unit, currency, period, basis, or classification",
                location=f"{location}.fields",
            )
            continue
        if referenced is None:
            continue
        run += 1
        if not comparable(referenced, tuple(cast(list[str], fields))):
            add_finding(
                findings,
                "incompatible_basis",
                "declared comparable metrics differ on: " + ", ".join(cast(list[str], fields)),
                location=location,
            )
    return run


def check_period_differences(checks: JsonValue, metrics: dict[str, dict[str, JsonValue]],
                             findings: list[dict[str, JsonValue]]) -> int:
    """校验期间差分。参数：checks 校验项、metrics 指标表、findings 问题。返回：实际差分检查数。异常：极大数值可能 OverflowError。"""
    if not isinstance(checks, list):
        add_finding(findings, "invalid_period_differences", "expected an array", location="checks.period_differences")
        return 0
    run = 0
    for index, check in enumerate(checks):
        location = f"checks.period_differences[{index}]"
        if not isinstance(check, dict):
            add_finding(findings, "invalid_difference", "expected an object", location=location)
            continue
        ids = [check.get(key) for key in ("cumulative", "prior_cumulative", "result")]
        rows = resolve_metrics(ids, metrics, findings, location)
        if rows is None:
            continue
        contexts = [row.get("statement") for row in rows]
        if not all(isinstance(context, dict) for context in contexts):
            add_finding(findings, "missing_statement_context", "each input/result needs statement context", location=location)
            continue
        contexts = cast(list[JsonMap], contexts)
        if any(context.get("kind") != "flow" for context in contexts):
            add_finding(findings, "nonadditive_difference", "only additive period flows may be subtracted", location=location)
            continue
        context_fields = ("concept", "scope", "accounting_standard", "version_basis", "security_basis")
        if not comparable(rows, ("unit", "currency", "basis", "classification")) or not comparable(contexts, context_fields):
            add_finding(findings, "incompatible_basis", "difference inputs must share concept, units, scope and accounting/version/security basis", location=location)
            continue
        try:
            periods = [(_parse_date(c["start"]), _parse_date(c["end"])) for c in contexts]
            (start, end), (prior_start, prior_end), (result_start, result_end) = periods
            valid = (all(a <= b for a, b in periods) and start == prior_start and prior_end < end
                     and (result_start - prior_end).days == 1 and result_end == end)
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            add_finding(findings, "incompatible_periods", "require shared cumulative start and contiguous result period", location=location)
            continue
        if rows[2].get("derivation") != {"operation": "subtract", "inputs": ids[:2]}:
            add_finding(findings, "missing_derivation", "result must retain subtract operation and ordered source metric IDs", location=location)
            continue
        if not all(finite_number(row.get("value")) for row in rows):
            add_finding(findings, "evidence_missing", "difference contains an unknown/nonfinite value", location=location)
            continue
        allowed = tolerance(check, findings, location)
        if allowed is None:
            continue
        calculated = number(rows[0]["value"], "cumulative.value") - number(rows[1]["value"], "prior.value")
        run += 1
        if abs(calculated - number(rows[2]["value"], "result.value")) > allowed * max(1.0, abs(number(rows[2]["value"], "result.value"))):
            add_finding(findings, "difference_mismatch", f"calculated result is {calculated:g}", location=location)
    return run


def validate(data: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """校验完整数据契约。参数：data 输入对象。返回：含 pass/fail、问题和检查计数的报告。异常：极大数值可能 OverflowError。"""
    findings: list[dict[str, JsonValue]] = []
    version = data.get("schema_version", _SCHEMA_V1)
    if isinstance(version, bool) or not isinstance(version, int) or version not in _SUPPORTED_SCHEMA_VERSIONS:
        add_finding(findings, "unsupported_schema", "schema_version must be 1 or 2", location="schema_version")
        version = _SCHEMA_V1
    decision_time = None
    if "decision_time" in data:
        decision_time = parse_time(data["decision_time"])
        if decision_time is None:
            add_finding(
                findings,
                "invalid_decision_time",
                "decision_time must be an ISO-8601 timestamp with timezone",
                location="decision_time",
            )
    if "as_of" in data and parse_time(data["as_of"]) is None:
        add_finding(
            findings,
            "invalid_as_of",
            "as_of must be an ISO-8601 timestamp with timezone",
            location="as_of",
        )

    raw_metrics = data.get("metrics")
    if not isinstance(raw_metrics, list) or not raw_metrics:
        add_finding(findings, "invalid_metrics", "metrics must be a non-empty array", location="metrics")
        raw_metrics = []
    metrics: dict[str, dict[str, JsonValue]] = {}
    for index, metric in enumerate(raw_metrics):
        metric_id = validate_metric(metric, index, decision_time, findings, version)
        if metric_id is None or not isinstance(metric, dict):
            continue
        if metric_id in metrics:
            add_finding(findings, "duplicate_id", f"duplicate metric id: {metric_id}", location=f"metrics[{index}].id")
        else:
            metrics[metric_id] = metric

    checks = data.get("checks", {})
    if not isinstance(checks, dict):
        add_finding(findings, "invalid_checks", "checks must be an object", location="checks")
        checks = {}
    checks_run: JsonMap = {
        "sums": check_sums(checks.get("sums", []), metrics, findings),
        "growth_rates": check_growth_rates(checks.get("growth_rates", []), metrics, findings),
        "probability_groups": check_probabilities(checks.get("probability_groups", []), metrics, findings),
        "basis_groups": check_basis_groups(checks.get("basis_groups", []), metrics, findings),
    }
    if version == _SCHEMA_V2:
        checks_run["period_differences"] = check_period_differences(checks.get("period_differences", []), metrics, findings)
    elif "period_differences" in checks:
        add_finding(findings, "unsupported_check", "period_differences requires schema_version 2", location="checks.period_differences")
    return {
        "schema_version": version,
        "status": "fail" if any(item["severity"] == "error" for item in findings) else "pass",
        "metrics_checked": len(raw_metrics),
        "checks_run": checks_run,
        "findings": [item for item in findings],
        "limitations": [
            "Arithmetic and metadata checks do not prove that a source supports a value or conclusion.",
            "A clean point-in-time check covers only the timestamps recorded in this file.",
        ],
    }
