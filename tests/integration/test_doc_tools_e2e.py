"""
doc_tools 端到端集成测试

使用真实测试数据，完整测试 doc_tools 的所有功能，包括：
1. list_files - 列出目录文件
2. get_file_sections - 提取文件章节结构
3. search_files - 搜索文件内容
4. read_file - 读取文件内容

测试策略：
- 使用 tests/fixtures/doc_tools 中的真实测试数据
- 模拟 AsyncAgent + 自定义 Runner 的完整流程
- 验证工具在真实场景下的表现
"""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from alpha.engine.async_agent import AsyncAgent
from alpha.engine import ToolRegistry, register_doc_tools
from alpha.engine import (
    content_complete,
    content_delta,
    done_event,
    tool_call_dispatched,
    tool_call_result,
    tool_calls_batch_done,
    tool_calls_batch_ready,
)


class DocToolsTestRunner:
    """
    自定义 Runner，用于端到端测试 doc_tools
    
    模拟 LLM 发起工具调用的完整流程
    """
    
    def __init__(self, tool_executor, test_scenario):
        """
        Args:
            tool_executor: ToolRegistry 实例，用于执行工具
            test_scenario: 测试场景配置
                - tool_calls: [(tool_name, tool_args), ...]
                - final_message: 最终回复内容
        """
        self.tool_executor = tool_executor
        self.test_scenario = test_scenario
        self.calls = []
        self.iteration = 0
    
    def is_supports_tool_calling(self):
        return False
    
    def set_tools(self, *args, **kwargs):
        return None

    async def close(self) -> None:
        """关闭 Runner（桩实现，无操作）。"""
        return None
    
    async def call(self, messages, stream=True, **extra_payloads):
        """模拟 LLM 调用流程"""
        self.calls.append(messages)
        
        if self.iteration == 0:
            # 第一轮：执行工具调用
            tool_calls = self.test_scenario.get("tool_calls", [])
            tool_call_ids = []
            
            yield content_complete("")
            
            # 发起所有工具调用
            for idx, (tool_name, tool_args) in enumerate(tool_calls):
                tool_call_id = f"call_{idx + 1}"
                tool_call_ids.append(tool_call_id)
                
                yield tool_call_dispatched(
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    arguments=json.dumps(tool_args),
                    index_in_iteration=idx,
                )
            
            yield tool_calls_batch_ready(tool_call_ids)
            
            # 执行工具并返回结果
            for idx, (tool_name, tool_args) in enumerate(tool_calls):
                tool_call_id = f"call_{idx + 1}"
                
                result = self.tool_executor.execute(tool_name, tool_args)
                
                yield tool_call_result(
                    tool_call_id,
                    result,
                    name=tool_name,
                    arguments=json.dumps(tool_args),
                    index_in_iteration=idx,
                )
            
            yield tool_calls_batch_done(
                tool_call_ids,
                ok=len(tool_call_ids),
                error=0,
                timeout=0,
                cancelled=0,
            )
            yield done_event(summary={"tool_calls": len(tool_call_ids)})
        else:
            # 第二轮：返回最终答案
            final_message = self.test_scenario.get("final_message", "完成分析")
            yield content_delta(final_message)
            yield content_complete(final_message)
            yield done_event(summary={"tool_calls": 0})
        
        self.iteration += 1


def _extract_tool_result_data(result):
    """从工具执行结果中提取 value 值。"""
    return result["value"]


@pytest.mark.asyncio
async def test_list_files_with_real_data(doc_tools_fixtures):
    """
    端到端测试：list_files 列出测试数据目录中的文件
    """
    # 准备环境
    registry = ToolRegistry()
    registry.register_allowed_paths([doc_tools_fixtures])
    register_doc_tools(registry)

    # 定义测试场景
    test_scenario = {
        "tool_calls": [
            ("list_files", {
                "directory": str(doc_tools_fixtures),
                "pattern": "*.md",
                "recursive": False,
                "limit": 10,
            }),
        ],
        "final_message": "找到了测试数据文件",
    }
    
    # 创建 Runner 和 Agent
    runner = DocToolsTestRunner(registry, test_scenario)
    agent = AsyncAgent(
        runner=runner,
        tool_executor=registry,
    )
    
    # 执行任务
    result = await agent.run_and_wait("列出测试数据目录中的 markdown 文件", system_prompt="你是文档分析助手")
    
    # 验证结果
    assert result.success
    assert len(result.tool_calls) == 1
    
    # 获取工具调用记录
    tool_calls = result.tool_calls
    assert len(tool_calls) == 1
    
    list_files_call = tool_calls[0]
    assert list_files_call["name"] == "list_files"
    assert list_files_call["result"]["ok"] is True
    
    # 验证找到了测试文件
    data = _extract_tool_result_data(list_files_call["result"])
    files = data.get("files", [])
    assert len(files) > 0
    
    file_names = {f["name"] for f in files}
    assert "doc_tools_test.md" in file_names


@pytest.mark.asyncio
async def test_get_file_sections_with_real_data(doc_tools_fixtures):
    """
    端到端测试：get_file_sections 提取真实文档的章节结构
    """
    test_file = doc_tools_fixtures / "doc_tools_test.md"
    
    # 准备环境
    registry = ToolRegistry()
    registry.register_allowed_paths([doc_tools_fixtures])
    register_doc_tools(registry)

    # 定义测试场景
    test_scenario = {
        "tool_calls": [
            ("get_file_sections", {
                "file_path": str(test_file),
                "limit": 20,
            }),
        ],
        "final_message": "已分析文档章节结构",
    }
    
    # 创建 Runner 和 Agent
    runner = DocToolsTestRunner(registry, test_scenario)
    agent = AsyncAgent(
        runner=runner,
        tool_executor=registry,
    )
    
    # 执行任务
    result = await agent.run_and_wait("分析测试文档的章节结构", system_prompt="你是文档分析助手")
    
    # 验证结果
    assert result.success
    assert len(result.tool_calls) == 1
    
    # 获取工具调用记录
    tool_calls = result.tool_calls
    assert len(tool_calls) == 1
    
    sections_call = tool_calls[0]
    assert sections_call["name"] == "get_file_sections"
    assert sections_call["result"]["ok"] is True
    
    # 验证提取到章节
    data = _extract_tool_result_data(sections_call["result"])
    sections = data.get("sections", [])
    assert len(sections) > 0
    
    # 验证第一个 section 是标题
    first_section = sections[0]
    assert "title" in first_section
    assert "line_range" in first_section
    assert "line_count" in first_section
    
    # 验证找到了特定章节（基于真实数据）
    section_titles = [s["title"] for s in sections[:10]]
    assert "000333.SZ" in section_titles or "致股东" in section_titles


@pytest.mark.asyncio
async def test_search_files_with_real_data(doc_tools_fixtures):
    """
    端到端测试：search_files 搜索真实文档中的关键词
    """
    # 准备环境
    registry = ToolRegistry()
    registry.register_allowed_paths([doc_tools_fixtures])
    register_doc_tools(registry)

    # 定义测试场景：搜索"美的"关键词
    test_scenario = {
        "tool_calls": [
            ("search_files", {
                "directory": str(doc_tools_fixtures),
                "query": "美的",
                "include_types": ["md"],
                "limit": 10,
            }),
        ],
        "final_message": "找到了相关内容",
    }
    
    # 创建 Runner 和 Agent
    runner = DocToolsTestRunner(registry, test_scenario)
    agent = AsyncAgent(
        runner=runner,
        tool_executor=registry,
    )
    
    # 执行任务
    result = await agent.run_and_wait("搜索测试文档中包含'美的'的内容", system_prompt="你是文档分析助手")
    
    # 验证结果
    assert result.success
    assert len(result.tool_calls) == 1
    
    # 获取工具调用记录
    tool_calls = result.tool_calls
    assert len(tool_calls) == 1
    
    search_call = tool_calls[0]
    assert search_call["name"] == "search_files"
    assert search_call["result"]["ok"] is True
    
    # 验证找到匹配
    data = _extract_tool_result_data(search_call["result"])
    matches = data.get("matches", [])
    assert len(matches) > 0

    # 验证匹配字段（v2 schema）
    first_match = matches[0]
    assert "file" in first_match
    assert "snippet" in first_match
    # Markdown 文件走处理器路径：section_ref/section_title 有值，snippet 包含关键词
    assert first_match.get("section_ref") is not None or first_match.get("snippet")
    assert "美的" in first_match["snippet"]


@pytest.mark.asyncio
async def test_read_file_with_real_data(doc_tools_fixtures):
    """
    端到端测试：read_file 读取真实文档的指定行范围
    """
    test_file = doc_tools_fixtures / "doc_tools_test.md"
    
    # 准备环境
    registry = ToolRegistry()
    registry.register_allowed_paths([doc_tools_fixtures])
    register_doc_tools(registry)

    # 定义测试场景：读取前 50 行
    test_scenario = {
        "tool_calls": [
            ("read_file", {
                "file_path": str(test_file),
                "start_line": 1,
                "end_line": 50,
            }),
        ],
        "final_message": "已读取文档内容",
    }
    
    # 创建 Runner 和 Agent
    runner = DocToolsTestRunner(registry, test_scenario)
    agent = AsyncAgent(
        runner=runner,
        tool_executor=registry,
    )
    
    # 执行任务
    result = await agent.run_and_wait("读取测试文档的前 50 行", system_prompt="你是文档分析助手")
    
    # 验证结果
    assert result.success
    assert len(result.tool_calls) == 1
    
    # 获取工具调用记录
    tool_calls = result.tool_calls
    assert len(tool_calls) == 1
    
    read_call = tool_calls[0]
    assert read_call["name"] == "read_file"
    assert read_call["result"]["ok"] is True
    
    # 验证读取到内容
    data = _extract_tool_result_data(read_call["result"])
    content = data.get("content", "")
    assert len(content) > 0
    
    # 验证行范围
    assert data.get("line_range") == [1, 50]
    assert data.get("total_lines", 0) > 50


@pytest.mark.asyncio
async def test_multi_tool_workflow_with_real_data(doc_tools_fixtures):
    """
    端到端测试：多工具协作工作流
    
    场景：
    1. list_files - 列出目录中的文件
    2. get_file_sections - 获取文件章节结构
    3. read_file - 读取特定章节内容
    """
    test_file = doc_tools_fixtures / "doc_tools_test.md"
    
    # 准备环境
    registry = ToolRegistry()
    registry.register_allowed_paths([doc_tools_fixtures])
    register_doc_tools(registry)

    # 定义测试场景：多工具调用
    test_scenario = {
        "tool_calls": [
            ("list_files", {
                "directory": str(doc_tools_fixtures),
                "pattern": "*.md",
                "recursive": False,
                "limit": 5,
            }),
            ("get_file_sections", {
                "file_path": str(test_file),
                "limit": 10,
            }),
            ("read_file", {
                "file_path": str(test_file),
                "start_line": 1,
                "end_line": 30,
            }),
        ],
        "final_message": "完成文档分析工作流",
    }
    
    # 创建 Runner 和 Agent
    runner = DocToolsTestRunner(registry, test_scenario)
    agent = AsyncAgent(
        runner=runner,
        tool_executor=registry,
    )
    
    # 执行任务
    result = await agent.run_and_wait("分析测试文档：列出文件、提取章节、读取内容", system_prompt="你是文档分析助手")
    
    # 验证结果
    assert result.success
    assert len(result.tool_calls) == 3
    
    # 获取工具调用记录
    tool_calls = result.tool_calls
    assert len(tool_calls) == 3
    
    # 验证每个工具调用都成功
    for call in tool_calls:
        assert call["result"]["ok"] is True
    
    # 验证工具调用顺序
    assert tool_calls[0]["name"] == "list_files"
    assert tool_calls[1]["name"] == "get_file_sections"
    assert tool_calls[2]["name"] == "read_file"
    
    # 验证 list_files 结果
    list_data = _extract_tool_result_data(tool_calls[0]["result"])
    assert len(list_data.get("files", [])) > 0
    
    # 验证 get_file_sections 结果
    sections_data = _extract_tool_result_data(tool_calls[1]["result"])
    assert len(sections_data.get("sections", [])) > 0
    
    # 验证 read_file 结果
    read_data = _extract_tool_result_data(tool_calls[2]["result"])
    assert len(read_data.get("content", "")) > 0


@pytest.mark.asyncio
async def test_doc_tools_with_limit_enforcement(doc_tools_fixtures):
    """
    端到端测试：验证 limit 参数的硬性限制
    
    场景：LLM 请求超过配置上限的数据量，系统应该自动限制
    """
    test_file = doc_tools_fixtures / "doc_tools_test.md"
    
    # 准备环境（使用默认限制）
    registry = ToolRegistry()
    registry.register_allowed_paths([doc_tools_fixtures])
    register_doc_tools(registry)
    
    # 定义测试场景：请求超大 limit
    test_scenario = {
        "tool_calls": [
            ("get_file_sections", {
                "file_path": str(test_file),
                "limit": 999,  # 远超默认上限 200
            }),
        ],
        "final_message": "已限制返回数量",
    }
    
    # 创建 Runner 和 Agent
    runner = DocToolsTestRunner(registry, test_scenario)
    agent = AsyncAgent(
        runner=runner,
        tool_executor=registry,
    )
    
    # 执行任务
    result = await agent.run_and_wait("获取文档的所有章节", system_prompt="你是文档分析助手")
    
    # 验证结果
    assert result.success
    
    # 获取工具调用记录
    tool_calls = result.tool_calls
    assert len(tool_calls) == 1
    
    sections_call = tool_calls[0]
    assert sections_call["result"]["ok"] is True
    
    # 验证返回数量被限制
    data = _extract_tool_result_data(sections_call["result"])
    returned_sections = data.get("returned_sections", 0)
    
    # 应该被限制在配置的上限（默认 200）以内
    assert returned_sections <= 200
    assert returned_sections < 999  # 证明确实进行了限制
