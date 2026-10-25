"""研究 CLI 指定版本发布、状态查询及凭据缺失测试。"""

import json
from pathlib import Path
from collections.abc import AsyncGenerator

import httpx
import pytest
from pytest_mock import MockerFixture

from alpha.cli.arg_parsing import _create_parser
from alpha.cli.commands.research import run_research_command
from alpha.contracts.env_keys import ALPHA_NOTION_TOKEN_ENV
from alpha.integrations.notion.client import NotionClient
from alpha.services.publication_preparation import load_notion_parent_id
from alpha.workspace_paths import build_research_store_path
from alpha.contracts.events import AppEvent, AppEventType
from tests.telegram.test_journey import _model
from tests.integrations.notion.fakes import NotionServer
from tests.integrations.notion.test_client import PARENT_ID
from tests.research.test_publications import _ready


def test_cli_publish_runs_authorized_queue_and_reads_same_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI 发布和本地状态查询复用相同意图。参数：目录、环境、mock、输出。返回：无。异常：断言失败。"""
    _, _, revision = _ready(build_research_store_path(tmp_path).parent)
    server = NotionServer()
    client = NotionClient("secret", transport=httpx.MockTransport(server))
    factory = mocker.patch("alpha.cli.commands.research.NotionClient", return_value=client)
    monkeypatch.setenv(ALPHA_NOTION_TOKEN_ENV, "secret")
    prefix = ["research", "--base", str(tmp_path), "--owner", "owner"]
    args = _create_parser().parse_args(prefix + ["publish", revision.revision_id, "--key", "publish", "--run"])
    assert run_research_command(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "published" and server.created == 2
    second = NotionClient("secret", transport=httpx.MockTransport(server))
    factory.return_value = second
    assert run_research_command(_create_parser().parse_args(prefix + ["publication", result["publication_id"]])) == 0
    assert json.loads(capsys.readouterr().out)["page_url"] == result["page_url"]
    assert server.created == 2
    monkeypatch.delenv(ALPHA_NOTION_TOKEN_ENV)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex"))
    with pytest.raises(ValueError, match="ALPHA_NOTION_TOKEN"):
        run_research_command(args)


def test_notion_parent_configuration_is_fixed_and_validated(tmp_path: Path) -> None:
    """默认目标是已确认 Invest，不按同名搜索；配置非法直接拒绝。参数：目录。返回：无。异常：断言失败。"""
    assert load_notion_parent_id(tmp_path, None) == PARENT_ID
    config = tmp_path / "custom"
    config.mkdir()
    (config / "notion.json").write_text('{"parent_page_id":"invalid"}')
    with pytest.raises(ValueError):
        load_notion_parent_id(tmp_path, config)


def test_cli_explicit_completion_policy_queues_and_publishes_fixed_revision(tmp_path: Path, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """只有显式完成后发布选项才建立自动归档意图。参数：目录、mock、输出。返回：无。异常：断言失败。"""
    prefix = ["research", "--base", str(tmp_path), "--owner", "owner"]
    assert run_research_command(_create_parser().parse_args(prefix + ["new", "研究框架", "--key", "create"])) == 0
    record = json.loads(capsys.readouterr().out)
    server = NotionServer()
    client = NotionClient("test", transport=httpx.MockTransport(server))
    mocker.patch("alpha.cli.commands.research.load_notion_token", return_value="test")
    mocker.patch("alpha.cli.commands.research.NotionClient", return_value=client)
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", new=_model)
    args = _create_parser().parse_args(prefix + ["ask", record["research_id"], "研究并归档", "--key", "turn", "--run", "--publish-on-complete"])
    assert run_research_command(args) == 0
    output = capsys.readouterr().out
    assert '"published"' in output and server.created == 2


def test_queued_completion_policy_survives_separate_cli_invocation(tmp_path: Path, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """只入队后重新装配执行，也按原策略归档。参数：目录、mock、输出。返回：无。异常：断言失败。"""
    prefix = ["research", "--base", str(tmp_path), "--owner", "owner"]
    assert run_research_command(_create_parser().parse_args(prefix + ["new", "研究框架", "--key", "create"])) == 0
    record = json.loads(capsys.readouterr().out)
    server = NotionServer()
    clients = [NotionClient("test", transport=httpx.MockTransport(server)) for _ in range(2)]
    mocker.patch("alpha.cli.commands.research.load_notion_token", return_value="test")
    mocker.patch("alpha.cli.commands.research.NotionClient", side_effect=clients)
    args = _create_parser().parse_args(prefix + ["ask", record["research_id"], "稍后执行并归档", "--key", "turn", "--publish-on-complete"])
    assert run_research_command(args) == 0 and server.created == 0
    capsys.readouterr()
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", new=_model)
    assert run_research_command(_create_parser().parse_args(prefix + ["run", record["research_id"]])) == 0
    assert '"published"' in capsys.readouterr().out and server.created == 2


def test_cli_runs_persistent_research_material_recovery_and_revision_workflow(tmp_path: Path, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI 使用真实服务执行研究和显式恢复，仅替换模型。参数：目录、mock、输出。返回：无。异常：断言失败。"""
    prefix = ["research", "--base", str(tmp_path), "--owner", "owner"]

    def execute(arguments: list[str]) -> str:
        """执行真实解析入口。参数：动作参数。返回：终端输出。异常：业务错误。"""
        assert run_research_command(_create_parser().parse_args(prefix + arguments)) == 0
        return capsys.readouterr().out

    record = json.loads(execute(["new", "收入质量", "--key", "create"]))
    identifier = record["research_id"]
    assert json.loads(execute(["new", "收入质量", "--key", "create"]))["research_id"] == identifier
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", new=_model)
    assert "revisions" in execute(["ask", identifier, "开始研究", "--key", "first", "--run"])
    status = json.loads(execute(["status", identifier]))
    assert len(status["revisions"]) == 1
    assert "研究报告" in execute(["report", status["revisions"][0]["revision_id"]])
    material = tmp_path / "note.md"
    material.write_text("收入变化待核对")
    assert "attachment_refs" in execute(["material", identifier, str(material), "--key", "file", "--run"])
    assert "revisions" in execute(["run", identifier])

    async def failure(*args: str, **kwargs: str) -> AsyncGenerator[AppEvent, None]:
        """模拟模型运行错误。参数：测试替换参数。返回：不可达事件。异常：明确错误。"""
        raise RuntimeError("模拟 CLI 模型故障")
        yield AppEvent(AppEventType.ERROR, {})

    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", new=failure)
    with pytest.raises(RuntimeError, match="模型故障"):
        execute(["ask", identifier, "故障输入", "--key", "failing", "--run"])
    capsys.readouterr()
    failed = json.loads(execute(["status", identifier]))
    mocker.patch("alpha.host.executor.DefaultHostExecutor._run_prepared_agent_stream", new=_model)
    assert "revisions" in execute(["resume", failed["execution_turn"]["turn_id"], "--key", "retry", "--run"])
    execute(["stop", identifier, "--key", "stop"])
    assert json.loads(execute(["archive", identifier]))["state"] == "archived"
    assert json.loads(execute(["open", identifier]))["state"] == "active"
    assert len(json.loads(execute(["list"]))) == 1
