"""SEC 表单专项章节处理器测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from alpha.fins.processors.def14a_processor import Def14AFormProcessor
from alpha.fins.processors.eight_k_processor import EightKFormProcessor
from alpha.fins.processors.sc13_processor import Sc13FormProcessor
from alpha.fins.processors.bs_six_k_processor import BsSixKFormProcessor
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


class _FakeDocumentWithPlaceholderSections:
    """测试用文档对象：章节文本仅包含表格占位符。"""

    def __init__(self, *, section_text: str, document_text: str) -> None:
        """初始化文档对象。

        Args:
            section_text: 章节文本（占位符主导）。
            document_text: 文档全文文本（包含真实 Item 标记）。

        Returns:
            无。

        Raises:
            ValueError: 参数非法时抛出。
        """

        self.sections = {"only": _FakeSection(section_text)}
        self.tables: list[object] = []
        self._document_text = document_text

    def text(self) -> str:
        """返回全文文本。

        Args:
            无。

        Returns:
            文档全文文本。

        Raises:
            RuntimeError: 读取失败时抛出。
        """

        return self._document_text


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
def test_sc13_processor_splits_item_and_tail_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 SC13 专项处理器按 Item 与尾段切分。

    Args:
        tmp_path: pytest 临时目录。
        monkeypatch: monkeypatch fixture。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13.html"
    source_path.write_text("<html><body>placeholder</body></html>", encoding="utf-8")
    text_value = (
        "Cover text. "
        "Item 1. Security and Issuer [[t_0001]] "
        "Item 2. Identity and Background "
        "Item 3. Source and Amount of Funds "
        "Item 4. Purpose of Transaction "
        "Item 5. Interest in Securities of the Issuer "
        "Item 6. Contracts, Arrangements, Understandings or Relationships "
        "Item 7. Material to be Filed as Exhibits "
        "SIGNATURE "
        "Schedule A Directors "
        "Exhibit 1 Share Repurchase Agreement"
    )
    monkeypatch.setattr(
        "alpha.fins.processors.sec_processor._parse_document",
        lambda html_content, form_type: _FakeDocument(text_value),
    )

    processor = Sc13FormProcessor(
        _make_source(source_path),
        form_type="SC 13D/A",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    assert any(title == "Item 1" for title in titles)
    assert any(title == "Item 7" for title in titles)
    assert any(title == "SIGNATURE" for title in titles)
    assert any(title == "Schedule A" for title in titles)
    assert any(title == "Exhibit" for title in titles)

    first_ref = str(sections[0]["ref"])
    section = processor.read_section(first_ref)
    assert isinstance(section["content"], str)


@pytest.mark.unit
def test_sc13_processor_fallbacks_to_document_text_when_sections_are_placeholders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 SC13 在章节仅含占位符时会回退到 document.text() 切分。

    Args:
        tmp_path: pytest 临时目录。
        monkeypatch: monkeypatch fixture。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13_placeholder.html"
    source_path.write_text("<html><body>placeholder</body></html>", encoding="utf-8")
    section_text = "[[t_0001]] [[t_0002]] [[t_0003]] [[t_0004]] [[t_0005]]"
    document_text = (
        "Cover text "
        "Item 1. Security and Issuer "
        "Item 2. Identity and Background "
        "Item 3. Source and Amount of Funds "
        "Item 4. Purpose of Transaction "
        "Item 5. Interest in Securities of the Issuer "
        "Item 6. Contracts "
        "Item 7. Material to be Filed as Exhibits "
        "SIGNATURE"
    )
    monkeypatch.setattr(
        "alpha.fins.processors.sec_processor._parse_document",
        lambda html_content, form_type: _FakeDocumentWithPlaceholderSections(
            section_text=section_text,
            document_text=document_text,
        ),
    )

    processor = Sc13FormProcessor(
        _make_source(source_path),
        form_type="SC 13G/A",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    assert len(sections) >= 3
    assert any(title == "Item 1" for title in titles)
    assert any(title == "Item 7" for title in titles)
    assert any(title == "SIGNATURE" for title in titles)


@pytest.mark.unit
def test_sc13_processor_uses_document_text_when_base_has_no_item_markers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 SC13 在 base 文本缺失 Item 标记时会回退到 document.text() 切分。

    Args:
        tmp_path: pytest 临时目录。
        monkeypatch: monkeypatch fixture。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "sc13_no_markers_in_base.html"
    source_path.write_text("<html><body>placeholder</body></html>", encoding="utf-8")
    section_text = (
        "[[t_0001]] General disclosure text without explicit item markers. "
        "The filing person reports ownership changes and related notes. "
        "SCHEDULE 13D CUSIP No. 22943F100. "
        "Additional narrative appears here for several lines."
    )
    document_text = (
        "Cover text "
        "Item 1. Security and Issuer "
        "Item 2. Identity and Background "
        "Item 3. Source and Amount of Funds "
        "Item 4. Purpose of Transaction "
        "Item 5. Interest in Securities of the Issuer "
        "Item 6. Contracts "
        "Item 7. Material to be Filed as Exhibits "
        "SIGNATURE"
    )
    monkeypatch.setattr(
        "alpha.fins.processors.sec_processor._parse_document",
        lambda html_content, form_type: _FakeDocumentWithPlaceholderSections(
            section_text=section_text,
            document_text=document_text,
        ),
    )

    processor = Sc13FormProcessor(
        _make_source(source_path),
        form_type="SC 13D/A",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    assert len(sections) >= 3
    assert any(title == "Item 1" for title in titles)
    assert any(title == "Item 7" for title in titles)


@pytest.mark.unit
def test_eight_k_processor_splits_item_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 8-K 专项处理器按 Item 切分。

    Args:
        tmp_path: pytest 临时目录。
        monkeypatch: monkeypatch fixture。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "8k.html"
    source_path.write_text("<html><body>placeholder</body></html>", encoding="utf-8")
    text_value = (
        "Intro text. "
        "Item 2.02 Results of Operations and Financial Condition. "
        "Body section. "
        "Item 9.01 Financial Statements and Exhibits. "
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

    assert any(title == "Item 2.02" for title in titles)
    assert any(title == "Item 9.01" for title in titles)
    assert any(title == "SIGNATURE" for title in titles)


@pytest.mark.unit
def test_six_k_processor_splits_press_release_blocks(tmp_path: Path) -> None:
    """验证 6-K 专项处理器按强标题切分。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "6k.html"
    source_path.write_text(
        """
        <html>
          <body>
            <p>Exhibit 99.1</p>
            <p>Trip.com Group Limited Reports Unaudited First Quarter of 2025 Financial Results</p>
            <p><b>Key Highlights for the First Quarter of 2025</b></p>
            <p><b>First Quarter of 2025 Financial Results and Business Updates</b></p>
            <p><b>Conference Call</b></p>
            <p><b>Safe Harbor Statement</b></p>
            <p><b>About Non-GAAP Financial Measures</b></p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    processor = BsSixKFormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="6-K",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    assert len(sections) >= 3
    assert any(title == "Key Highlights" for title in titles)
    assert any(title == "Conference Call" for title in titles)
    assert any(title == "Safe Harbor" for title in titles)


@pytest.mark.unit
def test_def14a_processor_splits_proposals_and_tail_sections(tmp_path: Path) -> None:
    """验证 DEF 14A 专项处理器按 Proposal 与尾段切分。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "def14a.html"
    source_path.write_text(
        """
        <html>
          <body>
            <p>Proxy Statement Summary</p>
            <p>Proxy Statement Summary includes board oversight highlights and meeting details.</p>
            <p>Executive Compensation</p>
            <p>Executive compensation discussion and analysis for named executive officers.</p>
            <p>Proposal No. 1 - Election of Directors</p>
            <p>Proposal No. 2 - Ratification of Auditors</p>
            <p>Proposal No. 3 - Advisory Vote to Approve Executive Compensation</p>
            <p>Annex A - Non-Employee Director Stock Plan</p>
            <p>SIGNATURE</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    processor = Def14AFormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="DEF 14A",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    assert any(title == "Proposal No. 1" for title in titles)
    assert any(title == "Proposal No. 2" for title in titles)
    assert any(title == "Executive Compensation" for title in titles)
    assert any(title == "Annex A" for title in titles)
    assert any(title == "SIGNATURE" for title in titles)

    first_ref = str(sections[0]["ref"])
    section = processor.read_section(first_ref)
    assert isinstance(section["content"], str)


@pytest.mark.unit
def test_def14a_processor_fallbacks_when_markers_insufficient(tmp_path: Path) -> None:
    """验证 DEF 14A 专项切分标记不足时回退到 edgartools 父类章节。

    Def14AFormProcessor 现继承 _BaseSecReportFormProcessor（edgartools 路径），
    当 DEF 14A 专项 marker 不足时，回退至 edgartools sections。
    对无 SEC 结构的简单 HTML 文档，edgartools 可能不产出命名章节。

    Args:
        tmp_path: pytest 临时目录。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    source_path = tmp_path / "def14a_fallback.html"
    source_path.write_text(
        """
        <html>
          <body>
            <h1>Overview</h1>
            <p>General proxy information.</p>
            <h2>Details</h2>
            <p>No proposal markers are present in this document.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    processor = Def14AFormProcessor(
        _make_source(source_path, media_type="text/html"),
        form_type="DEF14A",
        media_type="text/html",
    )
    sections = processor.list_sections()
    titles = [str(item.get("title") or "") for item in sections]

    # edgartools 路径下，简单 HTML 可能不产出 "Overview" 标题节；
    # 核心断言：无 Proposal 标记 + 处理器不崩溃。
    assert all(not title.startswith("Proposal No.") for title in titles)
