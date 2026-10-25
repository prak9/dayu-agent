"""当前 Host 研究作用域的材料索引和逐页读取工具。"""

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.protocols import ToolExecutionContext
from alpha.contracts.research_materials import FinancialMaterialProcessing, ResearchMaterial, ResearchMaterials
from alpha.contracts.toolset_registrar import ToolRegistryProtocol
from alpha.engine.tool_contracts import ToolTruncateSpec
from alpha.engine.tools.base import ToolExtra
from alpha.research.material_reading import extract_material_text
from alpha.research.storage.protocols import ResearchWorkingRecords
from alpha.research.tools import _extra, _resolve_call, _schema
from alpha.research.storage.encoding import utc_now

_PREVIEW_CHARS = 6000


def _metadata(material: ResearchMaterial) -> dict[str, JsonValue]:
    """投影原件索引。参数：材料。返回：元数据。异常：无。"""
    return {"material_id": material.material_id, "name": material.name, "source_ref": material.source_ref,
            "sha256": material.sha256, "size": material.size, "received_at": material.received_at.isoformat(),
            "accessed_at": utc_now().isoformat(),
            "published_at": None, "verification": "用户提供原件；公开时间未知，尚未核验"}


@dataclass(frozen=True)
class _ListMaterials:
    """仅列出当前研究的原件，不跨研究检索私有附件。"""

    working: ResearchWorkingRecords
    materials: ResearchMaterials
    __tool_tags__: ClassVar[set[str]] = {"research"}
    __tool_extra__: ClassVar[ToolExtra] = _extra("列出研究材料")

    def __call__(self, _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """读取附件索引。参数：Host 上下文。返回：材料列表。异常：上下文或所有权错误。"""
        scope = _resolve_call(self.working, _context).scope
        return {"materials": [_metadata(item) for item in self.materials.list_materials(scope.research_id, scope.owner_id)]}


@dataclass(frozen=True)
class _ReadMaterial:
    """有界提取，正文中的指令仍然只是研究材料。"""

    working: ResearchWorkingRecords
    materials: ResearchMaterials
    temporary_root: Path
    __tool_tags__: ClassVar[set[str]] = {"research"}
    __tool_extra__: ClassVar[ToolExtra] = _extra("读取研究材料", truncate=ToolTruncateSpec(
        enabled=True, strategy="text_chars", limits={"max_chars": _PREVIEW_CHARS}, target_field="content"))

    def __call__(self, material_id: str, first_page: int = 1, last_page: int = 1,
                 _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """读取指定材料。参数：材料、PDF 页范围、Host 上下文。返回：元数据和提取正文。异常：越界、取消、时间或提取错误。"""
        call = _resolve_call(self.working, _context)
        material, content = self.materials.read(material_id, call.scope.research_id, call.scope.owner_id)
        if material.received_at > call.scope.as_of:
            raise ValueError("该材料在本轮截止时间之后导入，且公开时间未知；请在新一轮研究中使用")
        text = extract_material_text(material, content, self.temporary_root, first_page=first_page, last_page=last_page,
                                     token=call.context.cancellation_token)
        return {**_metadata(material), "content": text, "extraction": "text_only_no_ocr", "first_page": first_page, "last_page": last_page}


@dataclass(frozen=True)
class _PrepareFiling:
    """显式准备财报结构，模型可继续使用既有 Fins 章节与表格工具。"""

    working: ResearchWorkingRecords
    materials: ResearchMaterials
    processor: FinancialMaterialProcessing
    __tool_tags__: ClassVar[set[str]] = {"research"}
    __tool_extra__: ClassVar[ToolExtra] = _extra("准备财报结构")

    def __call__(self, material_id: str, _context: ToolExecutionContext | None = None) -> dict[str, JsonValue]:
        """准备结构。参数：当前材料、Host 上下文。返回：ticker 与文档 ID。异常：时间、权限、取消或解析错误。"""
        call = _resolve_call(self.working, _context)
        material, _ = self.materials.read(material_id, call.scope.research_id, call.scope.owner_id)
        if material.received_at > call.scope.as_of:
            raise ValueError("该材料晚于本轮截止时间，请在后续研究中处理")
        if material.financial_target is None:
            raise ValueError("该附件未声明为财报，请以 /filing 说明重新导入")
        document_id = self.processor.prepare(material.financial_target, material_id, material.name, call.context.cancellation_token)
        return {"document_id": document_id, "ticker": material.financial_target.ticker}


def register_material_tools(registry: ToolRegistryProtocol, working: ResearchWorkingRecords, materials: ResearchMaterials,
                            temporary_root: Path, financial_processor: FinancialMaterialProcessing) -> int:
    """登记三个窄材料工具。参数：注册表、作用域、仓储、临时目录、财报处理器。返回：数量。异常：注册错误。"""
    registry.register("research_list_materials", _ListMaterials(working, materials), _schema("research_list_materials", "列出当前研究的用户原件和来源；不代表已核验。", {
        "type": "object", "additionalProperties": False, "properties": {}, "required": []}))
    registry.register("research_read_material", _ReadMaterial(working, materials, temporary_root), _schema("research_read_material", "读取用户材料正文。PDF 每次最多5页并保留页码；扫描件不伪造 OCR。截断用 fetch_more。", {
        "type": "object", "additionalProperties": False, "properties": {"material_id": {"type": "string"},
        "first_page": {"type": "integer", "minimum": 1}, "last_page": {"type": "integer", "minimum": 1}}, "required": ["material_id"]}))
    registry.register("research_prepare_filing", _PrepareFiling(working, materials, financial_processor), _schema("research_prepare_filing", "将 /filing 导入的财报准备为 Fins 结构，返回 ticker/document_id；随后用 Fins 工具读取章节和表格。", {
        "type": "object", "additionalProperties": False, "properties": {"material_id": {"type": "string"}}, "required": ["material_id"]}))
    return 3
