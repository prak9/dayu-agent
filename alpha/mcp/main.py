"""官方 MCP SDK stdio 入口，stdout 仅承载协议消息。"""

import argparse
import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp.server import MCPServer

from alpha.integrations.notion.client import NotionClient
from alpha.mcp.tools import AlphaMcpTools, register_mcp_tools
from alpha.startup.external_research import prepare_external_research
from alpha.services.publication_preparation import PublicationConnection, load_notion_parent_id, prepare_publication_service
from alpha.services.publication_worker import PublicationWorker
from alpha.services.research_preparation import prepare_research_service
from alpha.services.startup_preparation import prepare_host_runtime_dependencies
from alpha.startup.codex_credentials import load_notion_token

_PUBLISH_POLL_SECONDS = 1.0
_PUBLISH_ERROR_DELAY_SECONDS = 5.0


async def _publish_loop(worker: PublicationWorker) -> None:
    """处理明确授权的发布队列。参数：工作者。返回：无。异常：取消向上传播。"""
    while True:
        try:
            result = await worker.process_once()
            if result is None:
                await asyncio.sleep(_PUBLISH_POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.getLogger(__name__).error("Notion 发布队列暂未完成：%s", type(exc).__name__)
            await asyncio.sleep(_PUBLISH_ERROR_DELAY_SECONDS)


@dataclass(frozen=True)
class _McpLifetime:
    """stdio 连接拥有外部研究和发布工作者；断开时协作收尾。"""

    handlers: AlphaMcpTools
    client: NotionClient | None

    @asynccontextmanager
    async def __call__(self, server: MCPServer[None]) -> AsyncIterator[None]:
        """维护连接资源。参数：服务器。返回：空 lifespan。异常：取消或资源收尾错误。"""
        publication = self.handlers.publication
        publisher = asyncio.create_task(_publish_loop(PublicationWorker(publication))) if publication is not None else None
        try:
            yield None
        finally:
            if publisher is not None:
                publisher.cancel()
            try:
                await self.handlers.external.close()
            finally:
                if publisher is not None:
                    await asyncio.gather(publisher, return_exceptions=True)
                if self.client is not None:
                    self.client.close()


def build_server(workspace: Path, config_root: Path | None, owner_id: str) -> MCPServer[None]:
    """装配本地服务器。参数：工作区、配置覆盖、本地用户。返回：官方 SDK 服务器。异常：配置或数据库未初始化。"""
    dependencies = prepare_host_runtime_dependencies(workspace_root=workspace, config_root=config_root, execution_options=None,
                                                     runtime_label="alpha-mcp", log_module="APP.MCP")
    research = prepare_research_service(workspace, dependencies)
    token = load_notion_token()
    client = NotionClient(token) if token else None
    publication = (prepare_publication_service(workspace, dependencies, PublicationConnection(client, load_notion_parent_id(workspace, config_root)))
                   if client is not None else None)
    research.publisher = publication
    handlers = AlphaMcpTools(research, prepare_external_research(workspace, research), owner_id, publication)
    server = MCPServer[None]("alpha", instructions="使用当前 coding agent 完成研究；alpha 提供财报、检查点、候选稿与 Notion 归档。先查看 sessions，开始后按工具目录调用。",
                             lifespan=_McpLifetime(handlers, client), log_level="WARNING")
    register_mcp_tools(server, handlers)
    return server


def main() -> None:
    """运行 alpha-mcp。参数：来自命令行的工作区、配置与用户。返回：无。异常：启动失败或协议错误。"""
    parser = argparse.ArgumentParser(description="alpha 研究 MCP stdio 服务")
    parser.add_argument("--base", default="./workspace")
    parser.add_argument("--config", default=None)
    parser.add_argument("--owner", default="local")
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, force=True)
    config = Path(args.config).expanduser().resolve() if args.config else None
    build_server(Path(args.base).expanduser().resolve(), config, str(args.owner)).run(transport="stdio")


if __name__ == "__main__":
    main()
