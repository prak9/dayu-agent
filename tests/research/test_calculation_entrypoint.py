"""独立计算入口的 JSON、状态码及无 alpha 依赖运行测试。"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from alpha.research.methods import alpha_invest
from alpha.research.methods.alpha_invest.__main__ import main
from alpha.research.methods.alpha_invest.json_values import JsonValue, require_map

_ISOLATED_BOOTSTRAP = (
    "import runpy,sys;sys.modules['alpha']=None;"
    "sys.path.insert(0,sys.argv[1]);sys.argv=sys.argv[2:];"
    "runpy.run_module('alpha_invest',run_name='__main__')"
)


def test_validator_fail_report_is_not_process_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """校验失败仍输出报告，自动化必须读 status。参数：目录、输出捕获。返回：无。异常：断言失败。"""
    source = tmp_path / "data.json"
    source.write_text('{"metrics": []}')
    assert main(["validate_data", str(source)]) == 0
    result = require_map(cast(JsonValue, json.loads(capsys.readouterr().out)))
    assert result["status"] == "fail"


def test_known_calculator_dispatch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """固定方法路由到相同算法。参数：目录、输出捕获。返回：无。异常：断言失败。"""
    source = tmp_path / "data.json"
    source.write_text('{"base_eps":1,"years":5,"cost_of_equity":0.1,"cash_conversion":1,"terminal_cash_conversion":1,"terminal_growth":0,"growth":0}')
    assert main(["pe_implied_growth", str(source)]) == 0
    result = require_map(cast(JsonValue, json.loads(capsys.readouterr().out)))
    assert require_map(result["valuation"])["base_pe"] == pytest.approx(10)


@pytest.mark.parametrize("content", ['{broken', '[]', '{"number":NaN}', '{"base_eps":null}'])
def test_invalid_json_and_numeric_inputs_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str) -> None:
    """坏文件及非标准数值明确失败。参数：目录、输出捕获、文本。返回：无。异常：断言失败。"""
    source = tmp_path / "data.json"
    source.write_text(content)
    assert main(["pe_implied_growth", str(source)]) == 2
    output = capsys.readouterr()
    assert not output.out and "Error:" in output.err


def test_missing_and_oversized_files_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """输入读取有实际大小边界。参数：目录、输出捕获。返回：无。异常：断言失败。"""
    source = tmp_path / "input.json"
    assert main(["validate_data", str(source)]) == 2
    source.write_bytes(b" " * (8 * 1024 * 1024 + 1))
    assert main(["validate_data", str(source)]) == 2
    assert "8 MiB" in capsys.readouterr().err


def test_unknown_method_is_rejected_before_reading_file(tmp_path: Path) -> None:
    """任意方法名不形成代码执行入口。参数：目录。返回：无。异常：断言失败。"""
    with pytest.raises(SystemExit) as error:
        main(["arbitrary_code", str(tmp_path / "unused")])
    assert error.value.code == 2


def test_copied_package_runs_when_alpha_import_is_blocked(tmp_path: Path) -> None:
    """复制的计算包完全依赖标准库。参数：目录。返回：无。异常：断言失败。"""
    assert alpha_invest.__file__ is not None
    package = tmp_path / "portable" / "alpha_invest"
    shutil.copytree(Path(alpha_invest.__file__).parent, package, ignore=shutil.ignore_patterns("__pycache__"))
    source = tmp_path / "data.json"
    source.write_text('{"metrics": []}')
    process = subprocess.run(
        [sys.executable, "-I", "-c", _ISOLATED_BOOTSTRAP, str(package.parent), "alpha_invest", "validate_data", str(source)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["status"] == "fail"
