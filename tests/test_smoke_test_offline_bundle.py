"""`utils.smoke_test_offline_bundle` 模块测试。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

import pytest

from utils import smoke_test_offline_bundle as module

pytestmark = pytest.mark.unit


def test_run_smoke_checks_temporarily_skips_alpha_web(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """离线包 smoke 暂不验证尚未完成的 Web help。

    Args:
        monkeypatch: pytest monkeypatch fixture。
        tmp_path: pytest 临时目录 fixture。

    Returns:
        无。

    Raises:
        AssertionError: smoke 命令集合不符合预期时抛出。
    """

    python_path = tmp_path / ("python.exe" if os.name == "nt" else "python")
    scripts_dir = tmp_path / "Scripts"
    scripts_dir.mkdir()
    command_names: list[str] = []

    def _fake_run_command(command: Sequence[str], *, env: dict[str, str] | None = None) -> None:
        """记录 smoke 命令，不执行真实子进程。

        Args:
            command: 被测代码准备执行的命令。
            env: 可选环境变量覆盖。

        Returns:
            无。

        Raises:
            IndexError: 命令为空时抛出。
        """

        del env
        command_names.append(Path(command[0]).name)

    monkeypatch.setattr(module, "_run_command", _fake_run_command)

    module._run_smoke_checks(python_path, scripts_dir)

    skipped_web_name = "alpha-web.exe" if os.name == "nt" else "alpha-web"
    assert skipped_web_name not in command_names
