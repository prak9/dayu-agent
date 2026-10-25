"""读取随 wheel 分发的方法资源与独立计算代码，不读取开发机 skill 目录。"""

from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable


def _collect(directory: Traversable, prefix: str, result: dict[str, bytes], *, suffixes: tuple[str, ...]) -> None:
    """收集包内资源。参数：目录、逻辑前缀、结果映射、允许后缀。返回：无。异常：资源 I/O 错误。"""
    for entry in directory.iterdir():
        logical_path = f"{prefix}/{entry.name}" if prefix else entry.name
        if entry.is_dir():
            if entry.name != "__pycache__":
                _collect(entry, logical_path, result, suffixes=suffixes)
        elif entry.name.endswith(suffixes):
            result[logical_path] = entry.read_bytes()


def read_packaged_method_files() -> dict[str, bytes]:
    """读取当前分发版本。参数：无。返回：相对路径到完整字节映射。异常：包资源不可读。"""
    package = files("alpha.research.methods")
    result: dict[str, bytes] = {}
    _collect(package.joinpath("assets"), "", result, suffixes=(".md", ".json"))
    _collect(package.joinpath("alpha_invest"), "alpha_invest", result, suffixes=(".py",))
    return result
