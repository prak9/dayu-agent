"""alpha research 交互入口，仅调用 Service 公共能力。"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import cast

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.execution_options import ExecutionOptions
from alpha.contracts.research import CreateResearchRequest, ResearchDepth, ResearchPublicationPolicy, ResumeResearchTurnRequest, SubmitResearchTurnRequest
from alpha.contracts.research_financials import decode_financial_requirements
from alpha.contracts.events import AppEventType
from alpha.contracts.env_keys import ALPHA_NOTION_TOKEN_ENV
from alpha.startup.codex_credentials import load_notion_token
from alpha.contracts.publication import PublishResearchRequest, ResearchPublication
from alpha.integrations.notion.client import NotionClient
from alpha.services.publication_preparation import PublicationConnection, load_notion_parent_id, prepare_publication_service
from alpha.services.publication_worker import PublicationWorker
from alpha.services.publication_service import PublicationService
from alpha.contracts.publication import PublicationState
from alpha.services.startup_preparation import PreparedHostRuntimeDependencies
from alpha.services.research_preparation import prepare_research_service
from alpha.services.research_service import ResearchService
from alpha.services.research_material_service import prepare_research_materials
from alpha.contracts.research_materials import MAX_MATERIAL_BYTES
from alpha.services.startup_preparation import prepare_host_runtime_dependencies

_MAX_PUBLICATION_STEPS = 100

def _print_json(value: JsonValue) -> None:
    """打印结构化结果。参数：JSON 值。返回：无。异常：输出错误。"""
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


async def _run(service: ResearchService, research_id: str, owner_id: str) -> None:
    """消费当前研究输入。参数：服务、研究、用户。返回：无。异常：执行或提交失败。"""
    async for event in service.run_next(research_id, owner_id):
        if event.type in (AppEventType.FINAL_ANSWER, AppEventType.ERROR, AppEventType.WARNING, AppEventType.CANCELLED):
            _print_json(cast(JsonValue, event.payload))
    overview = service.overview(research_id, owner_id)
    _print_json({"research_id": research_id, "revisions": [revision.revision_id for revision in overview.revisions]})


def run_research_command(args: argparse.Namespace) -> int:
    """执行研究命令。参数：已解析参数。返回：退出码。异常：业务或配置错误向调用者传播。"""
    workspace = Path(str(args.base)).expanduser().resolve()
    config = Path(str(args.config)).expanduser().resolve() if args.config else None
    options = ExecutionOptions(model_name=str(args.model_name)) if args.model_name else None
    dependencies = prepare_host_runtime_dependencies(workspace_root=workspace, config_root=config, execution_options=None,
                                                     runtime_label="research-cli", log_module="APP.RESEARCH")
    service = prepare_research_service(workspace, dependencies)
    action = str(args.research_action)
    owner = str(args.owner)
    if action == "new":
        record = service.create(CreateResearchRequest(owner, str(args.key), str(args.question), tuple(args.subjects), str(args.title),
                                                      datetime.fromisoformat(str(args.as_of)) if args.as_of else None, ResearchDepth(args.depth)))
        _print_json(cast(JsonValue, asdict(record)))
    elif action == "list":
        _print_json(cast(JsonValue, [asdict(record) for record in service.list_research(owner)]))
    elif action == "status":
        _print_json(cast(JsonValue, asdict(service.overview(str(args.research_id), owner))))
    elif action == "ask":
        _ask_command(args, service, workspace, config, dependencies, options)
    elif action == "run":
        asyncio.run(_run(service, str(args.research_id), owner))
        _publish_completed_turn(service, str(args.research_id), owner, workspace, config, dependencies)
    elif action == "resume":
        turn = service.resume(ResumeResearchTurnRequest(str(args.turn_id), owner, str(args.key)))
        _print_json({"turn_id": turn.turn_id, "run_id": turn.run_id})
        if args.run:
            asyncio.run(_run(service, turn.research_id, owner))
            _publish_completed_turn(service, turn.research_id, owner, workspace, config, dependencies)
    elif action == "stop":
        _print_json(cast(JsonValue, asdict(service.stop(str(args.research_id), owner, str(args.key)))))
    elif action in ("archive", "open"):
        operation = service.archive if action == "archive" else service.reopen
        _print_json(cast(JsonValue, asdict(operation(str(args.research_id), owner))))
    elif action == "report":
        print(service.read_report(str(args.revision_id), owner))
    elif action == "material":
        with Path(str(args.file)).expanduser().open("rb") as source:
            content = source.read(MAX_MATERIAL_BYTES + 1)
        turn = prepare_research_materials(workspace, service).accept(str(args.research_id), owner, str(args.key),
            Path(str(args.file)).name, content, str(args.caption))
        _print_json({"turn_id": turn.turn_id, "attachment_refs": list(turn.attachment_refs)})
        if args.run:
            asyncio.run(_run(service, turn.research_id, owner))
    elif action in ("publish", "publication"):
        _publication_command(args, workspace, config, dependencies)
    else:
        raise ValueError(f"未知研究操作：{action}")
    return 0


def _prepare_publication(workspace: Path, config: Path | None, dependencies: PreparedHostRuntimeDependencies) -> tuple[NotionClient, PublicationService]:
    """准备显式请求的归档连接。参数：工作区、配置、宿主。返回：客户端和发布服务。异常：缺少凭据或目标配置。"""
    token = load_notion_token()
    if not token:
        raise ValueError(f"未找到 Codex Notion 凭据；请配置 mcp_servers.notion.env.NOTION_TOKEN，或显式覆盖 {ALPHA_NOTION_TOKEN_ENV}")
    client = NotionClient(token)
    try:
        return client, prepare_publication_service(workspace, dependencies, PublicationConnection(client, load_notion_parent_id(workspace, config)))
    except BaseException:
        client.close()
        raise


def _ask_command(args: argparse.Namespace, service: ResearchService, workspace: Path, config: Path | None,
                 dependencies: PreparedHostRuntimeDependencies, options: ExecutionOptions | None) -> None:
    """接受本轮要求和发布策略。参数：命令、服务、工作区、配置、宿主、选项。返回：无。异常：请求或执行失败。"""
    requirements = decode_financial_requirements(cast(JsonValue, json.loads(Path(str(args.financial_requirements)).read_text()))) if args.financial_requirements else ()
    client: NotionClient | None = None
    publication: PublicationService | None = None
    if args.publish_on_complete:
        client, publication = _prepare_publication(workspace, config, dependencies)
        service.publisher = publication
    try:
        turn = service.submit(SubmitResearchTurnRequest(str(args.research_id), str(args.owner), str(args.key), str(args.text), execution_options=options,
            financial_requirements=requirements, publication_policy=ResearchPublicationPolicy.ON_COMPLETE if args.publish_on_complete else ResearchPublicationPolicy.MANUAL))
        _print_json({"turn_id": turn.turn_id, "state": turn.state.value})
        if args.run:
            asyncio.run(_run(service, turn.research_id, str(args.owner)))
            if publication is not None:
                _print_json(cast(JsonValue, [asdict(item) for item in asyncio.run(_drain_publications(publication))]))
    finally:
        if client is not None:
            client.close()


async def _drain_publications(publication: PublicationService) -> list[ResearchPublication]:
    """处理当前到期意图，有界停止并保留未知结果。参数：发布服务。返回：本次处理记录。异常：取消或持久化失败。"""
    results: list[ResearchPublication] = []
    worker = PublicationWorker(publication)
    for _ in range(_MAX_PUBLICATION_STEPS):
        result = await worker.process_once()
        if result is None:
            break
        results.append(result)
        if result.state == PublicationState.FAILED_TERMINAL:
            break
    return results


def _publish_completed_turn(service: ResearchService, research_id: str, owner_id: str, workspace: Path, config: Path | None,
                            dependencies: PreparedHostRuntimeDependencies) -> None:
    """继续消费持久的本轮完成后发布策略。参数：研究服务、研究、用户、工作区、配置、宿主。返回：无。异常：连接或发布错误。"""
    turn = service.overview(research_id, owner_id).execution_turn
    if turn is None or turn.publication_policy != ResearchPublicationPolicy.ON_COMPLETE:
        return
    client, publication = _prepare_publication(workspace, config, dependencies)
    try:
        _print_json(cast(JsonValue, [asdict(item) for item in asyncio.run(_drain_publications(publication))]))
    finally:
        client.close()


def _publication_command(args: argparse.Namespace, workspace: Path, config: Path | None, dependencies: PreparedHostRuntimeDependencies) -> None:
    """接受或查询发布。参数：参数、工作区、配置、共享宿主。返回：无。异常：缺密钥、越权或发布错误。"""
    client, publication = _prepare_publication(workspace, config, dependencies)
    try:
        if str(args.research_action) == "publish":
            result = publication.request_publish(PublishResearchRequest(str(args.revision_id), str(args.owner), str(args.key)))
            if args.run:
                asyncio.run(PublicationWorker(publication).process_once())
            result = publication.get(result.publication_id, str(args.owner))
        else:
            result = publication.get(str(args.publication_id), str(args.owner))
        _print_json(cast(JsonValue, asdict(result)))
    finally:
        client.close()
