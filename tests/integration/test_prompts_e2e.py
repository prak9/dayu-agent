"""
Prompts 模板系统端到端测试

测试 load_prompt, parse_when_tool_blocks, parse_when_tag_blocks, replace_template_variables
使用真实复杂模板文件验证：
1. 嵌套条件块解析
2. 工具/标签条件渲染
3. 模板变量替换
4. 组合场景
"""
from pathlib import Path

import pytest

from alpha.prompt_template_rendering import replace_template_variables
from alpha.prompting.prompt_renderer import (
    load_prompt,
    parse_when_tool_blocks,
    parse_when_tag_blocks,
)


def test_load_complex_system_prompt(prompts_fixtures):
    """测试加载包含复杂嵌套条件块的系统 prompt"""
    template_path = prompts_fixtures / "system_prompt_complex.md"
    
    # 加载原始模板
    template = template_path.read_text(encoding="utf-8")
    
    assert len(template) > 0
    assert "<when_tool list_files>" in template
    assert "<when_tool get_file_sections>" in template
    assert "<when_tag doc>" in template
    assert "{{environment}}" in template


def test_nested_when_tool_blocks(prompts_fixtures):
    """测试嵌套 when_tool 块的解析"""
    template_path = prompts_fixtures / "system_prompt_complex.md"
    template = template_path.read_text(encoding="utf-8")
    
    # 场景1：只注册 list_files
    tool_names = {"list_files"}
    rendered = parse_when_tool_blocks(template, tool_names)
    
    assert "文件列表工具" in rendered
    assert "list_files" in rendered
    # 嵌套的 get_file_sections 块应该被移除
    # 但 get_file_sections 可能出现在 when_tag 块中（作为普通文本），这是允许的
    # 只验证嵌套的 when_tool 块被移除
    assert "组合使用" not in rendered  # 这是 when_tool get_file_sections 块中的内容


def test_nested_when_tool_all_registered(prompts_fixtures):
    """测试所有嵌套工具都注册时的解析"""
    template_path = prompts_fixtures / "system_prompt_complex.md"
    template = template_path.read_text(encoding="utf-8")
    
    # 场景2：注册所有工具
    tool_names = {"list_files", "get_file_sections", "search_files", "read_file"}
    rendered = parse_when_tool_blocks(template, tool_names)
    
    assert "文件列表工具" in rendered
    assert "组合使用" in rendered  # 嵌套块应该保留
    assert "get_file_sections" in rendered
    assert "文件搜索工具" in rendered
    assert "后续操作" in rendered  # 嵌套在 search_files 中的 read_file 块


def test_when_tag_nested_blocks(prompts_fixtures):
    """测试嵌套 when_tag 块的解析"""
    template_path = prompts_fixtures / "system_prompt_complex.md"
    template = template_path.read_text(encoding="utf-8")
    
    # 先移除 when_tool 块
    rendered = parse_when_tool_blocks(template, set())
    
    # 场景1：只有 doc 标签
    tag_names = {"doc"}
    rendered = parse_when_tag_blocks(rendered, tag_names)
    
    assert "文档处理模式" in rendered
    assert "分析增强" not in rendered  # 嵌套的 analysis 标签被移除
    
    # 场景2：doc 和 analysis 标签都有
    tag_names = {"doc", "analysis"}
    rendered = parse_when_tag_blocks(template, tag_names)
    
    assert "文档处理模式" in rendered
    assert "分析增强" in rendered  # 嵌套块保留


def test_when_tag_mutually_exclusive(prompts_fixtures):
    """测试互斥的 when_tag 块"""
    template_path = prompts_fixtures / "system_prompt_complex.md"
    template = template_path.read_text(encoding="utf-8")
    
    # 移除 when_tool 块
    rendered = parse_when_tool_blocks(template, set())
    
    # 只选择 doc 标签（不选 fin）
    tag_names = {"doc"}
    rendered = parse_when_tag_blocks(rendered, tag_names)
    
    assert "文档处理模式" in rendered
    assert "财务分析模式" not in rendered  # fin 标签块被移除


def test_template_variables_replacement(prompts_fixtures):
    """测试模板变量替换"""
    template_path = prompts_fixtures / "template_variables.md"
    template = template_path.read_text(encoding="utf-8")
    
    variables = {
        "project_name": "Test Project",
        "version": "2.0.0",
        "author": "Alice",
        "environment": "production",
        "user_name": "Bob",
        "user_role": "admin",
        "access_level": "full",
        "max_iterations": "15",
        "timeout": "3600",
        "debug_mode": "false",
        "timestamp": "2024-01-01T00:00:00Z",
        "last_modified": "2024-01-15",
    }
    
    rendered = replace_template_variables(template, variables)
    
    # 验证变量被替换
    assert "Test Project" in rendered
    assert "2.0.0" in rendered
    assert "Alice" in rendered
    assert "production" in rendered
    assert "Bob" in rendered
    assert "admin" in rendered
    
    # 验证未定义的变量保持原样
    assert "{{unset_variable}}" in rendered
    
    # 验证所有定义的变量都被替换
    for key in variables.keys():
        assert f"{{{{{key}}}}}" not in rendered


def test_load_prompt_full_workflow(prompts_fixtures):
    """测试 load_prompt 完整工作流（工具 + 标签 + 变量）"""
    template_path = prompts_fixtures / "system_prompt_complex.md"
    template = template_path.read_text(encoding="utf-8")
    
    tool_names = {"list_files", "read_file"}
    tag_names = {"doc", "verbose"}
    variables = {
        "environment": "test",
        "user_role": "developer",
        "max_iterations": "10",
    }
    
    rendered = load_prompt(
        template,
        variables=variables,
        tool_names=tool_names,
        tag_names=tag_names,
    )
    
    # 验证工具块
    assert "文件列表工具" in rendered
    assert "list_files" in rendered
    assert "文件读取工具" in rendered
    assert "文件搜索工具" not in rendered  # search_files 未注册
    
    # 验证标签块
    assert "文档处理模式" in rendered  # doc 标签
    assert "详细模式" in rendered  # verbose 标签
    assert "简洁模式" not in rendered  # concise 标签未启用
    
    # 验证变量替换
    assert "当前环境：test" in rendered
    assert "用户角色：developer" in rendered
    assert "最大迭代次数：10" in rendered


def test_multi_tool_guidance_rendering(prompts_fixtures):
    """测试多工具说明文档的条件渲染"""
    template_path = prompts_fixtures / "tool_guidance_multi_tool.md"
    template = template_path.read_text(encoding="utf-8")
    
    # 场景1：只有部分工具
    tool_names = {"list_files", "search_files"}
    tag_names = set()
    
    rendered = load_prompt(
        template,
        variables=None,
        tool_names=tool_names,
        tag_names=tag_names,
    )
    
    assert "1. list_files" in rendered
    assert "3. search_files" in rendered
    assert "2. get_file_sections" not in rendered  # 未注册
    assert "4. read_file" not in rendered  # 未注册
    
    # 验证嵌套块（search_files 中的 read_file）被移除
    assert "后续操作" not in rendered


def test_multi_tool_guidance_with_tags(prompts_fixtures):
    """测试工具说明 + 标签组合"""
    template_path = prompts_fixtures / "tool_guidance_multi_tool.md"
    template = template_path.read_text(encoding="utf-8")
    
    tool_names = {"list_files", "get_file_sections", "search_files", "read_file"}
    tag_names = {"doc"}
    
    rendered = load_prompt(
        template,
        variables=None,
        tool_names=tool_names,
        tag_names=tag_names,
    )
    
    # 验证所有工具块都存在
    assert "1. list_files" in rendered
    assert "2. get_file_sections" in rendered
    assert "3. search_files" in rendered
    assert "4. read_file" in rendered
    
    # 验证标签块
    assert "文档分析工作流" in rendered
    assert "标准流程" in rendered


def test_tool_guidance_with_variables(prompts_fixtures):
    """测试工具说明文档的变量替换"""
    template_path = prompts_fixtures / "tool_guidance_multi_tool.md"
    template = template_path.read_text(encoding="utf-8")
    
    variables = {
        "list_files_max": "200",
        "get_sections_max": "200",
        "search_max_results": "50",
        "read_file_max_chars": "200000",
    }
    
    rendered = load_prompt(
        template,
        variables=variables,
        tool_names={"list_files", "get_file_sections", "search_files", "read_file"},
        tag_names=set(),
    )
    
    # 验证变量替换
    assert "最多 200 个文件" in rendered
    assert "最多 200 个 section" in rendered
    assert "最多 50 个匹配" in rendered
    assert "最多 200000 字符" in rendered


def test_template_variables_with_conditions(prompts_fixtures):
    """测试条件块中的变量替换"""
    template_path = prompts_fixtures / "template_variables.md"
    template = template_path.read_text(encoding="utf-8")
    
    tool_names = {"list_files"}
    tag_names = {"analysis"}
    variables = {
        "project_name": "MyProject",
        "list_files_max": "100",
        "pattern_support": "true",
        "analysis_depth": "detailed",
        "include_metrics": "yes",
    }
    
    rendered = load_prompt(
        template,
        variables=variables,
        tool_names=tool_names,
        tag_names=tag_names,
    )
    
    # 验证条件块保留
    assert "Available Tools" in rendered
    assert "Analysis Mode" in rendered
    
    # 验证条件块中的变量被替换
    assert "Max files: 100" in rendered
    assert "Supports pattern matching: true" in rendered
    assert "Analysis depth: detailed" in rendered
    assert "Include metrics: yes" in rendered


def test_empty_tool_names(prompts_fixtures):
    """测试没有工具注册时，所有 when_tool 块被移除"""
    template_path = prompts_fixtures / "system_prompt_complex.md"
    template = template_path.read_text(encoding="utf-8")
    
    rendered = load_prompt(
        template,
        variables=None,
        tool_names=set(),
        tag_names=set(),
    )
    
    # 所有工具相关内容应该被移除
    assert "文件列表工具" not in rendered
    assert "文件搜索工具" not in rendered
    assert "文件读取工具" not in rendered
    assert "get_file_sections" not in rendered
    
    # 基础内容保留
    assert "你是一个智能助手" in rendered
    assert "基础能力" in rendered


def test_empty_tag_names(prompts_fixtures):
    """测试没有标签时，所有 when_tag 块被移除"""
    template_path = prompts_fixtures / "system_prompt_complex.md"
    template = template_path.read_text(encoding="utf-8")
    
    # 先移除工具块
    rendered = load_prompt(
        template,
        variables=None,
        tool_names=set(),
        tag_names=set(),
    )
    
    # 所有标签相关内容应该被移除
    assert "文档处理模式" not in rendered
    assert "财务分析模式" not in rendered
    assert "详细模式" not in rendered
    assert "简洁模式" not in rendered
