"""独立 invest 计算入口；校验器的 fail 报告仍以退出码 0 返回，调用方须检查状态。"""

from __future__ import annotations

import argparse
import json
import sys
from enum import Enum
from pathlib import Path
from typing import Callable, NoReturn, cast

from .gf_dma import calculate as calculate_gf_dma
from .json_values import JsonMap, JsonValue, require_map
from .option_distribution import calculate as calculate_option_distribution
from .pe_implied_growth import calculate as calculate_pe_implied_growth
from .validate_data import validate

_MAX_INPUT_BYTES = 8 * 1024 * 1024
_ERROR_EXIT_CODE = 2
_STDIN_INPUT = "-"


class CalculationMethod(str, Enum):
    """计算入口支持的固定方法集合，禁止执行任意代码。"""

    PE_IMPLIED_GROWTH = "pe_implied_growth"
    OPTION_DISTRIBUTION = "option_distribution"
    GF_DMA = "gf_dma"
    VALIDATE_DATA = "validate_data"


_CALCULATORS: dict[CalculationMethod, Callable[[JsonMap], JsonMap]] = {
    CalculationMethod.PE_IMPLIED_GROWTH: calculate_pe_implied_growth,
    CalculationMethod.OPTION_DISTRIBUTION: calculate_option_distribution,
    CalculationMethod.GF_DMA: calculate_gf_dma,
    CalculationMethod.VALIDATE_DATA: validate,
}


def _reject_constant(value: str) -> NoReturn:
    """拒绝非标准 JSON 数值。参数：value 常量文本。返回：不返回。异常：始终 ValueError。"""
    raise ValueError(f"nonfinite JSON constant is unsupported: {value}")


def main(argv: list[str] | None = None) -> int:
    """运行固定计算方法。参数：argv 命令参数。返回：进程退出码。异常：参数语法错误时 SystemExit。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("method", choices=[method.value for method in CalculationMethod])
    parser.add_argument("input", type=Path)
    args = parser.parse_args(argv)
    try:
        if str(args.input) == _STDIN_INPUT:
            content = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
        else:
            path = Path(str(args.input))
            with path.open("rb") as handle:
                content = handle.read(_MAX_INPUT_BYTES + 1)
        if len(content) > _MAX_INPUT_BYTES:
            raise ValueError("input exceeds 8 MiB limit")
        data = require_map(cast(JsonValue, json.loads(content.decode("utf-8"), parse_constant=_reject_constant)))
        output = _CALCULATORS[CalculationMethod(str(args.method))](data)
        print(json.dumps(output, ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, ValueError, OverflowError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return _ERROR_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
