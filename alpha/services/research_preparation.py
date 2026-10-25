"""研究服务的默认装配入口，UI 不接触数据库和文件布局。"""

from pathlib import Path

from alpha.research.storage.artifacts import FsResearchArtifactStore
from alpha.research.storage.catalog import SQLiteResearchCatalog
from alpha.research.storage.methods import FsResearchMethodStore
from alpha.research.storage.revisions import SQLiteResearchRevisions
from alpha.research.storage.store import ResearchStore
from alpha.research.storage.turns import SQLiteResearchTurns
from alpha.research.storage.working import SQLiteResearchWorkingRecords
from alpha.research.storage.bindings import SQLiteResearchBindings
from alpha.services.research_channel_service import ResearchChannelService
from alpha.services.research_service import ResearchService
from alpha.services.publication_preparation import prepare_publication_service
from alpha.services.startup_preparation import PreparedHostRuntimeDependencies
from alpha.workspace_paths import build_research_artifacts_dir, build_research_methods_dir, build_research_store_path


def prepare_research_service(workspace_root: Path, dependencies: PreparedHostRuntimeDependencies) -> ResearchService:
    """装配研究服务。参数：工作区、共享宿主依赖。返回：服务。异常：存储初始化失败。"""
    store = ResearchStore(build_research_store_path(workspace_root))
    return ResearchService(dependencies.host, dependencies.scene_execution_acceptance_preparer,
                           SQLiteResearchCatalog(store), SQLiteResearchTurns(store),
                           SQLiteResearchRevisions(store, FsResearchArtifactStore(build_research_artifacts_dir(workspace_root))),
                           SQLiteResearchWorkingRecords(store), FsResearchMethodStore(build_research_methods_dir(workspace_root)),
                           prepare_publication_service(workspace_root, dependencies, None))


def prepare_research_channels(workspace_root: Path, research: ResearchService) -> ResearchChannelService:
    """装配渠道绑定服务。参数：工作区、研究服务。返回：绑定服务。异常：存储错误。"""
    return ResearchChannelService(research, SQLiteResearchBindings(ResearchStore(build_research_store_path(workspace_root))))
