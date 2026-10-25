"""engine 架构边界测试。"""

from __future__ import annotations

from pathlib import Path
import re

import pytest


@pytest.mark.unit
def test_engine_python_modules_do_not_import_fins() -> None:
    """验证 engine Python 模块不反向依赖 fins 包。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 发现反向依赖时抛出。
    """

    engine_root = Path("alpha/engine")
    pattern = re.compile(r"^\s*(from|import)\s+alpha\.fins\b", re.MULTILINE)
    offenders: list[str] = []
    for path in engine_root.rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        if pattern.search(content):
            offenders.append(str(path))
    assert offenders == []


@pytest.mark.unit
def test_engine_processors_do_not_embed_financial_keywords() -> None:
    """验证 engine 通用处理器不内置金融关键词常量。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 发现违规常量时抛出。
    """

    processors_root = Path("alpha/engine/processors")
    target_files = [
        processors_root / "bs_processor.py",
        processors_root / "docling_processor.py",
        processors_root / "markdown_processor.py",
    ]
    offenders: list[str] = []
    for path in target_files:
        content = path.read_text(encoding="utf-8")
        if "_FINANCIAL_KEYWORDS" in content:
            offenders.append(str(path))
    assert offenders == []


@pytest.mark.unit
def test_engine_core_modules_do_not_import_neutral_tool_contracts_via_tools_namespace() -> None:
    """验证 engine 核心模块不经由 tools 命名空间依赖中性工具契约。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 发现核心模块重新依赖旧路径时抛出。
    """

    engine_root = Path("alpha/engine")
    pattern = re.compile(
        r"(^\s*from\s+\.(?:tools)\.(?:schema_types|limits)\s+import\b)|"
        r"(^\s*from\s+alpha\.engine\.tools\.(?:schema_types|limits)\s+import\b)|"
        r"(^\s*import\s+alpha\.engine\.tools\.(?:schema_types|limits)\b)",
        re.MULTILINE,
    )
    offenders: list[str] = []
    for path in engine_root.rglob("*.py"):
        if "tools" in path.parts:
            continue
        content = path.read_text(encoding="utf-8")
        if pattern.search(content):
            offenders.append(str(path))
    assert offenders == []


@pytest.mark.unit
def test_tool_registry_satisfies_tool_executor_protocol() -> None:
    """ToolRegistry 实现了 ToolExecutor Protocol 声明的全部方法。

    遍历 Protocol 声明的公开方法，验证 ToolRegistry 均已实现。
    """
    import inspect
    from alpha.engine.protocols import ToolExecutor
    from alpha.engine.tool_registry import ToolRegistry

    protocol_methods = {
        name
        for name, _ in inspect.getmembers(ToolExecutor, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    registry_methods = {
        name
        for name, _ in inspect.getmembers(ToolRegistry, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    missing = protocol_methods - registry_methods
    assert missing == set(), f"ToolRegistry 缺少 Protocol 方法: {missing}"
