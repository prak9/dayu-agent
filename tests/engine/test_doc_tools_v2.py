"""
文档工具测试 - list_files / get_file_sections / search_files / read_file / read_file_section

覆盖范围：
- 4 个既有工具的基础功能和边界情况
- get_file_sections 新增字段验证（ref/level/parent_ref/table_refs/table_count）
- search_files 新增字段验证（section_ref/section_title/snippet）
- read_file_section 正常路径、无效 ref、不支持格式
- 处理器路径（Markdown/HTML）和降级路径（txt 等）
"""
import builtins
import json
from pathlib import Path
from typing import Any

import pytest

from alpha.engine import ToolRegistry, register_doc_tools
from alpha.engine.exceptions import FileAccessError, ToolArgumentError
from alpha.engine.tools import doc_tools


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _extract_data(result):
    """从工具执行结果中提取 value 值。"""
    return result["value"]


def _create_registry_with_path(path: Path) -> ToolRegistry:
    """创建注册了指定路径白名单的 ToolRegistry 并注册 doc_tools。"""
    registry = ToolRegistry()
    registry.register_allowed_paths([path])
    register_doc_tools(registry)
    return registry

def test_doc_tool_schema_descriptions_follow_workflow(tmp_path: Path) -> None:
    """验证文档工具 schema 文案按工作流解释参数来源与后续动作。"""

    registry = _create_registry_with_path(tmp_path)
    schemas = registry.get_schemas()

    list_schema = next(item for item in schemas if item.get("function", {}).get("name") == "list_files")
    sections_schema = next(item for item in schemas if item.get("function", {}).get("name") == "get_file_sections")
    read_section_schema = next(item for item in schemas if item.get("function", {}).get("name") == "read_file_section")

    directory_desc = list_schema["function"]["parameters"]["properties"]["directory"]["description"]
    file_path_desc = sections_schema["function"]["parameters"]["properties"]["file_path"]["description"]
    ref_desc = read_section_schema["function"]["parameters"]["properties"]["ref"]["description"]

    assert "先用它列出文件" in directory_desc
    assert "优先使用 list_files 返回的 files[].path" in file_path_desc
    assert "必须来自 get_file_sections 返回的 sections[].ref" in ref_desc
    assert "不要猜 ref" in ref_desc
    assert "Directory path" not in directory_desc


# ---------------------------------------------------------------------------
# list_files
# ---------------------------------------------------------------------------

class TestListFiles:
    """list_files 工具测试。"""

    def test_basic(self, tmp_path: Path):
        """基本功能：按 pattern 过滤 + 递归搜索。"""
        (tmp_path / "a.txt").write_text("A", encoding="utf-8")
        (tmp_path / "b.md").write_text("B", encoding="utf-8")
        sub_dir = tmp_path / "sub"
        sub_dir.mkdir()
        (sub_dir / "c.txt").write_text("C", encoding="utf-8")

        registry = _create_registry_with_path(tmp_path)
        result = registry.execute("list_files", {
            "directory": str(tmp_path),
            "pattern": "*.txt",
            "recursive": True,
            "limit": 10,
        })

        assert result["ok"] is True
        data = _extract_data(result)
        names = {item["name"] for item in data.get("files", [])}
        assert names == {"a.txt", "c.txt"}

    def test_non_dir(self, tmp_path: Path):
        """传入文件路径应失败。"""
        file_path = tmp_path / "file.txt"
        file_path.write_text("x", encoding="utf-8")

        registry = _create_registry_with_path(tmp_path)
        result = registry.execute("list_files", {"directory": str(file_path)})

        assert result["ok"] is False
        assert result["error"] == "permission_denied"

    def test_stat_error_skips(self, tmp_path: Path, monkeypatch):
        """stat 失败的文件应被跳过而非中断。"""
        (tmp_path / "a.txt").write_text("A", encoding="utf-8")
        (tmp_path / "b.txt").write_text("B", encoding="utf-8")

        original_stat = Path.stat
        original_is_file = Path.is_file

        def fake_stat(self, *args, **kwargs):
            if self.name == "b.txt":
                raise OSError("stat failed")
            return original_stat(self)

        def fake_is_file(self):
            if self.name in {"a.txt", "b.txt"}:
                return True
            return original_is_file(self)

        monkeypatch.setattr(Path, "stat", fake_stat)
        monkeypatch.setattr(Path, "is_file", fake_is_file)

        registry = _create_registry_with_path(tmp_path)
        result = registry.execute("list_files", {
            "directory": str(tmp_path), "pattern": "*.txt",
        })

        assert result["ok"] is True
        data = _extract_data(result)
        names = {item["name"] for item in data.get("files", [])}
        assert "a.txt" in names
        assert "b.txt" not in names


# ---------------------------------------------------------------------------
# get_file_sections
# ---------------------------------------------------------------------------

class TestGetFileSections:
    """get_file_sections 工具测试。"""

    def test_markdown_processor_path(self, tmp_path: Path):
        """Markdown 文件应走 processor 路径，返回 ref/level/parent_ref 等新字段。"""
        md = tmp_path / "doc.md"
        md.write_text(
            "# Title\nIntro\n\n## Section A\nA1\nA2\n\n## Section B\nB1\n",
            encoding="utf-8",
        )

        registry = _create_registry_with_path(tmp_path)
        result = registry.execute("get_file_sections", {
            "file_path": str(md),
            "limit": 10,
        })

        assert result["ok"] is True
        data = _extract_data(result)
        sections = data.get("sections", [])
        titles = [s["title"] for s in sections]
        assert titles == ["Title", "Section A", "Section B"]

        # 验证新增字段
        s0 = sections[0]
        assert s0["ref"] is not None  # processor 路径应有 ref
        assert s0["level"] == 1
        assert s0["parent_ref"] is None  # 顶级节点
        assert isinstance(s0["table_refs"], list)
        assert isinstance(s0["table_count"], int)
        assert s0["table_count"] >= 0

        # 子章节应有 parent_ref
        s1 = sections[1]
        assert s1["level"] == 2
        assert s1["parent_ref"] == s0["ref"]

    def test_html_processor_path(self, tmp_path: Path):
        """HTML 文件应走 BSProcessor 路径。"""
        html = tmp_path / "page.html"
        html.write_text(
            "<html><body><h1>Main Title</h1><p>Content</p>"
            "<h2>Sub Section</h2><p>Detail</p></body></html>",
            encoding="utf-8",
        )

        registry = _create_registry_with_path(tmp_path)
        result = registry.execute("get_file_sections", {
            "file_path": str(html),
            "limit": 10,
        })

        assert result["ok"] is True
        data = _extract_data(result)
        sections = data.get("sections", [])
        # HTML 至少有一个 section
        assert len(sections) >= 1
        # 验证新字段存在
        s0 = sections[0]
        assert "ref" in s0
        assert "level" in s0
        assert "table_refs" in s0
        assert "table_count" in s0

    def test_fallback_txt(self, tmp_path: Path):
        """不支持的格式（txt）应 fallback 返回单个 section。"""
        txt = tmp_path / "note.txt"
        txt.write_text("Line 1\nLine 2", encoding="utf-8")

        registry = _create_registry_with_path(tmp_path)
        result = registry.execute("get_file_sections", {
            "file_path": str(txt),
        })

        assert result["ok"] is True
        data = _extract_data(result)
        sections = data.get("sections", [])
        assert len(sections) == 1
        assert sections[0]["title"] == "note.txt"
        # 降级路径的新字段应为 None/0
        assert sections[0]["ref"] is None
        assert sections[0]["level"] is None
        assert sections[0]["table_refs"] == []
        assert sections[0]["table_count"] == 0

    def test_unicode_decode_fallback(self, tmp_path: Path, monkeypatch):
        """无法解码的文件应 fallback。"""
        txt = tmp_path / "bad.txt"
        txt.write_bytes(b"\xff\xfe\xfd")

        def bad_open(*args: Any, **kwargs: Any):
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "bad")

        monkeypatch.setattr(builtins, "open", bad_open)

        registry = _create_registry_with_path(tmp_path)
        result = registry.execute("get_file_sections", {"file_path": str(txt)})

        assert result["ok"] is True
        data = _extract_data(result)
        assert data["total_lines"] == 0

    def test_markdown_with_tables(self, tmp_path: Path):
        """包含表格的 Markdown 文件应在 table_refs/table_count 中反映。"""
        md = tmp_path / "tables.md"
        md.write_text(
            "# Report\n\n"
            "| Col A | Col B |\n"
            "|-------|-------|\n"
            "| 1     | 2     |\n"
            "\n"
            "## Detail\n"
            "Some text\n",
            encoding="utf-8",
        )

        registry = _create_registry_with_path(tmp_path)
        result = registry.execute("get_file_sections", {
            "file_path": str(md),
            "limit": 10,
        })

        assert result["ok"] is True
        data = _extract_data(result)
        sections = data.get("sections", [])
        # 第一个 section 应包含 1 个表格
        report_section = sections[0]
        assert report_section["table_count"] >= 1
        assert len(report_section["table_refs"]) >= 1


# ---------------------------------------------------------------------------
# search_files
# ---------------------------------------------------------------------------

class TestSearchFiles:
    """search_files 工具测试。"""

    def test_basic_with_new_fields(self, tmp_path: Path):
        """基本搜索应返回 section_ref/section_title/snippet 新字段。"""
        (tmp_path / "a.txt").write_text("Target line here\nOther", encoding="utf-8")
        (tmp_path / "b.md").write_text("No match here", encoding="utf-8")

        registry = _create_registry_with_path(tmp_path)
        result = registry.execute("search_files", {
            "directory": str(tmp_path),
            "query": "target",
            "include_types": ["txt"],
            "limit": 5,
        })

        assert result["ok"] is True
        data = _extract_data(result)
        matches = data.get("matches", [])
        assert len(matches) >= 1

        m = matches[0]
        assert m["file"] == "a.txt"
        # 新字段存在
        assert "snippet" in m
        assert "ref" in m
        assert "section_title" in m
        assert "matched_line_content" in m
        # txt 文件走降级路径，应有 line_number 和 matched_line_content
        assert m["line_number"] is not None
        assert m["matched_line_content"] is not None

    def test_markdown_processor_search(self, tmp_path: Path):
        """Markdown 文件搜索应走 processor 路径，返回 section_ref/section_title。"""
        md = tmp_path / "doc.md"
        md.write_text(
            "# Introduction\n\nThis is the overview.\n\n"
            "## Revenue Analysis\n\nRevenue grew by 20% year-over-year.\n",
            encoding="utf-8",
        )

        registry = _create_registry_with_path(tmp_path)
        result = registry.execute("search_files", {
            "directory": str(tmp_path),
            "query": "revenue",
            "limit": 5,
        })

        assert result["ok"] is True
        data = _extract_data(result)
        matches = data.get("matches", [])
        assert len(matches) >= 1

        m = matches[0]
        assert m["file"] == "doc.md"
        # processor 路径应有 section 信息
        assert m["ref"] is not None
        assert m["section_title"] is not None
        assert m["snippet"] is not None and len(m["snippet"]) > 0
        # processor 路径的 line_number 和 matched_line_content 为 None
        assert m["line_number"] is None
        assert m["matched_line_content"] is None

    def test_no_matched_snippet_preview_field(self, tmp_path: Path):
        """确认旧字段 matched_snippet_preview 已被移除。"""
        (tmp_path / "a.txt").write_text("findme", encoding="utf-8")

        registry = _create_registry_with_path(tmp_path)
        result = registry.execute("search_files", {
            "directory": str(tmp_path),
            "query": "findme",
            "limit": 5,
        })

        assert result["ok"] is True
        data = _extract_data(result)
        matches = data.get("matches", [])
        assert len(matches) >= 1
        assert "matched_snippet_preview" not in matches[0]

    def test_skips_unreadable(self, tmp_path: Path, monkeypatch):
        """无法读取的文件应被跳过。"""
        good = tmp_path / "good.txt"
        bad = tmp_path / "bad.txt"
        good.write_text("findme", encoding="utf-8")
        bad.write_bytes(b"\xff\xfe\xfd")

        real_open = builtins.open

        def selective_open(path, *args, **kwargs):
            if str(path) == str(bad):
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "bad")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", selective_open)

        registry = _create_registry_with_path(tmp_path)
        result = registry.execute("search_files", {
            "directory": str(tmp_path),
            "query": "findme",
        })

        assert result["ok"] is True
        data = _extract_data(result)
        assert data["total_matches"] >= 1


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------

class TestReadFile:
    """read_file 工具测试。"""

    def test_range(self, tmp_path: Path):
        """按行范围读取应只返回指定行。"""
        txt = tmp_path / "readme.txt"
        txt.write_text("Line 1\nLine 2\nLine 3", encoding="utf-8")

        registry = _create_registry_with_path(tmp_path)
        result = registry.execute("read_file", {
            "file_path": str(txt),
            "start_line": 2,
            "end_line": 3,
        })

        assert result["ok"] is True
        data = _extract_data(result)
        assert "Line 2" in data.get("content", "")
        assert "Line 1" not in data.get("content", "")

    def test_invalid_line_range(self, tmp_path: Path):
        """无效行号应抛出 ToolArgumentError。"""
        txt = tmp_path / "readme.txt"
        txt.write_text("Line 1\nLine 2", encoding="utf-8")

        registry = _create_registry_with_path(tmp_path)
        read_tool = registry.tools["read_file"]

        with pytest.raises(ToolArgumentError):
            read_tool(file_path=str(txt), start_line=0, end_line=1)

        with pytest.raises(ToolArgumentError):
            read_tool(file_path=str(txt), start_line=2, end_line=1)

    def test_all_encodings_fail(self, tmp_path: Path, monkeypatch):
        """所有编码尝试失败应抛出 FileAccessError。"""
        txt = tmp_path / "bad.txt"
        txt.write_bytes(b"\xff\xfe\xfd")

        def bad_open(*args: Any, **kwargs: Any):
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "bad")

        monkeypatch.setattr(builtins, "open", bad_open)

        registry = _create_registry_with_path(tmp_path)
        read_tool = registry.tools["read_file"]

        with pytest.raises(FileAccessError):
            read_tool(file_path=str(txt))


# ---------------------------------------------------------------------------
# read_file_section
# ---------------------------------------------------------------------------

class TestReadFileSection:
    """read_file_section 工具测试。"""

    def test_basic_markdown(self, tmp_path: Path):
        """Markdown 文件按 ref 读取应返回章节内容。"""
        md = tmp_path / "doc.md"
        md.write_text(
            "# Title\nIntro text\n\n## Section A\nA content line 1\nA content line 2\n\n## Section B\nB text\n",
            encoding="utf-8",
        )

        registry = _create_registry_with_path(tmp_path)

        # 先获取 sections 拿到 ref
        sections_result = registry.execute("get_file_sections", {
            "file_path": str(md),
            "limit": 10,
        })
        assert sections_result["ok"] is True
        sections = _extract_data(sections_result)["sections"]

        # 读取第二个 section (Section A)
        section_a = sections[1]
        assert section_a["title"] == "Section A"
        ref = section_a["ref"]
        assert ref is not None

        result = registry.execute("read_file_section", {
            "file_path": str(md),
            "ref": ref,
        })

        assert result["ok"] is True
        data = _extract_data(result)
        assert data["ref"] == ref
        assert data["title"] == "Section A"
        assert "A content" in data["content"]
        assert isinstance(data["tables"], list)
        assert isinstance(data["children"], list)
        assert isinstance(data["content_word_count"], int)
        assert data["content_word_count"] > 0

    def test_html_section(self, tmp_path: Path):
        """HTML 文件按 ref 读取应正常工作。"""
        html = tmp_path / "page.html"
        html.write_text(
            "<html><body><h1>Main</h1><p>Paragraph one</p>"
            "<h2>Sub</h2><p>Paragraph two</p></body></html>",
            encoding="utf-8",
        )

        registry = _create_registry_with_path(tmp_path)

        sections_result = registry.execute("get_file_sections", {
            "file_path": str(html),
            "limit": 10,
        })
        assert sections_result["ok"] is True
        sections = _extract_data(sections_result)["sections"]
        assert len(sections) >= 1

        ref = sections[0]["ref"]
        result = registry.execute("read_file_section", {
            "file_path": str(html),
            "ref": ref,
        })

        assert result["ok"] is True
        data = _extract_data(result)
        assert data["ref"] == ref
        assert "content" in data

    def test_invalid_ref(self, tmp_path: Path):
        """无效 ref 应返回失败。"""
        md = tmp_path / "doc.md"
        md.write_text("# Title\nText\n", encoding="utf-8")

        registry = _create_registry_with_path(tmp_path)
        result = registry.execute("read_file_section", {
            "file_path": str(md),
            "ref": "s_9999",
        })

        assert result["ok"] is False

    def test_unsupported_format(self, tmp_path: Path):
        """不支持格式的文件应返回失败。"""
        txt = tmp_path / "note.txt"
        txt.write_text("Some content", encoding="utf-8")

        registry = _create_registry_with_path(tmp_path)
        result = registry.execute("read_file_section", {
            "file_path": str(txt),
            "ref": "s_0001",
        })

        assert result["ok"] is False

    def test_children_navigation(self, tmp_path: Path):
        """子章节应出现在 children 中。"""
        md = tmp_path / "hierarchy.md"
        md.write_text(
            "# Root\nRoot text\n\n## Child A\nChild A text\n\n## Child B\nChild B text\n",
            encoding="utf-8",
        )

        registry = _create_registry_with_path(tmp_path)

        sections_result = registry.execute("get_file_sections", {
            "file_path": str(md),
            "limit": 10,
        })
        sections = _extract_data(sections_result)["sections"]
        root_ref = sections[0]["ref"]

        result = registry.execute("read_file_section", {
            "file_path": str(md),
            "ref": root_ref,
        })

        assert result["ok"] is True
        data = _extract_data(result)
        children = data["children"]
        assert len(children) == 2
        child_titles = {c["title"] for c in children}
        assert child_titles == {"Child A", "Child B"}
        for c in children:
            assert c["ref"] is not None
            assert c["level"] == 2

    def test_section_with_table(self, tmp_path: Path):
        """包含表格的章节应在 tables 字段中反映。"""
        md = tmp_path / "report.md"
        md.write_text(
            "# Summary\n\n"
            "| Key | Value |\n"
            "|-----|-------|\n"
            "| A   | 100   |\n"
            "\n"
            "Text after table.\n",
            encoding="utf-8",
        )

        registry = _create_registry_with_path(tmp_path)

        sections_result = registry.execute("get_file_sections", {
            "file_path": str(md),
            "limit": 10,
        })
        sections = _extract_data(sections_result)["sections"]
        ref = sections[0]["ref"]

        result = registry.execute("read_file_section", {
            "file_path": str(md),
            "ref": ref,
        })

        assert result["ok"] is True
        data = _extract_data(result)
        assert len(data["tables"]) >= 1


# ---------------------------------------------------------------------------
# 路径安全
# ---------------------------------------------------------------------------

class TestPathSecurity:
    """路径安全验证测试。"""

    def test_denied(self, tmp_path: Path):
        """访问白名单外的文件应返回 permission_denied。"""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        (allowed / "ok.txt").write_text("OK", encoding="utf-8")

        registry = _create_registry_with_path(allowed)

        outside = tmp_path / "outside.txt"
        outside.write_text("NO", encoding="utf-8")

        result = registry.execute("read_file", {
            "file_path": str(outside),
        })

        assert result["ok"] is False
        assert result["error"] == "permission_denied"
