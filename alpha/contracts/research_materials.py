"""研究附件元数据与财报字节的窄存取边界。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from alpha.contracts.cancellation import CancellationToken

MAX_MATERIAL_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class FinancialMaterialTarget:
    """用户明确声明的财报所属公司与文档类型。"""

    ticker: str
    form_type: str


@dataclass(frozen=True)
class ResearchMaterial:
    """原始附件事实，不代表正文已经提取或论据已核验。"""

    material_id: str
    research_id: str
    name: str
    media_type: str
    sha256: str
    size: int
    received_at: datetime
    source_ref: str
    financial_target: FinancialMaterialTarget | None


class FinancialMaterialBlobs(Protocol):
    """所有财报字节必须通过 Fins 仓储实现。"""

    def put(self, target: FinancialMaterialTarget, document_id: str, name: str, content: bytes) -> str:
        """幂等保存财报源材料。参数：目标、稳定文档 ID、名称、字节。返回：来源引用。异常：冲突或存储错误。"""
        ...

    def read(self, target: FinancialMaterialTarget, document_id: str, name: str) -> bytes:
        """读取财报原始字节。参数：目标、文档、名称。返回：内容。异常：缺失或存储错误。"""
        ...



class ResearchMaterials(Protocol):
    """作用域内附件仓储，不解释 Host 生命周期。"""

    def put(self, research_id: str, owner_id: str, request_key: str, name: str, content: bytes,
            financial_target: FinancialMaterialTarget | None = None) -> ResearchMaterial:
        """接受原始附件。参数：研究、用户、键、名称、字节、可选财报目标。返回：材料。异常：越权或冲突。"""
        ...

    def list_materials(self, research_id: str, owner_id: str) -> list[ResearchMaterial]:
        """列出附件。参数：研究、用户。返回：元数据。异常：越权。"""
        ...

    def read(self, material_id: str, research_id: str, owner_id: str) -> tuple[ResearchMaterial, bytes]:
        """核验后读取附件。参数：材料、研究、用户。返回：元数据及内容。异常：越界或损坏。"""
        ...


class FinancialMaterialProcessing(Protocol):
    """财报结构处理与原件持久化分离。"""

    def prepare(self, target: FinancialMaterialTarget, document_id: str, name: str, token: CancellationToken | None) -> str:
        """准备 Fins 结构。参数：目标、文档、原件、令牌。返回：文档 ID。异常：取消或处理失败。"""
        ...
