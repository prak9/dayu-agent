"""处理器注册表测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO, Optional

import pytest

from alpha.engine.processors.base import SearchHit, SectionContent, SectionSummary, TableContent, TableSummary
from alpha.engine.processors.processor_registry import ProcessorRegistry
from alpha.engine.processors.source import Source


class DummySource:
    """测试用 Source。"""

    def __init__(self, uri: str) -> None:
        """初始化 Source。

        Args:
            uri: 资源 URI。

        Returns:
            无。

        Raises:
            ValueError: URI 为空时抛出。
        """

        if not uri:
            raise ValueError("uri 不能为空")
        self.uri = uri
        self.media_type = "text/html"
        self.content_length = None
        self.etag = None

    def open(self) -> BinaryIO:
        """打开只读流。

        Args:
            无。

        Returns:
            二进制只读流。

        Raises:
            OSError: 打开失败时抛出。
        """

        raise OSError("dummy source 不提供 open")

    def materialize(self, suffix: Optional[str] = None) -> Path:
        """物化为本地路径。

        Args:
            suffix: 可选后缀。

        Returns:
            本地路径。

        Raises:
            OSError: 物化失败时抛出。
        """

        raise OSError("dummy source 不提供 materialize")


class DummyProcessorA:
    """测试处理器 A。"""

    PARSER_VERSION = "dummy_processor_a_v1"

    @classmethod
    def get_parser_version(cls) -> str:
        """返回测试处理器版本。"""

        return str(cls.PARSER_VERSION)

    def __init__(
        self,
        source: Source,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> None:
        """初始化处理器。

        Args:
            source: 文档来源抽象。
            form_type: 可选表单类型。
            media_type: 可选媒体类型。

        Returns:
            None。

        Raises:
            ValueError: 参数非法时抛出。
        """

        self.source = source

    @classmethod
    def supports(
        cls,
        source: Source,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> bool:
        """判断是否支持处理该文件。

        Args:
            source: 文档来源抽象。
            form_type: 可选表单类型。
            media_type: 可选媒体类型。

        Returns:
            是否支持。

        Raises:
            OSError: 读取失败时可能抛出。
        """

        return True

    def list_sections(self) -> list[SectionSummary]:
        """返回测试章节列表。"""

        return [
            {
                "ref": "s_0001",
                "title": "Dummy section",
                "level": 1,
                "parent_ref": None,
                "preview": "dummy preview",
            }
        ]

    def list_tables(self) -> list[TableSummary]:
        """返回测试表格列表。"""

        return [
            {
                "table_ref": "t_0001",
                "caption": "Dummy table",
                "context_before": "",
                "row_count": 1,
                "col_count": 1,
                "table_type": "data",
                "headers": ["A"],
                "section_ref": "s_0001",
            }
        ]

    def read_section(self, ref: str) -> SectionContent:
        """返回测试章节内容。"""

        return {
            "ref": ref,
            "title": "Dummy section",
            "content": "dummy content",
            "tables": [],
            "word_count": 2,
            "contains_full_text": True,
        }

    def read_table(self, table_ref: str) -> TableContent:
        """返回测试表格内容。"""

        return {
            "table_ref": table_ref,
            "caption": "Dummy table",
            "data_format": "records",
            "data": [],
            "columns": ["A"],
            "row_count": 1,
            "col_count": 1,
            "section_ref": "s_0001",
            "table_type": "data",
        }

    def get_section_title(self, ref: str) -> Optional[str]:
        """根据 ref 返回测试章节标题。"""

        del ref
        return "Dummy section"

    def search(self, query: str, within_ref: Optional[str] = None) -> list[SearchHit]:
        """返回空搜索结果。"""

        del query, within_ref
        return []

    def get_full_text(self) -> str:
        """返回测试全文。"""

        return "dummy content"

    def get_full_text_with_table_markers(self) -> str:
        """返回带占位符的测试全文。"""

        return self.get_full_text()


class DummyProcessorB(DummyProcessorA):
    """测试处理器 B。"""

    def __init__(
        self,
        source: Source,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> None:
        """初始化处理器。

        Args:
            source: 文档来源抽象。
            form_type: 可选表单类型。
            media_type: 可选媒体类型。

        Returns:
            None。

        Raises:
            ValueError: 参数非法时抛出。
        """

        self.source = source

    @classmethod
    def supports(
        cls,
        source: Source,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> bool:
        """判断是否支持处理该文件。

        Args:
            source: 文档来源抽象。
            form_type: 可选表单类型。
            media_type: 可选媒体类型。

        Returns:
            是否支持。

        Raises:
            OSError: 读取失败时可能抛出。
        """

        return True


class DummyProcessorRaisesOSError(DummyProcessorA):
    """测试处理器：supports 抛 OSError。"""

    def __init__(
        self,
        source: Source,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> None:
        """初始化处理器。

        Args:
            source: 文档来源抽象。
            form_type: 可选表单类型。
            media_type: 可选媒体类型。

        Returns:
            None。

        Raises:
            ValueError: 参数非法时抛出。
        """

        self.source = source

    @classmethod
    def supports(
        cls,
        source: Source,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> bool:
        """判断是否支持处理该文件。

        Args:
            source: 文档来源抽象。
            form_type: 可选表单类型。
            media_type: 可选媒体类型。

        Returns:
            是否支持。

        Raises:
            OSError: 人工触发。
        """

        raise OSError("模拟读取失败")


class DummyProcessorNever(DummyProcessorA):
    """测试处理器：永不支持。"""

    def __init__(
        self,
        source: Source,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> None:
        """初始化处理器。

        Args:
            source: 文档来源抽象。
            form_type: 可选表单类型。
            media_type: 可选媒体类型。

        Returns:
            None。

        Raises:
            ValueError: 参数非法时抛出。
        """

        self.source = source

    @classmethod
    def supports(
        cls,
        source: Source,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> bool:
        """判断是否支持处理该文件。

        Args:
            source: 文档来源抽象。
            form_type: 可选表单类型。
            media_type: 可选媒体类型。

        Returns:
            是否支持。

        Raises:
            OSError: 读取失败时可能抛出。
        """

        return False


class DummyProcessorInitError(DummyProcessorA):
    """测试处理器：构造阶段抛出异常。"""

    def __init__(
        self,
        source: Source,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> None:
        """初始化处理器并主动抛错。

        Args:
            source: 文档来源抽象。
            form_type: 可选表单类型。
            media_type: 可选媒体类型。

        Returns:
            无。

        Raises:
            RuntimeError: 始终抛出，模拟初始化失败。
        """

        del source, form_type, media_type
        raise RuntimeError("模拟初始化失败")

    @classmethod
    def supports(
        cls,
        source: Source,
        *,
        form_type: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> bool:
        """判断是否支持处理该文件。

        Args:
            source: 文档来源抽象。
            form_type: 可选表单类型。
            media_type: 可选媒体类型。

        Returns:
            始终返回 True。

        Raises:
            OSError: 读取失败时可能抛出。
        """

        return True


@pytest.mark.unit
def test_processor_registry_register_and_resolve(tmp_path: Path) -> None:
    """验证注册与解析。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    sample = DummySource("local://sample.html")

    registry = ProcessorRegistry()
    registry.register(DummyProcessorA, name="dummy_a", priority=1)

    resolved = registry.resolve(sample)
    assert resolved is DummyProcessorA


@pytest.mark.unit
def test_processor_registry_priority(tmp_path: Path) -> None:
    """验证优先级排序。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    sample = DummySource("local://sample.html")

    registry = ProcessorRegistry()
    registry.register(DummyProcessorA, name="dummy_a", priority=1)
    registry.register(DummyProcessorB, name="dummy_b", priority=5)

    resolved = registry.resolve(sample)
    assert resolved is DummyProcessorB


@pytest.mark.unit
def test_processor_registry_create(tmp_path: Path) -> None:
    """验证创建处理器实例。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    sample = DummySource("local://sample.html")

    registry = ProcessorRegistry()
    registry.register(DummyProcessorA, name="dummy_a", priority=1)

    instance = registry.create(sample)
    assert isinstance(instance, DummyProcessorA)


@pytest.mark.unit
def test_processor_registry_overwrite_and_unregister(tmp_path: Path) -> None:
    """验证覆盖注册与卸载行为。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        None。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    sample = DummySource("local://sample.html")
    registry = ProcessorRegistry()
    registry.register(DummyProcessorA, name="dup", priority=1)
    registry.register(DummyProcessorB, name="dup", priority=5, overwrite=True)

    resolved = registry.resolve(sample)
    assert resolved is DummyProcessorB

    registry.unregister("dup")
    assert registry.list_processors() == []
    with pytest.raises(KeyError):
        registry.unregister("dup")


@pytest.mark.unit
def test_processor_registry_empty_by_default() -> None:
    """验证注册表默认为空且不会隐式路由。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    registry = ProcessorRegistry()
    assert registry.list_processors() == []
    source = DummySource("local://sample.html")
    assert registry.resolve(source) is None


@pytest.mark.unit
def test_processor_registry_register_duplicate_without_overwrite_raises() -> None:
    """验证重复注册且不允许覆盖会抛错。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    registry = ProcessorRegistry()
    registry.register(DummyProcessorA, name="dup", priority=1)
    with pytest.raises(ValueError):
        registry.register(DummyProcessorB, name="dup", priority=2, overwrite=False)


@pytest.mark.unit
def test_processor_registry_resolve_skips_oserror_processor() -> None:
    """验证 resolve 会跳过 supports 抛 OSError 的处理器。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source = DummySource("local://sample.html")
    registry = ProcessorRegistry()
    registry.register(DummyProcessorRaisesOSError, name="bad", priority=10)
    registry.register(DummyProcessorA, name="ok", priority=1)

    assert registry.resolve(source) is DummyProcessorA


@pytest.mark.unit
def test_processor_registry_create_when_no_processor_raises() -> None:
    """验证 create 在无可用处理器时抛出 ValueError。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source = DummySource("local://sample.html")
    registry = ProcessorRegistry()
    registry.register(DummyProcessorNever, name="never", priority=1)
    with pytest.raises(ValueError):
        registry.create(source)


@pytest.mark.unit
def test_processor_registry_create_with_fallback_uses_next_candidate() -> None:
    """验证 create_with_fallback 在首候选失败时回退下一候选。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source = DummySource("local://sample.html")
    registry = ProcessorRegistry()
    registry.register(DummyProcessorInitError, name="broken", priority=10)
    registry.register(DummyProcessorA, name="ok", priority=5)

    callback_events: list[str] = []

    def _record_fallback(
        processor_cls: type[Any],
        exc: Exception,
        current_index: int,
        total_candidates: int,
    ) -> None:
        """记录回退回调参数。

        Args:
            processor_cls: 当前失败候选类。
            exc: 创建异常。
            current_index: 当前候选序号（从 1 开始）。
            total_candidates: 候选总数。

        Returns:
            无。

        Raises:
            RuntimeError: 无。
        """

        callback_events.append(
            f"{processor_cls.__name__}:{current_index}/{total_candidates}:{type(exc).__name__}"
        )

    instance = registry.create_with_fallback(source, on_fallback=_record_fallback)

    assert isinstance(instance, DummyProcessorA)
    assert callback_events == ["DummyProcessorInitError:1/2:RuntimeError"]


@pytest.mark.unit
def test_processor_registry_create_with_fallback_raises_when_all_failed() -> None:
    """验证 create_with_fallback 在候选全部失败时抛出 RuntimeError。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source = DummySource("local://sample.html")
    registry = ProcessorRegistry()
    registry.register(DummyProcessorInitError, name="broken_1", priority=10)
    registry.register(DummyProcessorInitError, name="broken_2", priority=5)

    with pytest.raises(RuntimeError, match="处理器创建失败且无可用回退"):
        registry.create_with_fallback(source)


@pytest.mark.unit
def test_processor_registry_resolve_candidates_returns_ordered_matches() -> None:
    """验证 resolve_candidates 返回按优先级排序的可用处理器。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source = DummySource("local://sample.html")
    registry = ProcessorRegistry()
    registry.register(DummyProcessorRaisesOSError, name="bad", priority=9)
    registry.register(DummyProcessorA, name="a", priority=5)
    registry.register(DummyProcessorB, name="b", priority=3)

    candidates = registry.resolve_candidates(source)
    assert candidates == [DummyProcessorA, DummyProcessorB]
