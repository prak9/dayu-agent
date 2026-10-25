"""
测试 when_tag 条件块解析
"""
from pathlib import Path

import pytest

from alpha.prompt_template_rendering import replace_template_variables
from alpha.prompting.prompt_renderer import load_prompt
from alpha.prompting.prompt_renderer import (
    PromptParseError,
    parse_when_tag_blocks,
    parse_when_tool_blocks,
)


def test_when_tag_blocks_render(tmp_path: Path):
    template = (
        "Before\n"
        "<when_tag doc>DOC\n</when_tag>\n"
        "<when_tag fin>FIN\n</when_tag>\n"
        "After\n"
    )
    template_path = tmp_path / "guide.md"
    template_path.write_text(template, encoding="utf-8")

    rendered = load_prompt(template, variables=None, tool_names=set(), tag_names={"doc"})

    assert "DOC" in rendered
    assert "FIN" not in rendered
    assert "Before" in rendered
    assert "After" in rendered


def test_when_tag_blocks_comma_all_match(tmp_path: Path):
    template = "<when_tag doc, fin>OK</when_tag>"
    template_path = tmp_path / "guide.md"
    template_path.write_text(template, encoding="utf-8")

    rendered = load_prompt(template, variables=None, tool_names=set(), tag_names={"fin"})
    assert rendered.strip() == ""


def test_when_tag_blocks_comma_all_match_success(tmp_path: Path):
    template = "<when_tag doc, fin>OK</when_tag>"
    template_path = tmp_path / "guide.md"
    template_path.write_text(template, encoding="utf-8")

    rendered = load_prompt(template, variables=None, tool_names=set(), tag_names={"doc", "fin"})
    assert rendered.strip() == "OK"


def test_when_tool_blocks_inline_and_standalone():
    template = (
        "Start <when_tool a>INLINE</when_tool> End\n"
        "<when_tool a>\nBLOCK\n</when_tool>\n"
    )

    rendered = parse_when_tool_blocks(template, {"a"})
    assert "INLINE" in rendered
    assert "BLOCK" in rendered


def test_when_tool_blocks_missing_close_raises():
    template = "<when_tool a>oops"
    with pytest.raises(PromptParseError):
        parse_when_tool_blocks(template, {"a"})


def test_when_tag_blocks_missing_close_raises():
    template = "<when_tag a>oops"
    with pytest.raises(PromptParseError):
        parse_when_tag_blocks(template, {"a"})


def test_load_prompt_no_conditions_or_vars():
    template = "  hello  "
    rendered = load_prompt(template, variables=None, tool_names=None, tag_names=None)
    assert rendered == "hello"


def test_parse_when_tag_blocks_inline_end_of_text():
    template = "prefix <when_tag a>VALUE</when_tag>"
    rendered = parse_when_tag_blocks(template, {"a"})
    assert rendered == "prefix VALUE"


def test_load_prompt_empty_template_returns_empty():
    assert load_prompt("", variables={"x": 1}, tool_names={"a"}, tag_names={"t"}) == ""


def test_replace_template_variables_keeps_unknown_variable():
    rendered = replace_template_variables("A={{known}}, B={{unknown}}", {"known": 1})
    assert rendered == "A=1, B={{unknown}}"
