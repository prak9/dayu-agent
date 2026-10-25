"""HTML 四段式处理流水线测试。"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any, cast

import pytest

from alpha.engine.processors.html_extraction import extract_main_content
from alpha.engine.processors.html_markdown import render_html_to_markdown
from alpha.engine.processors.html_normalization import normalize_html_fragment
from alpha.engine.processors.html_pipeline import HtmlPipelineStageError, convert_html_to_llm_markdown


@pytest.mark.unit
def test_extract_main_content_prefers_trafilatura_when_quality_good(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证正文质量足够时优先采用 trafilatura。"""

    fake_module = ModuleType("trafilatura")
    cast(Any, fake_module).extract = lambda html, **kwargs: (
        "<article><h1>标题</h1><p>第一段正文足够长，包含清晰信息，并补充经营变化、渠道反馈和用户行为等关键细节。</p><p>第二段继续展开事件背景，补充销量、价格带和市场反应，确保文本长度足以通过质量门。</p></article>"
    )
    monkeypatch.setitem(sys.modules, "trafilatura", fake_module)
    monkeypatch.delitem(sys.modules, "readability", raising=False)

    result = extract_main_content("<html><head><title>标题</title></head><body></body></html>")

    assert result.extractor_source == "trafilatura"
    assert result.quality_report.is_usable is True


@pytest.mark.unit
def test_extract_main_content_falls_back_to_readability_when_trafilatura_quality_poor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 trafilatura 质量不足时会自动回退 readability。"""

    fake_trafilatura = ModuleType("trafilatura")
    cast(Any, fake_trafilatura).extract = lambda html, **kwargs: (
        "<div><a href='/a'>Home</a><a href='/b'>News</a><a href='/c'>Markets</a></div>"
    )
    monkeypatch.setitem(sys.modules, "trafilatura", fake_trafilatura)

    fake_readability = ModuleType("readability")

    class _FakeDocument:
        """模拟 readability.Document。"""

        def __init__(self, html: str) -> None:
            self._html = html

        def summary(self, html_partial: bool = True) -> str:
            _ = html_partial
            return (
                "<article><p>第一段正文足够长，说明业务进展、渠道变化和定价策略，并包含多个可用于分析的细节。</p>"
                "<p>第二段继续说明影响与数据，补充销量、毛利率和市场反馈等信息，确保质量评估通过。</p></article>"
            )

        def short_title(self) -> str:
            return "可读标题"

    cast(Any, fake_readability).Document = _FakeDocument
    monkeypatch.setitem(sys.modules, "readability", fake_readability)

    result = extract_main_content("<html><head><title>原始标题</title></head><body></body></html>")

    assert result.extractor_source == "readability"
    assert result.title == "可读标题"
    assert result.quality_report.is_usable is True


@pytest.mark.unit
def test_extract_main_content_falls_back_to_bs_when_other_extractors_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证双通道抽取都不可用时会回退到 BS 规则抽取。"""

    monkeypatch.delitem(sys.modules, "trafilatura", raising=False)
    monkeypatch.delitem(sys.modules, "readability", raising=False)

    html = """
    <html>
      <head><title>回退标题</title></head>
      <body>
        <article>
          <p>第一段正文用于验证 BS 回退路径能够抽到主体。</p>
          <p>第二段正文继续补充背景信息，避免被判定为 too_short。</p>
        </article>
      </body>
    </html>
    """

    result = extract_main_content(html)

    assert result.extractor_source == "bs_fallback"
    assert "BS 回退路径" in result.text


@pytest.mark.unit
def test_normalize_html_fragment_removes_noise_and_normalizes_tags() -> None:
    """验证 HTML 规范化会移除噪音并统一强调标签。"""

    html = """
    <article class="content" style="color:red">
      <script>alert(1)</script>
      <p><b>重点</b><i>提示</i></p>
      <div></div>
    </article>
    """

    result = normalize_html_fragment(html)

    assert "<script" not in result.html
    assert "<strong>重点</strong>" in result.html
    assert "<em>提示</em>" in result.html
    assert "style=" not in result.html
    assert result.normalization_applied is True


@pytest.mark.unit
def test_render_html_to_markdown_falls_back_to_html2text(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 markdownify 失败时会自动回退 html2text。"""

    monkeypatch.setattr(
        "alpha.engine.processors.html_markdown._render_with_markdownify",
        lambda html: (_ for _ in ()).throw(RuntimeError("markdownify failed")),
    )

    fake_html2text = ModuleType("html2text")

    class _FakeHTML2Text:
        """模拟 html2text.HTML2Text。"""

        body_width = 0
        ignore_images = True
        ignore_emphasis = False
        ignore_links = False
        unicode_snob = True

        def handle(self, html: str) -> str:
            _ = html
            return "# fallback\n\nbody"

    cast(Any, fake_html2text).HTML2Text = _FakeHTML2Text
    monkeypatch.setitem(sys.modules, "html2text", fake_html2text)

    result = render_html_to_markdown("<h1>fallback</h1><p>body</p>")

    assert result.renderer_source == "html2text"
    assert "body" in result.markdown


@pytest.mark.unit
def test_convert_html_to_llm_markdown_returns_pipeline_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证四段式编排会返回统一元数据。"""

    monkeypatch.setattr("alpha.engine.processors.html_extraction.extract_with_trafilatura", lambda html, url="": None)
    monkeypatch.setattr("alpha.engine.processors.html_extraction.extract_with_readability", lambda html, url="": None)

    html = """
    <html>
      <head><title>流水线标题</title></head>
      <body>
        <article>
          <p>第一段正文说明产品发布与渠道反馈。</p>
          <p>第二段正文说明价格带、销量和市场反应。</p>
        </article>
      </body>
    </html>
    """

    result = convert_html_to_llm_markdown(html, url="https://example.com/article")

    assert result.title == "流水线标题"
    assert result.extractor_source == "bs_fallback"
    assert result.renderer_source == "markdownify"
    assert result.normalization_applied is True
    assert result.content_stats["markdown_length"] > 0


@pytest.mark.unit
def test_convert_html_to_llm_markdown_preserves_page_title_when_body_starts_with_subheading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证正文以子标题开头时仍会补回页面标题。

    Args:
        monkeypatch: pytest monkeypatch fixture。

    Returns:
        无。

    Raises:
        AssertionError: 断言失败时抛出。
    """

    monkeypatch.setattr("alpha.engine.processors.html_extraction.extract_with_trafilatura", lambda html, url="": None)
    monkeypatch.setattr("alpha.engine.processors.html_extraction.extract_with_readability", lambda html, url="": None)

    html = """
    <html>
      <head><title>页面总标题</title></head>
      <body>
        <article>
          <h2>小节摘要</h2>
          <p>第一段正文足够长，包含业务进展、渠道变化和市场反馈等关键信息。</p>
          <p>第二段正文继续补充价格带、销量表现和管理层口径，确保通过质量门。</p>
        </article>
      </body>
    </html>
    """

    result = convert_html_to_llm_markdown(html)

    assert result.title == "页面总标题"
    assert result.markdown.startswith("# 页面总标题")
    assert "## 小节摘要" in result.markdown


@pytest.mark.unit
def test_convert_html_to_llm_markdown_raises_stage_error_on_empty_html() -> None:
    """验证空 HTML 会抛出 extract 阶段错误。"""

    with pytest.raises(HtmlPipelineStageError) as exc_info:
        convert_html_to_llm_markdown("")

    assert exc_info.value.stage == "extract"
