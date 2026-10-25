"""fins 处理器注册构建器测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO, Optional, cast

import pytest

from alpha.engine.processors.source import Source
from alpha.fins.processors.bs_def14a_processor import BsDef14AFormProcessor
from alpha.fins.processors.def14a_processor import Def14AFormProcessor
from alpha.fins.processors.bs_eight_k_processor import BsEightKFormProcessor
from alpha.fins.processors.bs_sc13_processor import BsSc13FormProcessor
from alpha.fins.processors.eight_k_processor import EightKFormProcessor
from alpha.fins.processors.registry import build_bs_experiment_registry, build_fins_processor_registry
from alpha.fins.processors.sc13_processor import Sc13FormProcessor
from alpha.fins.processors.bs_six_k_processor import BsSixKFormProcessor
from alpha.fins.processors.ten_k_processor import TenKFormProcessor
from alpha.fins.processors.bs_ten_k_processor import BsTenKFormProcessor
from alpha.fins.processors.bs_ten_q_processor import BsTenQFormProcessor
from alpha.fins.processors.bs_twenty_f_processor import BsTwentyFFormProcessor
from alpha.fins.processors.ten_q_processor import TenQFormProcessor
from alpha.fins.processors.twenty_f_processor import TwentyFFormProcessor


class DummySource:
    """测试用 Source。"""

    def __init__(self, uri: str, media_type: Optional[str] = "text/html") -> None:
        """初始化测试 Source。

        Args:
            uri: 资源 URI。
            media_type: 媒体类型。

        Returns:
            无。

        Raises:
            ValueError: URI 为空时抛出。
        """

        if not uri:
            raise ValueError("uri 不能为空")
        self.uri = uri
        self.media_type = media_type
        self.content_length = None
        self.etag = None

    def open(self) -> BinaryIO:
        """打开只读流（测试桩）。

        Args:
            无。

        Returns:
            二进制只读流。

        Raises:
            OSError: 测试桩不提供读取能力。
        """

        raise OSError("dummy source 不提供 open")

    def materialize(self, suffix: Optional[str] = None) -> Path:
        """物化路径（测试桩）。

        Args:
            suffix: 可选后缀。

        Returns:
            本地路径。

        Raises:
            OSError: 测试桩不提供物化能力。
        """

        raise OSError("dummy source 不提供 materialize")


@pytest.mark.unit
def test_build_fins_processor_registry_registers_sec_and_bs() -> None:
    """验证 fins 构建器会注册专项/通用处理器。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    registry = build_fins_processor_registry()
    processors = registry.list_processors()
    assert [item["name"] for item in processors] == [
        "sc13_section_processor",
        "six_k_section_processor",
        "def14a_section_processor",
        "eight_k_section_processor",
        "ten_k_section_processor",
        "ten_q_section_processor",
        "twenty_f_section_processor",
        "sc13_section_processor_fallback",
        "def14a_section_processor_fallback",
        "eight_k_section_processor_fallback",
        "ten_k_section_processor_fallback",
        "ten_q_section_processor_fallback",
        "twenty_f_section_processor_fallback",
        "sec_processor",
        "docling_processor",
        "markdown_processor",
        "bs_processor",
    ]
    assert {
        str(item["name"]): int(cast(Any, item["priority"]))
        for item in processors
    } == {
        "sc13_section_processor": 200,
        "six_k_section_processor": 200,
        "def14a_section_processor": 200,
        "eight_k_section_processor": 200,
        "ten_k_section_processor": 200,
        "ten_q_section_processor": 200,
        "twenty_f_section_processor": 200,
        "sc13_section_processor_fallback": 190,
        "def14a_section_processor_fallback": 190,
        "eight_k_section_processor_fallback": 190,
        "ten_k_section_processor_fallback": 190,
        "ten_q_section_processor_fallback": 190,
        "twenty_f_section_processor_fallback": 190,
        "sec_processor": 120,
        "docling_processor": 100,
        "markdown_processor": 100,
        "bs_processor": 80,
    }


@pytest.mark.unit
def test_build_fins_processor_registry_routes_by_form() -> None:
    """验证 fins 构建器路由规则。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    registry = build_fins_processor_registry()
    source = DummySource("local://sample.html")

    resolved_10k = registry.resolve(source, form_type="10-K")
    resolved_10q = registry.resolve(source, form_type="10-Q")
    resolved_20f = registry.resolve(source, form_type="20-F")
    resolved_def14a = registry.resolve(source, form_type="DEF 14A")
    resolved_6k = registry.resolve(source, form_type="6-K")
    resolved_8k = registry.resolve(source, form_type="8-K")
    resolved_sc13 = registry.resolve(source, form_type="SC 13D/A")

    # 10-K 主路径为 BsTenKFormProcessor，TenKFormProcessor 为回退
    assert resolved_10k is BsTenKFormProcessor
    # 10-Q 主路径为 BsTenQFormProcessor，TenQFormProcessor 为回退
    assert resolved_10q is BsTenQFormProcessor
    # 20-F 主路径为 BsTwentyFFormProcessor，TwentyFFormProcessor 为回退
    assert resolved_20f is BsTwentyFFormProcessor
    # DEF 14A 主路径为 BsDef14AFormProcessor，Def14AFormProcessor 为回退
    assert resolved_def14a is BsDef14AFormProcessor
    assert resolved_6k is BsSixKFormProcessor
    # 8-K 主路径为 BsEightKFormProcessor，EightKFormProcessor 为回退
    assert resolved_8k is BsEightKFormProcessor
    # SC 13 主路径为 BsSc13FormProcessor，Sc13FormProcessor 为回退
    assert resolved_sc13 is BsSc13FormProcessor


@pytest.mark.unit
@pytest.mark.parametrize(
    ("form_type", "expected_class_name"),
    [
        ("10-K", "BsTenKFormProcessor"),
        ("10-Q", "BsTenQFormProcessor"),
        ("20-F", "BsTwentyFFormProcessor"),
        ("DEF 14A", "BsDef14AFormProcessor"),
        ("6-K", "BsSixKFormProcessor"),
        ("8-K", "BsEightKFormProcessor"),
        ("SC 13D/A", "BsSc13FormProcessor"),
    ],
)
def test_build_fins_processor_registry_routes_by_form_class_name(
    form_type: str,
    expected_class_name: str,
) -> None:
    """验证各类 SEC form 路由到对应专用处理器类名。

    Args:
        form_type: 输入 form 类型。
        expected_class_name: 期望处理器类名。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    registry = build_fins_processor_registry()
    source = DummySource("local://sample.html")

    resolved = registry.resolve(source, form_type=form_type)

    assert resolved is not None
    assert resolved.__name__ == expected_class_name


@pytest.mark.unit
def test_build_bs_experiment_registry_routes_10k_to_bs() -> None:
    """验证 BS 实验注册表与默认注册表一致（BS 已为主路径）。

    BsTenKFormProcessor 已在默认注册表中作为 10-K 主路径，
    ``build_bs_experiment_registry()`` 保持向后兼容。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    registry = build_bs_experiment_registry()
    source = DummySource("local://sample.html")

    resolved_10k = registry.resolve(source, form_type="10-K")
    resolved_10q = registry.resolve(source, form_type="10-Q")

    # 10-K 应路由到 BsTenKFormProcessor（而非 TenKFormProcessor）
    assert resolved_10k is BsTenKFormProcessor
    # 10-Q 应路由到 BsTenQFormProcessor（而非 TenQFormProcessor）
    assert resolved_10q is BsTenQFormProcessor


@pytest.mark.unit
def test_build_fins_registry_10k_fallback_candidates() -> None:
    """验证 10-K 回退候选列表包含 BsTenKFormProcessor 和 TenKFormProcessor。

    ``create_with_fallback`` 使用 ``resolve_candidates`` 返回的候选列表，
    当 BsTenKFormProcessor 实例化失败时自动回退到 TenKFormProcessor。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    registry = build_fins_processor_registry()
    source = DummySource("local://sample.html")

    candidates = registry.resolve_candidates(source, form_type="10-K")

    # 前两个候选应为 BS（主路径）和 Sec（回退）
    assert len(candidates) >= 2
    assert candidates[0] is BsTenKFormProcessor
    assert candidates[1] is TenKFormProcessor


@pytest.mark.unit
def test_build_fins_registry_20f_fallback_candidates() -> None:
    """验证 20-F 回退候选列表包含 BsTwentyFFormProcessor 和 TwentyFFormProcessor。

    ``create_with_fallback`` 使用 ``resolve_candidates`` 返回的候选列表，
    当 BsTwentyFFormProcessor 实例化失败时自动回退到 TwentyFFormProcessor。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    registry = build_fins_processor_registry()
    source = DummySource("local://sample.html")

    candidates = registry.resolve_candidates(source, form_type="20-F")

    # 前两个候选应为 BS（主路径）和 edgartools（回退）
    assert len(candidates) >= 2
    assert candidates[0] is BsTwentyFFormProcessor
    assert candidates[1] is TwentyFFormProcessor


@pytest.mark.unit
def test_build_fins_registry_sc13_fallback_candidates() -> None:
    """验证 SC 13 回退候选列表包含 BsSc13FormProcessor 和 Sc13FormProcessor。

    ``create_with_fallback`` 使用 ``resolve_candidates`` 返回的候选列表，
    当 BsSc13FormProcessor 实例化失败时自动回退到 Sc13FormProcessor。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    registry = build_fins_processor_registry()
    source = DummySource("local://sample.html")

    candidates = registry.resolve_candidates(source, form_type="SC 13G")

    # 前两个候选应为 BS（主路径）和 edgartools（回退）
    assert len(candidates) >= 2
    assert candidates[0] is BsSc13FormProcessor
    assert candidates[1] is Sc13FormProcessor
