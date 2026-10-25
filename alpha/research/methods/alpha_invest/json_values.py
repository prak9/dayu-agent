"""独立计算包的 JSON 类型与输入校验，不依赖 alpha 主进程。"""

from __future__ import annotations

import math
from typing import TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonMap: TypeAlias = dict[str, JsonValue]


def require_map(value: JsonValue, name: str = "input") -> JsonMap:
    """要求 JSON 对象。参数：值、字段名。返回：对象。异常：非对象时 ValueError。"""
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def finite_number(value: JsonValue) -> float | None:
    """读取有限数。参数：JSON 值。返回：数或空。异常：无。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def number(value: JsonValue, name: str) -> float:
    """要求有限数。参数：JSON 值、字段名。返回：数。异常：缺数或非有限数时 ValueError。"""
    result = finite_number(value)
    if result is None:
        raise ValueError(f"{name} must be a finite number")
    return result
