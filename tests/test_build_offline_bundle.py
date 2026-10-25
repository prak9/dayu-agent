"""`utils.build_offline_bundle` 模块测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from utils import build_offline_bundle as module

pytestmark = pytest.mark.unit


class TestWriteInstallScript:
    """`_write_install_script()` 测试。"""

    def test_writes_unix_install_script_with_binary_only_guard(self, tmp_path: Path) -> None:
        """Unix 安装脚本应显式要求仅安装 wheel。"""

        module._write_install_script(tmp_path, version="0.1.2", platform_id="macos-arm64")

        script_text = (tmp_path / "install.sh").read_text(encoding="utf-8")

        assert module._PIP_ONLY_BINARY_ALL in script_text
        assert "alpha-agent[browser,web]==0.1.2" in script_text

    def test_writes_windows_install_script_with_binary_only_guard(self, tmp_path: Path) -> None:
        """Windows 安装脚本应显式要求仅安装 wheel。"""

        module._write_install_script(tmp_path, version="0.1.2", platform_id="windows-x64")

        script_text = (tmp_path / "install.cmd").read_text(encoding="utf-8")

        assert module._PIP_ONLY_BINARY_ALL in script_text
        assert "alpha-agent[browser,web]==0.1.2" in script_text


class TestWriteBundleReadme:
    """`_write_bundle_readme()` 测试。"""

    def test_readme_does_not_mention_unfinished_alpha_web_help(self, tmp_path: Path) -> None:
        """离线包 README 不应提示尚未完成的 Web help 验证。"""

        module._write_bundle_readme(
            tmp_path,
            package_name="alpha-agent",
            version="0.1.2",
            platform_id="macos-arm64",
        )

        readme_text = (tmp_path / "README.txt").read_text(encoding="utf-8")

        assert "alpha-web --help" not in readme_text


class TestDownloadWheelhouse:
    """`_download_wheelhouse()` 测试。"""

    def test_requirements_include_browser_and_web_extras(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """wheelhouse 下载阶段应同时纳入 browser 与 web extras。"""

        wheel_path = tmp_path / "alpha_agent-0.1.2-py3-none-any.whl"
        wheel_path.write_text("wheel", encoding="utf-8")
        constraints_path = tmp_path / "constraints.txt"
        constraints_path.write_text("requests==2.32.5\n", encoding="utf-8")
        captured_requirements: list[str] = []

        def _fake_run_command(command: list[str], *, env: dict[str, str] | None = None) -> None:
            """记录临时 requirements 文件内容。

            Args:
                command: 被测代码传入的 pip download 命令。
                env: 可选环境变量覆盖。

            Returns:
                无。

            Raises:
                ValueError: 命令中缺少 `-r` 参数时由 `list.index` 抛出。
                OSError: requirements 文件读取失败时抛出。
            """

            del env
            requirements_path = Path(command[command.index("-r") + 1])
            captured_requirements.append(requirements_path.read_text(encoding="utf-8"))

        def _fake_build_source_distribution_wheels(
            wheelhouse_dir: Path,
            *,
            wheel_cache_dir: Path | None,
        ) -> None:
            """跳过源码包构建。

            Args:
                wheelhouse_dir: 被测代码传入的 wheelhouse 目录。
                wheel_cache_dir: 可选 wheel 缓存目录。

            Returns:
                无。

            Raises:
                无。
            """

            del wheelhouse_dir, wheel_cache_dir

        monkeypatch.setattr(module, "_run_command", _fake_run_command)
        monkeypatch.setattr(
            module,
            "_build_source_distribution_wheels",
            _fake_build_source_distribution_wheels,
        )

        module._download_wheelhouse(
            tmp_path / "bundle",
            wheel_path=wheel_path,
            constraints_path=constraints_path,
            wheel_cache_dir=None,
        )

        assert captured_requirements == [f"{module._offline_wheel_requirement(wheel_path)}\n"]


class TestBuildSourceDistributionWheels:
    """`_build_source_distribution_wheels()` 测试。"""

    def test_skips_when_wheelhouse_contains_only_wheels(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """若 wheelhouse 里只有 wheel，则不应触发 `pip wheel`。"""

        (tmp_path / "already-built-1.0.0-py3-none-any.whl").write_text("wheel", encoding="utf-8")

        command_calls: list[list[str]] = []

        def _fake_run_command(command: list[str], *, env: dict[str, str] | None = None) -> None:
            del env
            command_calls.append(command)

        monkeypatch.setattr(module, "_run_command", _fake_run_command)

        module._build_source_distribution_wheels(tmp_path, wheel_cache_dir=None)

        assert command_calls == []

    def test_builds_source_distributions_and_removes_archives(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """应把源码分发包预构建为 wheel，并删除原始源码归档。"""

        source_tar = tmp_path / "demo_pkg-1.0.0.tar.gz"
        source_zip = tmp_path / "other_pkg-2.0.0.zip"
        existing_wheel = tmp_path / "keep_pkg-3.0.0-py3-none-any.whl"
        source_tar.write_text("tar", encoding="utf-8")
        source_zip.write_text("zip", encoding="utf-8")
        existing_wheel.write_text("wheel", encoding="utf-8")

        command_calls: list[list[str]] = []

        def _fake_run_command(command: list[str], *, env: dict[str, str] | None = None) -> None:
            del env
            command_calls.append(command)
            wheel_dir = Path(command[command.index("--wheel-dir") + 1])
            source_paths = [Path(path_text) for path_text in command[command.index(str(wheel_dir)) + 1 :]]
            for source_path in source_paths:
                wheel_name = f"{source_path.stem}-py3-none-any.whl"
                (wheel_dir / wheel_name).write_text("built", encoding="utf-8")

        monkeypatch.setattr(module, "_run_command", _fake_run_command)

        module._build_source_distribution_wheels(tmp_path, wheel_cache_dir=None)

        assert len(command_calls) == 1
        assert command_calls[0][:5] == [module.sys.executable, "-m", "pip", "wheel", "--no-deps"]
        assert not source_tar.exists()
        assert not source_zip.exists()
        assert existing_wheel.exists()
        assert (tmp_path / "demo_pkg-1.0.0.tar-py3-none-any.whl").exists()
        assert (tmp_path / "other_pkg-2.0.0-py3-none-any.whl").exists()

    def test_writes_back_newly_built_wheels_to_cache_dir(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """构建得到的新 wheel 应被回写到缓存目录；原有 wheel 不应被回写。"""

        wheelhouse_dir = tmp_path / "wheelhouse"
        wheelhouse_dir.mkdir()
        cache_dir = tmp_path / "cache"

        source_tar = wheelhouse_dir / "demo_pkg-1.0.0.tar.gz"
        existing_wheel = wheelhouse_dir / "keep_pkg-3.0.0-py3-none-any.whl"
        source_tar.write_text("tar", encoding="utf-8")
        existing_wheel.write_text("wheel", encoding="utf-8")

        def _fake_run_command(command: list[str], *, env: dict[str, str] | None = None) -> None:
            del env
            wheel_dir = Path(command[command.index("--wheel-dir") + 1])
            source_paths = [Path(path_text) for path_text in command[command.index(str(wheel_dir)) + 1 :]]
            for source_path in source_paths:
                wheel_name = f"{source_path.stem}-py3-none-any.whl"
                (wheel_dir / wheel_name).write_text("built", encoding="utf-8")

        monkeypatch.setattr(module, "_run_command", _fake_run_command)

        module._build_source_distribution_wheels(wheelhouse_dir, wheel_cache_dir=cache_dir)

        assert cache_dir.is_dir()
        cached_names = {path.name for path in cache_dir.iterdir()}
        assert cached_names == {"demo_pkg-1.0.0.tar-py3-none-any.whl"}
        assert not (cache_dir / "keep_pkg-3.0.0-py3-none-any.whl").exists()

    def test_cache_writeback_skips_existing_same_name(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """缓存目录已存在同名 wheel 时不应覆盖。"""

        wheelhouse_dir = tmp_path / "wheelhouse"
        wheelhouse_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        (wheelhouse_dir / "demo_pkg-1.0.0.tar.gz").write_text("tar", encoding="utf-8")
        preexisting_cached = cache_dir / "demo_pkg-1.0.0.tar-py3-none-any.whl"
        preexisting_cached.write_text("preexisting", encoding="utf-8")

        def _fake_run_command(command: list[str], *, env: dict[str, str] | None = None) -> None:
            del env
            wheel_dir = Path(command[command.index("--wheel-dir") + 1])
            source_paths = [Path(path_text) for path_text in command[command.index(str(wheel_dir)) + 1 :]]
            for source_path in source_paths:
                (wheel_dir / f"{source_path.stem}-py3-none-any.whl").write_text("built", encoding="utf-8")

        monkeypatch.setattr(module, "_run_command", _fake_run_command)

        module._build_source_distribution_wheels(wheelhouse_dir, wheel_cache_dir=cache_dir)

        assert preexisting_cached.read_text(encoding="utf-8") == "preexisting"
