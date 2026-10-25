"""研究附件接受服务，文件来源和新输入固定在同一研究。"""

from dataclasses import dataclass
from pathlib import Path

from alpha.contracts.research import SubmitResearchTurnRequest, ResearchTurn
from alpha.contracts.research_materials import FinancialMaterialTarget, ResearchMaterials
from alpha.fins.storage.research_materials import FsFinancialMaterialBlobs
from alpha.fins.ticker_normalization import normalize_ticker
from alpha.research.storage.materials import SQLiteResearchMaterials
from alpha.research.storage.store import ResearchStore
from alpha.services.research_service import ResearchService
from alpha.workspace_paths import build_research_store_path


@dataclass(frozen=True)
class ResearchMaterialService:
    """仅保存原件与排队输入，正文提取在后续 Host 工具执行内完成。"""

    research: ResearchService
    records: ResearchMaterials

    def accept(self, research_id: str, owner_id: str, request_key: str, name: str, content: bytes, caption: str = "") -> ResearchTurn:
        """导入并建立新一轮。参数：研究、用户、键、名称、字节、说明。返回：接受输入。异常：越权、附件或财报说明错误。"""
        self.research.overview(research_id, owner_id)
        target: FinancialMaterialTarget | None = None
        if caption.startswith("/filing"):
            parts = caption.split(maxsplit=3)
            if len(parts) < 3 or parts[0] != "/filing":
                raise ValueError("财报附件说明格式：/filing TICKER FORM_TYPE [研究要求]，例如 /filing AAPL 10-K 核对收入")
            target = FinancialMaterialTarget(normalize_ticker(parts[1]).canonical, parts[2])
            caption = parts[3] if len(parts) > 3 else "核对财报材料并更新研究"
        material = self.records.put(research_id, owner_id, request_key, name, content, target)
        instruction = (f"新增用户材料：{material.name}\nmaterial_id: {material.material_id}\n来源：{material.source_ref}\n"
                       "原件已保存，正文尚未提取或核验。请用 research_read_material 读取并保留定位；"
                       "公开时间未知时不得假设已满足历史截止时间。\n" + (caption or "核对新增材料对当前研究结论的影响，提交新版本。"))
        return self.research.submit(SubmitResearchTurnRequest(research_id, owner_id, request_key + ":material-turn", instruction,
                                                            attachment_refs=(material.material_id,)))


def prepare_research_materials(workspace_root: Path, research: ResearchService) -> ResearchMaterialService:
    """装配附件边界。参数：工作区、研究服务。返回：材料服务。异常：仓储初始化错误。"""
    return ResearchMaterialService(research, SQLiteResearchMaterials(ResearchStore(build_research_store_path(workspace_root)), FsFinancialMaterialBlobs(workspace_root)))
