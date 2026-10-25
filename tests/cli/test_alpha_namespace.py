"""alpha 包与公共命令的身份契约测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tomllib


def test_alpha_namespace_and_console_entrypoints() -> None:
    """验证新包及公共入口使用已确认的 alpha 名称。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 包、分发名称或命令仍使用旧命名时抛出。
    """

    assert importlib.util.find_spec("alpha") is not None
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "alpha-agent"
    assert project["scripts"] == {
        "alpha": "alpha.cli.main:main",
        "alpha-web": "alpha.web.__main__:main",
        "alpha-wechat": "alpha.wechat.main:main",
        "alpha-telegram": "alpha.telegram.main:main",
        "alpha-render": "alpha.render.render:main",
        "alpha-mcp": "alpha.mcp.main:main",
    }
