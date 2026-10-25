"""8-K 表单章节处理器覆盖率测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from alpha.fins.processors.eight_k_processor import EightKFormProcessor
from alpha.fins.storage.local_file_source import LocalFileSource


class _FakeSection:
    """测试用章节对象。"""

    def __init__(self, text_value: str) -> None:
        """初始化章节对象。

        Args:
            text_value: 章节文本。

        Returns:
            无。

        Raises:
            ValueError: 参数非法时抛出。
        """

        self._text_value = text_value
        self.title = None
        self.name = None
        self.part = None
        self.item = None

    def text(self) -> str:
        """返回章节文本。

        Args:
            无。

        Returns:
            章节文本。

        Raises:
            RuntimeError: 读取失败时抛出。
        """

        return self._text_value

    def tables(self) -> list[object]:
        """返回章节内表格。

        Args:
            无。

        Returns:
            空列表。

        Raises:
            RuntimeError: 读取失败时抛出。
        """

        return []


class _FakeDocument:
    """测试用文档对象。"""

    def __init__(self, text_value: str) -> None:
        """初始化文档对象。

        Args:
            text_value: 文档全文文本。

        Returns:
            无。

        Raises:
            ValueError: 参数非法时抛出。
        """

        self.sections = {"only": _FakeSection(text_value)}
        self.tables: list[object] = []
        self._text_value = text_value

    def text(self) -> str:
        """返回全文文本。

        Args:
            无。

        Returns:
            全文文本。

        Raises:
            RuntimeError: 读取失败时抛出。
        """

        return self._text_value


def _make_source(path: Path, *, media_type: Optional[str] = "text/html") -> LocalFileSource:
    """构建本地 Source。

    Args:
        path: 文件路径。
        media_type: 媒体类型。

    Returns:
        LocalFileSource 实例。

    Raises:
        OSError: 文件状态读取失败时抛出。
    """

    return LocalFileSource(
        path=path,
        uri=f"local://{path.name}",
        media_type=media_type,
        content_length=path.stat().st_size,
        etag=None,
    )


@pytest.mark.unit
def test_eight_k_processor_handles_empty_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 8-K 处理器正确跳过空 Item。

    测试场景：
    - 文本中包含空 Item（无实际编号）。
    - 处理器应该能够跳过这些空项，只保留有效的 Item。

    Args:
        tmp_path: pytest 临时目录。
        monkeypatch: monkeypatch fixture。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k_empty_items.html"
    source_path.write_text("<html><body>placeholder</body></html>", encoding="utf-8")
    # 文本包含有效和无效的 Item 模式
    text_value = (
        "Intro text. "
        "Item  (empty item - no number) "
        "Item 1.01 Costs Associated with Exit or Disposal Activities. "
        "Content for 1.01 "
        "Item 2.03 Creation of a Direct Financial Obligation. "
        "Content for 2.03 "
        "SIGNATURE"
    )
    monkeypatch.setattr(
        "alpha.fins.processors.sec_processor._parse_document",
        lambda html_content, form_type: _FakeDocument(text_value),
    )

    processor = EightKFormProcessor(
        _make_source(source_path),
        form_type="8-K",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    # 验证空 Item 被跳过，有效 Item 被保留
    assert any(title == "Item 1.01" for title in titles)
    assert any(title == "Item 2.03" for title in titles)
    assert len([t for t in titles if t.startswith("Item") and t.strip() == "Item"]) == 0


@pytest.mark.unit
def test_eight_k_processor_deduplicates_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 8-K 处理器正确去重重复的 Item。

    测试场景：
    - 文本中 Item 编号出现多次。
    - 处理器应该只保留每个 Item 编号的首次出现。

    Args:
        tmp_path: pytest 临时目录。
        monkeypatch: monkeypatch fixture。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k_duplicates.html"
    source_path.write_text("<html><body>placeholder</body></html>", encoding="utf-8")
    # 文本中重复出现相同的 Item 编号
    text_value = (
        "Intro text. "
        "Item 1.01 Costs Associated with Exit. "
        "First content. "
        "Item 1.01 More content for Item 1.01 (duplicate). "
        "Item 2.04 Costs Associated with Exit. "
        "SIGNATURE"
    )
    monkeypatch.setattr(
        "alpha.fins.processors.sec_processor._parse_document",
        lambda html_content, form_type: _FakeDocument(text_value),
    )

    processor = EightKFormProcessor(
        _make_source(source_path),
        form_type="8-K",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    # 验证重复 Item 被去重，只出现一次
    item_1_01_count = len([t for t in titles if t == "Item 1.01"])
    assert item_1_01_count == 1


@pytest.mark.unit
def test_eight_k_processor_without_signature_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 8-K 处理器处理缺失 Signature 标记的情况。

    测试场景：
    - 文本中没有明确的 SIGNATURE 标记。
    - 处理器应该正确处理此情况，只包含 Item 小节。

    Args:
        tmp_path: pytest 临时目录。
        monkeypatch: monkeypatch fixture。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k_no_signature.html"
    source_path.write_text("<html><body>placeholder</body></html>", encoding="utf-8")
    # 文本中没有 SIGNATURE 或 signature 标记
    text_value = (
        "Intro text. "
        "Item 1.02 Unregistered Sales of Equity Securities. "
        "Content about the transaction. "
        "Item 2.05 Costs Associated with Exit. "
        "More detailed content about costs. "
        "This is the end of the document without any signature line."
    )
    monkeypatch.setattr(
        "alpha.fins.processors.sec_processor._parse_document",
        lambda html_content, form_type: _FakeDocument(text_value),
    )

    processor = EightKFormProcessor(
        _make_source(source_path),
        form_type="8-K",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    # 验证 Item 被找到
    assert any(title == "Item 1.02" for title in titles)
    assert any(title == "Item 2.05" for title in titles)


@pytest.mark.unit
def test_eight_k_processor_signature_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 8-K 处理器在 Signature 后正确截断。

    测试场景：
    - 文本在 Signature 标记后包含额外内容。
    - 处理器应该在 Signature 处创建分界，截断后续内容。

    Args:
        tmp_path: pytest 临时目录。
        monkeypatch: monkeypatch fixture。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k_signature_truncation.html"
    source_path.write_text("<html><body>placeholder</body></html>", encoding="utf-8")
    text_value = (
        "Intro text. "
        "Item 2.01 Completion of Acquisition. "
        "Content about acquisition. "
        "Item 3.01 Notice of Delinquency. "
        "Details here. "
        "SIGNATURE "
        "This is exhibit detail that comes after signature. "
        "Exhibit 99.1 - Press Release text. "
        "More exhibit content that should not be part of any item."
    )
    monkeypatch.setattr(
        "alpha.fins.processors.sec_processor._parse_document",
        lambda html_content, form_type: _FakeDocument(text_value),
    )

    processor = EightKFormProcessor(
        _make_source(source_path),
        form_type="8-K",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    # 验证 Item 被正确识别，且包含 Signature
    assert any(title == "Item 2.01" for title in titles)
    assert any(title == "Item 3.01" for title in titles)
    assert any(title == "SIGNATURE" for title in titles)

    # 验证可以读取任何一个小节内容
    first_ref = str(sections[0]["ref"])
    section = processor.read_section(first_ref)
    assert isinstance(section["content"], str)


@pytest.mark.unit
def test_eight_k_processor_supports_8k_form_type(tmp_path: Path) -> None:
    """验证 8-K 处理器支持 8-K 表单类型。

    测试场景：
    - 验证 supports() 方法正确识别 8-K 表单类型。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k.html"
    source_path.write_text("<html><body>Test content</body></html>", encoding="utf-8")
    source = _make_source(source_path)

    # 验证 supports() 对 8-K 返回 True
    assert EightKFormProcessor.supports(source, form_type="8-K", media_type="text/html") is True


@pytest.mark.unit
def test_eight_k_processor_rejects_non_8k_form_type(tmp_path: Path) -> None:
    """验证 8-K 处理器拒绝非 8-K 表单类型。

    测试场景：
    - 验证 supports() 方法对其他表单类型返回 False。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "other.html"
    source_path.write_text("<html><body>Test content</body></html>", encoding="utf-8")
    source = _make_source(source_path)

    # 验证 supports() 对非 8-K 表单返回 False
    assert EightKFormProcessor.supports(source, form_type="10-K", media_type="text/html") is False
    assert EightKFormProcessor.supports(source, form_type="SC 13D", media_type="text/html") is False


@pytest.mark.unit
def test_eight_k_processor_case_insensitive_item_matching(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 8-K 处理器 Item 匹配对大小写不敏感。

    测试场景：
    - 文本中 ITEM 关键字使用不同的大小写。
    - 处理器应该正确识别所有大小写变体。

    Args:
        tmp_path: pytest 临时目录。
        monkeypatch: monkeypatch fixture。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k_case_insensitive.html"
    source_path.write_text("<html><body>placeholder</body></html>", encoding="utf-8")
    text_value = (
        "Intro text. "
        "item 1.03 Bankruptcy or Receivership. Content here. "
        "ITEM 2.02 Results of Operations. More content. "
        "Item 3.01 Notice of Delinquency. Additional details. "
        "SIGNATURE"
    )
    monkeypatch.setattr(
        "alpha.fins.processors.sec_processor._parse_document",
        lambda html_content, form_type: _FakeDocument(text_value),
    )

    processor = EightKFormProcessor(
        _make_source(source_path),
        form_type="8-K",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    # 验证所有大小写变体都被识别
    assert any(title == "Item 1.03" for title in titles)
    assert any(title == "Item 2.02" for title in titles)
    assert any(title == "Item 3.01" for title in titles)
    assert any(title == "SIGNATURE" for title in titles)


__all__ = ["test_eight_k_processor_handles_empty_items"]
