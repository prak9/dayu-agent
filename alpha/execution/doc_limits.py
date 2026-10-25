"""文档工具限制配置。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocToolLimits:
    """文档工具限制配置。

    Attributes:
        list_files_max: `list_files` 最大返回文件数。
        get_sections_max: `get_file_sections` 最大返回章节数。
        search_files_max_results: `search_files` 最大返回命中数。
        read_file_max_chars: `read_file` 最大返回字符数（超出由 ToolRegistry 截断）。
        read_file_section_max_chars: `read_file_section` 最大返回字符数（超出由 ToolRegistry 截断）。
    """

    list_files_max: int = 200
    get_sections_max: int = 200
    search_files_max_results: int = 50
    read_file_max_chars: int = 80_000
    read_file_section_max_chars: int = 50_000
