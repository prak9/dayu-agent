"""按内容哈希固定方法代码及文档，旧受理恢复不随软件升级切换资源。"""

from __future__ import annotations

import errno
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import cast

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research import ResearchConflictError
from alpha.contracts.research_methods import ResearchMethodBundle
from alpha.research.storage.atomic import staged_directory, sync_directory, write_bytes_synced
from alpha.research.storage.encoding import canonical_json, content_hash

_MANIFEST_FILE = "_bundle-manifest.json"
_HASH_PATTERN = re.compile(r"[a-f0-9]{64}\Z")
_RUNTIME_ENTRY = "RUNTIME.md"
_INVEST_ENTRY = "skills/invest/SKILL.md"


def _validated_path(name: str) -> PurePosixPath:
    """校验方法资源相对路径。参数：name 路径。返回：规范路径。异常：绝对、穿越或保留路径。"""
    path = PurePosixPath(name)
    if not name or not path.parts or "\\" in name or "\x00" in name or path.is_absolute() or ".." in path.parts or path.as_posix() != name or name == _MANIFEST_FILE:
        raise ValueError("方法资源路径非法")
    return path


def _file_hash(data: bytes) -> str:
    """计算原始字节摘要。参数：data 内容。返回：摘要。异常：无。"""
    return hashlib.sha256(data).hexdigest()


class FsResearchMethodStore:
    """提交内容寻址方法包；已存在包只核验，不覆盖。"""

    def __init__(self, root: Path) -> None:
        """设置方法库。参数：root 目录。返回：无。异常：I/O 错误。"""
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def pin(self, files: Mapping[str, bytes]) -> ResearchMethodBundle:
        """固定资源。参数：files 逻辑路径与完整字节。返回：已核验方法包。异常：路径、缺失或内容冲突。"""
        if _RUNTIME_ENTRY not in files or _INVEST_ENTRY not in files:
            raise ValueError("方法包缺少 runtime 或 invest 入口")
        for name in files:
            _validated_path(name)
        manifest = {name: _file_hash(data) for name, data in files.items()}
        encoded = canonical_json({name: digest for name, digest in manifest.items()})
        method_hash = content_hash(encoded)
        destination = self._root / method_hash
        if destination.exists():
            return self.load(method_hash)
        with staged_directory(self._root) as staging:
            for name, data in files.items():
                path = staging / name
                path.parent.mkdir(parents=True, exist_ok=True)
                write_bytes_synced(path, data)
            write_bytes_synced(staging / _MANIFEST_FILE, encoded.encode("utf-8"))
            directories = [path for path in staging.rglob("*") if path.is_dir()]
            for directory in sorted(directories, key=_path_depth, reverse=True):
                sync_directory(directory)
            sync_directory(staging)
            try:
                staging.rename(destination)
            except OSError as exc:
                if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                    raise
            sync_directory(self._root)
        return self.load(method_hash)

    def load(self, method_hash: str) -> ResearchMethodBundle:
        """恢复原资源。参数：method_hash 已受理哈希。返回：方法包。异常：不存在、越界或完整性失败。"""
        if not _HASH_PATTERN.fullmatch(method_hash):
            raise ValueError("方法哈希格式非法")
        directory = self._root / method_hash
        if not directory.resolve().is_relative_to(self._root):
            raise ResearchConflictError("方法包路径越界")
        if (directory / _MANIFEST_FILE).is_symlink():
            raise ResearchConflictError("方法包清单不能是符号链接")
        try:
            encoded = (directory / _MANIFEST_FILE).read_text(encoding="utf-8")
            manifest = cast(JsonValue, json.loads(encoded))
            if not isinstance(manifest, dict) or content_hash(canonical_json(manifest)) != method_hash:
                raise ResearchConflictError("方法包清单校验失败")
            entries = list(directory.rglob("*"))
            if any(path.is_symlink() for path in entries):
                raise ResearchConflictError("方法包不能包含符号链接")
            actual_names = {path.relative_to(directory).as_posix() for path in entries if path.is_file()}
            if actual_names != {*manifest, _MANIFEST_FILE}:
                raise ResearchConflictError("方法包文件集合校验失败")
            for name, digest in manifest.items():
                path = directory / _validated_path(name)
                if not isinstance(digest, str) or _file_hash(path.read_bytes()) != digest:
                    raise ResearchConflictError("方法包内容校验失败")
            entrypoint = (directory / _RUNTIME_ENTRY).read_text(encoding="utf-8") + "\n\n" + (directory / _INVEST_ENTRY).read_text(encoding="utf-8")
        except (FileNotFoundError, UnicodeError, json.JSONDecodeError) as exc:
            raise ResearchConflictError("方法包缺失或损坏，不能替换为当前版本") from exc
        return ResearchMethodBundle(method_hash, directory, entrypoint)

    def read_reference(self, method_hash: str, path: str) -> str:
        """读取固定方法参考。参数：方法哈希、包内路径。返回：正文。异常：越界、非 Markdown 或完整性失败。"""
        relative = _validated_path(path)
        if relative.suffix != ".md":
            raise ValueError("方法参考只允许 Markdown 文档")
        bundle = self.load(method_hash)
        return (bundle.root / relative).read_text(encoding="utf-8")


def _path_depth(path: Path) -> int:
    """计算目录同步顺序。参数：path 目录。返回：层级数。异常：无。"""
    return len(path.parts)
