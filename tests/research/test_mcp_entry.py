"""官方 MCP SDK 的工具发现、调用和连接退出验收。"""

import json
import asyncio
import os
import sys
from pathlib import Path
from typing import cast

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.types import CallToolResult, TextContent
import httpx
from pytest_mock import MockerFixture

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.run import RunState
from alpha.host.host import Host
from alpha.mcp.main import build_server, main
from alpha.integrations.notion.client import NotionClient
from tests.integrations.notion.fakes import NotionServer
from alpha.workspace_paths import build_host_store_default_path


def _decode(result: CallToolResult) -> dict[str, JsonValue]:
    """读取 SDK 返回的业务对象。参数：调用结果。返回：JSON 对象。异常：协议或业务失败。"""
    assert not result.is_error, result
    content = result.content[0]
    assert isinstance(content, TextContent)
    value = cast(JsonValue, json.loads(content.text))
    assert isinstance(value, dict)
    return value


@pytest.mark.asyncio
async def test_real_stdio_discovers_tools_commits_and_cleans_disconnect(tmp_path: Path) -> None:
    """从子进程公开入口验证 stdout 协议、正式报告与断线取消。参数：目录。返回：无。异常：断言失败。"""
    # 测试工作区没有发布意图，使用哑凭据避免读取或使用个人 Notion token。
    environment = {key: value for key, value in os.environ.items() if key.lower() != "no_proxy"}
    environment["ALPHA_NOTION_TOKEN"] = "test-notion-disabled"
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "alpha.mcp.main", "--base", str(tmp_path)], env=environment)
    async with Client(parameters, raise_exceptions=True) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert {"alpha_begin", "alpha_finish", "alpha_publish", "alpha_resume"} <= names
        research = _decode(await client.call_tool("alpha_create", {"question": "方法研究", "request_key": "create"}))
        opened = _decode(await client.call_tool("alpha_begin", {"research_id": research["research_id"], "text": "开始", "request_key": "begin"}))
        handle = opened["handle"]
        drafted = _decode(await client.call_tool("alpha_call", {"handle": handle, "tool_name": "research_draft_report", "arguments_json": '{"report_markdown":"# 直接研究成果"}', "call_id": "draft"}))
        body = drafted["value"]
        assert isinstance(body, dict)
        revision = _decode(await client.call_tool("alpha_finish", {"handle": handle, "candidate_id": body["candidate_id"], "content_hash": body["content_hash"], "call_id": "finish"}))
        assert revision["number"] == 1 and revision["source_run_id"] == opened["run_id"]
        later = _decode(await client.call_tool("alpha_begin", {"research_id": research["research_id"], "text": "待继续", "request_key": "next"}))
        run_id = str(later["run_id"])
    host = Host(host_store_path=build_host_store_default_path(tmp_path))
    run = host.get_run(run_id)
    assert run is not None and run.state == RunState.CANCELLED
    assert not host.list_active_runs()


@pytest.mark.asyncio
async def test_sdk_tools_publish_only_explicitly_enabled_revision(tmp_path: Path, mocker: MockerFixture) -> None:
    """官方 SDK 内存传输验证真实生命周期、显式发布策略和归档队列。参数：目录、mock。返回：无。异常：断言失败。"""
    server = NotionServer()
    notion = NotionClient("test", transport=httpx.MockTransport(server))
    mocker.patch("alpha.mcp.main.load_notion_token", return_value="test")
    mocker.patch("alpha.mcp.main.NotionClient", return_value=notion)
    app = build_server(tmp_path, None, "local")
    async with Client(app, raise_exceptions=False) as client:
        await client.call_tool("alpha_sessions", {})
        record = _decode(await client.call_tool("alpha_create", {"question": "方法研究", "request_key": "create"}))
        opened = _decode(await client.call_tool("alpha_begin", {"research_id": record["research_id"], "text": "开始并归档", "request_key": "begin", "publish_on_complete": True}))
        handle = opened["handle"]
        invalid = await client.call_tool("alpha_call", {"handle": handle, "tool_name": "research_checkpoints", "arguments_json": "[]", "call_id": "invalid"})
        assert invalid.is_error
        draft = _decode(await client.call_tool("alpha_call", {"handle": handle, "tool_name": "research_draft_report", "arguments_json": '{"report_markdown":"# 正式报告"}', "call_id": "draft"}))["value"]
        assert isinstance(draft, dict)
        revision = _decode(await client.call_tool("alpha_finish", {"handle": handle, "candidate_id": draft["candidate_id"], "content_hash": draft["content_hash"], "call_id": "finish"}))
        for _ in range(100):
            publications = await client.call_tool("alpha_publications", {})
            text = publications.content[0]
            assert isinstance(text, TextContent)
            if '"published"' in text.text:
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("显式授权的完成后发布没有被工作者消费")
        assert server.created == 2
        repeated = _decode(await client.call_tool("alpha_publish", {"revision_id": revision["revision_id"], "request_key": "manual-repeat"}))
        assert repeated["state"] == "published"
        assert (await client.call_tool("alpha_resume", {"turn_id": "missing", "request_key": "resume"})).is_error
        later = _decode(await client.call_tool("alpha_begin", {"research_id": record["research_id"], "text": "下一轮", "request_key": "next"}))
        assert _decode(await client.call_tool("alpha_abort", {"handle": later["handle"]}))["stopped"] is True


@pytest.mark.asyncio
async def test_sdk_without_notion_reports_missing_connection(tmp_path: Path, mocker: MockerFixture) -> None:
    """未配置归档不影响研究发现，明确发布会报缺失。参数：目录、mock。返回：无。异常：断言失败。"""
    mocker.patch("alpha.mcp.main.load_notion_token", return_value=None)
    async with Client(build_server(tmp_path, None, "local")) as client:
        result = await client.call_tool("alpha_publish", {"revision_id": "missing", "request_key": "publish"})
        assert result.is_error
        assert not (await client.call_tool("alpha_publications", {})).is_error


def test_console_main_uses_stdio_and_explicit_workspace(tmp_path: Path, mocker: MockerFixture) -> None:
    """命令参数只配置服务器，不改变协议传输。参数：目录、mock。返回：无。异常：断言失败。"""
    mocked = mocker.patch("alpha.mcp.main.build_server")
    mocker.patch.object(sys, "argv", ["alpha-mcp", "--base", str(tmp_path), "--owner", "owner"])
    main()
    mocked.assert_called_once_with(tmp_path, None, "owner")
    mocked.return_value.run.assert_called_once_with(transport="stdio")
