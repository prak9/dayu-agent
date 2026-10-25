"""方法包的可移植引用、内容固定与恢复完整性测试。"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from alpha.contracts.research import ResearchConflictError
from alpha.research.methods.resources import read_packaged_method_files
from alpha.research.storage.methods import FsResearchMethodStore

_ISOLATED_BOOTSTRAP = (
    "import runpy,sys;sys.modules['alpha']=None;"
    "sys.path.insert(0,sys.argv[1]);sys.argv=sys.argv[2:];"
    "runpy.run_module('alpha_invest',run_name='__main__')"
)


def test_resources_close_references_and_run_from_pinned_bundle(tmp_path: Path) -> None:
    """干净资源包可读依赖并独立运行。参数：目录。返回：无。异常：断言失败。"""
    files = read_packaged_method_files()
    store = FsResearchMethodStore(tmp_path / "methods")
    bundle = store.pin(files)
    assert store.pin(files) == bundle
    assert "# Invest" in bundle.entrypoint_text and "alpha invest" in bundle.entrypoint_text
    assert (bundle.root / "skills/writing/SKILL.md").is_file()
    assert (bundle.root / "skills/writing/references/revision-checklist.md").is_file()
    for name, content in files.items():
        if not name.endswith(".md"):
            continue
        for link in re.findall(r"\]\(([^)]+)\)", content.decode()):
            relative = link.split("#")[0]
            if relative and "://" not in relative and not relative.startswith("mailto:"):
                assert (bundle.root / name).parent.joinpath(relative).is_file(), (name, relative)
    source = tmp_path / "input.json"
    source.write_text('{"metrics": []}')
    result = subprocess.run(
        [sys.executable, "-B", "-I", "-c", _ISOLATED_BOOTSTRAP, str(bundle.root), "alpha_invest", "validate_data", str(source)],
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "fail"
    assert store.load(bundle.method_hash) == bundle


def test_current_assets_change_does_not_replace_old_accepted_method(tmp_path: Path) -> None:
    """新代码版本不会改变旧方法包。参数：目录。返回：无。异常：断言失败。"""
    store = FsResearchMethodStore(tmp_path / "methods")
    files = read_packaged_method_files()
    old = store.pin(files)
    changed = store.pin({**files, "RUNTIME.md": b"# New runtime"})
    assert changed.method_hash != old.method_hash
    assert store.load(old.method_hash) == old
    (old.root / "skills/invest/SKILL.md").write_text("被改写")
    with pytest.raises(ResearchConflictError, match="内容校验"):
        store.load(old.method_hash)


def test_pending_directory_and_interrupted_ack_are_recoverable(tmp_path: Path, mocker: MockerFixture) -> None:
    """提交后的确认中断可复用，未完成目录不混入正式包。参数：目录、mock。返回：无。异常：断言失败。"""
    root = tmp_path / "methods"
    store = FsResearchMethodStore(root)
    files = read_packaged_method_files()
    pending = root / ".pending-interrupted"
    pending.mkdir()
    (pending / "RUNTIME.md").write_text("未完成")
    mocker.patch.object(store, "load", side_effect=RuntimeError("模拟提交后退出"))
    with pytest.raises(RuntimeError, match="提交后"):
        store.pin(files)
    committed = [path for path in root.iterdir() if not path.name.startswith(".")]
    assert len(committed) == 1
    mocker.stopall()
    assert store.pin(files).root == committed[0]


@pytest.mark.parametrize("path", ["../escape.md", "/absolute.md", "x/../escape.md", "x\\escape.md", "", ".", "_bundle-manifest.json"])
def test_resource_paths_cannot_escape_or_shadow_manifest(tmp_path: Path, path: str) -> None:
    """资源路径只能是包内规范相对路径。参数：目录、路径。返回：无。异常：断言失败。"""
    with pytest.raises(ValueError):
        FsResearchMethodStore(tmp_path).pin({"RUNTIME.md": b"runtime", "skills/invest/SKILL.md": b"invest", path: b"invalid"})


def test_missing_manifest_untracked_code_and_bad_hash_fail(tmp_path: Path) -> None:
    """缺包或未校验代码不使用新版本兜底。参数：目录。返回：无。异常：断言失败。"""
    store = FsResearchMethodStore(tmp_path)
    with pytest.raises(ValueError):
        store.pin({})
    with pytest.raises(ValueError):
        store.load("invalid")
    with pytest.raises(ResearchConflictError, match="缺失"):
        store.load("0" * 64)
    bundle = store.pin(read_packaged_method_files())
    extra = bundle.root / "alpha_invest" / "extra.py"
    extra.write_text("unexpected code")
    with pytest.raises(ResearchConflictError, match="文件集合"):
        store.load(bundle.method_hash)
    extra.unlink()
    manifest = bundle.root / "_bundle-manifest.json"
    manifest.write_text("{}")
    with pytest.raises(ResearchConflictError, match="清单校验"):
        store.load(bundle.method_hash)


def test_symlink_manifest_and_resource_are_rejected(tmp_path: Path) -> None:
    """方法资源不能通过链接绕出已固定内容。参数：目录。返回：无。异常：断言失败。"""
    store = FsResearchMethodStore(tmp_path / "methods")
    bundle = store.pin(read_packaged_method_files())
    original = bundle.root / "RUNTIME.md"
    copy = tmp_path / "runtime-copy.md"
    original.rename(copy)
    original.symlink_to(copy)
    with pytest.raises(ResearchConflictError, match="符号链接"):
        store.load(bundle.method_hash)
    original.unlink()
    copy.rename(original)
    manifest = bundle.root / "_bundle-manifest.json"
    saved = tmp_path / "manifest.json"
    manifest.rename(saved)
    manifest.symlink_to(saved)
    with pytest.raises(ResearchConflictError, match="符号链接"):
        store.load(bundle.method_hash)
