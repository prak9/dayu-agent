"""研究工具集装配，将工作区位置适配为窄仓储端口。"""

from alpha.contracts.toolset_registrar import ToolsetRegistrationContext
from alpha.research.storage.methods import FsResearchMethodStore
from alpha.research.storage.store import ResearchStore
from alpha.research.storage.working import SQLiteResearchWorkingRecords
from alpha.research.storage.artifacts import FsResearchArtifactStore
from alpha.research.storage.revisions import SQLiteResearchRevisions
from alpha.research.tools import register_research_tools
from alpha.research.judgments import ResearchJudgments
from alpha.research.judgment_tools import register_judgment_tools
from alpha.research.report_composer import ResearchReportComposer
from alpha.research.report_tools import register_report_tools
from alpha.research.analysis_tools import register_analysis_tools
from alpha.research.candidates import ResearchCandidates
from alpha.research.storage.analysis import SQLiteResearchAnalysis
from alpha.fins.research_reader import FinsResearchReader
from alpha.fins.service_runtime import DefaultFinsRuntime
from alpha.research.material_tools import register_material_tools
from alpha.research.storage.materials import SQLiteResearchMaterials
from alpha.fins.storage.research_materials import FsFinancialMaterialBlobs
from alpha.fins.research_material_processing import prepare_financial_material_processor
from alpha.workspace_paths import build_research_artifacts_dir, build_research_methods_dir, build_research_store_path


def register_research_toolset(context: ToolsetRegistrationContext) -> int:
    """装配研究工具。参数：通用注册上下文。返回：业务工具数。异常：存储初始化或注册失败。"""
    root = context.workspace.workspace_dir
    store = ResearchStore(build_research_store_path(root))
    working = SQLiteResearchWorkingRecords(store)
    methods = FsResearchMethodStore(build_research_methods_dir(root))
    count = register_research_tools(context.registry, working, methods,
                                    SQLiteResearchRevisions(store, FsResearchArtifactStore(build_research_artifacts_dir(root))))
    count += register_judgment_tools(context.registry, ResearchJudgments(working), working)
    candidates = ResearchCandidates(SQLiteResearchAnalysis(store), working, methods)
    count += register_analysis_tools(context.registry, candidates, FinsResearchReader(DefaultFinsRuntime.create(workspace_root=root)))
    count += register_report_tools(context.registry, ResearchReportComposer(candidates, ResearchJudgments(working)))
    return count + register_material_tools(context.registry, working, SQLiteResearchMaterials(store, FsFinancialMaterialBlobs(root)),
                                          root / "tmp", prepare_financial_material_processor(root))
