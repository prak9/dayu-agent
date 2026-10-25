"""UI 请求期不直连 Host 的架构守护测试。"""

from __future__ import annotations

from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_repo_file(relative_path: str) -> str:
    """读取仓库内文件文本。

    Args:
        relative_path: 相对仓库根目录的路径。

    Returns:
        文件文本内容。

    Raises:
        FileNotFoundError: 文件不存在时抛出。
    """

    return (_REPO_ROOT / relative_path).read_text(encoding="utf-8")


@pytest.mark.unit
def test_web_routes_do_not_use_global_service_locator() -> None:
    """Web 请求期路由不应再回退到全局 `get_dependencies()`。"""

    for relative_path in [
        "alpha/web/routes/chat.py",
        "alpha/web/routes/prompt.py",
        "alpha/web/routes/fins.py",
        "alpha/web/routes/sessions.py",
        "alpha/web/routes/runs.py",
        "alpha/web/routes/events.py",
    ]:
        content = _read_repo_file(relative_path)
        assert "get_dependencies(" not in content
        assert "dependencies.host" not in content


@pytest.mark.unit
def test_wechat_daemon_no_longer_holds_ensure_chat_session_callback() -> None:
    """WeChat daemon 不应再持有 `ensure_chat_session` 回调。"""

    content = _read_repo_file("alpha/wechat/daemon.py")

    assert "ensure_chat_session" not in content


@pytest.mark.unit
def test_cli_interactive_path_no_longer_directly_creates_host_session() -> None:
    """CLI interactive 请求路径不应再直接创建 Host session。"""

    content = _read_repo_file("alpha/cli/main.py")

    assert 'args.command == "interactive"' in content
    assert "host.create_session" not in content
