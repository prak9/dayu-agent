"""发布目标配置与默认仓储装配；凭据和 HTTP 连接由入口持有。"""

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from alpha.contracts.agent_types import JsonValue
from alpha.integrations.notion.contracts import NotionGateway
from alpha.integrations.notion.decoding import page_id, require_map, require_text
from alpha.research.storage.artifacts import FsResearchArtifactStore
from alpha.research.storage.catalog import SQLiteResearchCatalog
from alpha.research.storage.publications import SQLiteResearchPublications
from alpha.research.storage.revisions import SQLiteResearchRevisions
from alpha.research.storage.store import ResearchStore
from alpha.research.storage.notion_topics import SQLiteResearchTopics
from alpha.services.notion_topic_service import NotionTopicService
from alpha.services.publication_service import PublicationService
from alpha.services.startup_preparation import PreparedHostRuntimeDependencies
from alpha.startup.config_file_resolver import ConfigFileResolver
from alpha.workspace_paths import build_research_artifacts_dir, build_research_store_path

_CONFIG_NAME = "notion.json"


@dataclass(frozen=True)
class PublicationConnection:
    """已装配外部能力和固定父页，不把 token 放入业务请求或模型。"""

    gateway: NotionGateway
    parent_page_id: str


def load_notion_parent_id(workspace_root: Path, config_root: Path | None) -> str:
    """读取固定 Invest 父页。参数：工作区、配置覆盖。返回：规范 UUID。异常：配置缺失或非法。"""
    raw = ConfigFileResolver(config_root or workspace_root / "config").read_json(_CONFIG_NAME)
    return page_id(require_text(require_map(cast(JsonValue, raw)).get("parent_page_id")))


def prepare_publication_service(workspace_root: Path, dependencies: PreparedHostRuntimeDependencies, connection: PublicationConnection | None) -> PublicationService:
    """装配发布服务；无连接时只接受本地意图。参数：工作区、共享 Host、可选连接。返回：服务。异常：目标或存储非法。"""
    store = ResearchStore(build_research_store_path(workspace_root))
    gateway = connection.gateway if connection is not None else None
    target = page_id(connection.parent_page_id) if connection is not None else load_notion_parent_id(workspace_root, dependencies.workspace.config_root)
    return PublicationService(dependencies.host, SQLiteResearchPublications(store), SQLiteResearchCatalog(store),
                              SQLiteResearchRevisions(store, FsResearchArtifactStore(build_research_artifacts_dir(workspace_root))),
                              gateway, target, NotionTopicService(SQLiteResearchTopics(store), gateway))
