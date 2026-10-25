"""外部研究的默认工具装配，不启动本地 Codex 或其他模型。"""

from dataclasses import dataclass
from pathlib import Path

from alpha.engine.tool_registry import ToolRegistry
from alpha.fins.research_material_processing import prepare_financial_material_processor
from alpha.fins.research_reader import FinsResearchReader
from alpha.fins.service_runtime import DefaultFinsRuntime
from alpha.fins.storage.research_materials import FsFinancialMaterialBlobs
from alpha.fins.tools.fins_tools import register_fins_read_tools
from alpha.research.analysis_tools import register_analysis_tools
from alpha.research.candidates import ResearchCandidates
from alpha.research.material_tools import register_material_tools
from alpha.research.storage.analysis import SQLiteResearchAnalysis
from alpha.research.storage.artifacts import FsResearchArtifactStore
from alpha.research.storage.materials import SQLiteResearchMaterials
from alpha.research.storage.methods import FsResearchMethodStore
from alpha.research.storage.revisions import SQLiteResearchRevisions
from alpha.research.storage.store import ResearchStore
from alpha.research.storage.working import SQLiteResearchWorkingRecords
from alpha.research.tools import register_research_tools
from alpha.services.external_research_service import ExternalResearchService
from alpha.services.research_service import ResearchService
from alpha.workspace_paths import build_research_artifacts_dir, build_research_methods_dir, build_research_store_path


@dataclass(frozen=True)
class ExternalToolRegistryFactory:
    """每个执行独立续读游标，持久仓储仍共享同一研究库。"""

    workspace: Path

    def __call__(self) -> ToolRegistry:
        """构造有作用域的实际工具目录。参数：无。返回：注册表。异常：装配失败。"""
        store = ResearchStore(build_research_store_path(self.workspace))
        working = SQLiteResearchWorkingRecords(store)
        methods = FsResearchMethodStore(build_research_methods_dir(self.workspace))
        runtime = DefaultFinsRuntime.create(workspace_root=self.workspace)
        registry = ToolRegistry()
        register_research_tools(registry, working, methods, SQLiteResearchRevisions(store, FsResearchArtifactStore(build_research_artifacts_dir(self.workspace))))
        register_analysis_tools(registry, ResearchCandidates(SQLiteResearchAnalysis(store), working, methods), FinsResearchReader(runtime))
        register_material_tools(registry, working, SQLiteResearchMaterials(store, FsFinancialMaterialBlobs(self.workspace)),
                                self.workspace / "tmp", prepare_financial_material_processor(self.workspace))
        register_fins_read_tools(registry, service=runtime.get_tool_service())
        return registry


def prepare_external_research(workspace: Path, research: ResearchService) -> ExternalResearchService:
    """装配外部入口。参数：工作区、研究服务。返回：外部服务。异常：无。"""
    return ExternalResearchService(research, ExternalToolRegistryFactory(workspace))
