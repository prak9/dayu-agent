"""研究附件元数据及一般材料字节；财报原件委托 Fins 仓储。"""

from datetime import datetime
from hashlib import sha256
from pathlib import PurePath
import sqlite3
from uuid import NAMESPACE_URL, uuid5

from alpha.contracts.research import ResearchConflictError, ResearchState
from alpha.contracts.research_materials import MAX_MATERIAL_BYTES, FinancialMaterialBlobs, FinancialMaterialTarget, ResearchMaterial
from alpha.research.storage.encoding import canonical_json, content_hash, encode_time, owned_research, utc_now
from alpha.research.storage.store import ResearchStore

_MEDIA_TYPES = {".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown", ".html": "text/html", ".htm": "text/html"}


def _metadata(row: sqlite3.Row) -> ResearchMaterial:
    """解码材料身份。参数：行。返回：元数据。异常：损坏字段。"""
    target = FinancialMaterialTarget(str(row["ticker"]), str(row["form_type"])) if row["ticker"] is not None else None
    return ResearchMaterial(str(row["material_id"]), str(row["research_id"]), str(row["name"]), str(row["media_type"]),
                            str(row["sha256"]), int(row["size"]), datetime.fromisoformat(str(row["received_at"])), str(row["source_ref"]), target)


def validate_material(name: str, content: bytes) -> str:
    """校验真实字节与文件名。参数：名称、内容。返回：媒体类型。异常：超限、不支持或签名损坏。"""
    if not name or PurePath(name).name != name or "\\" in name or "\x00" in name or len(name) > 200:
        raise ValueError("附件文件名非法")
    suffix = PurePath(name).suffix.lower()
    if suffix not in _MEDIA_TYPES:
        raise ValueError("附件仅支持 PDF、TXT、Markdown 和 HTML")
    if not 0 < len(content) <= MAX_MATERIAL_BYTES:
        raise ValueError("附件为空或实际大小超过 20 MiB")
    if suffix == ".pdf":
        if not content.lstrip().startswith(b"%PDF-"):
            raise ValueError("附件不是有效 PDF 签名")
    else:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeError:
            raise ValueError("文本附件必须使用 UTF-8 编码") from None
        if "\x00" in text:
            raise ValueError("附件包含二进制内容")
    return _MEDIA_TYPES[suffix]


class SQLiteResearchMaterials:
    """原始文件不可变，请求重放复用同一材料；不缓存未经核验的提取状态。"""

    def __init__(self, store: ResearchStore, financial: FinancialMaterialBlobs) -> None:
        """注入两个存储边界。参数：研究库、财报字节端口。返回：无。异常：无。"""
        self._store = store
        self._financial = financial

    def put(self, research_id: str, owner_id: str, request_key: str, name: str, content: bytes,
            financial_target: FinancialMaterialTarget | None = None) -> ResearchMaterial:
        """持久保存原件。参数：研究、用户、键、文件、内容、财报目标。返回：材料。异常：越权、归档或幂等冲突。"""
        media_type = validate_material(name, content)
        digest = sha256(content).hexdigest()
        fingerprint = content_hash(canonical_json({"sha256": digest, "name": name,
            "ticker": financial_target.ticker if financial_target else None, "form_type": financial_target.form_type if financial_target else None}))
        if not request_key.strip():
            raise ValueError("附件请求键不能为空")
        identifier = "material_" + uuid5(NAMESPACE_URL, f"alpha:{research_id}:{fingerprint}").hex
        with self._store.connection(write=True) as conn:
            research = owned_research(conn, research_id, owner_id)
            previous = conn.execute("SELECT * FROM material_requests WHERE research_id=? AND request_key=?", (research_id, request_key)).fetchone()
            if previous is not None and str(previous["input_hash"]) != fingerprint:
                raise ResearchConflictError("相同附件请求键内容改变")
            row = conn.execute("SELECT * FROM research_materials WHERE material_id=?", (identifier,)).fetchone()
            if row is not None:
                conn.execute("INSERT OR IGNORE INTO material_requests VALUES (?,?,?,?)", (research_id, request_key, fingerprint, identifier))
                return _metadata(row)
            if str(research["state"]) != ResearchState.ACTIVE.value:
                raise ResearchConflictError("请先重新打开研究再导入附件")
            source_ref = self._financial.put(financial_target, identifier, name, content) if financial_target else f"research-material:{identifier}"
            conn.execute("INSERT INTO research_materials VALUES (?,?,?,?,?,?,?,?,?,?,?)", (identifier, research_id, name, media_type, digest,
                len(content), encode_time(utc_now()), source_ref, financial_target.ticker if financial_target else None,
                financial_target.form_type if financial_target else None, None if financial_target else content))
            conn.execute("INSERT INTO material_requests VALUES (?,?,?,?)", (research_id, request_key, fingerprint, identifier))
            row = conn.execute("SELECT * FROM research_materials WHERE material_id=?", (identifier,)).fetchone()
            return _metadata(row)

    def list_materials(self, research_id: str, owner_id: str) -> list[ResearchMaterial]:
        """列出当前研究原件。参数：研究、用户。返回：材料。异常：越权。"""
        with self._store.connection() as conn:
            owned_research(conn, research_id, owner_id)
            return [_metadata(row) for row in conn.execute("SELECT * FROM research_materials WHERE research_id=? ORDER BY received_at,material_id", (research_id,)).fetchall()]

    def read(self, material_id: str, research_id: str, owner_id: str) -> tuple[ResearchMaterial, bytes]:
        """核对所属研究和哈希。参数：材料、研究、用户。返回：元数据、字节。异常：越界或损坏。"""
        with self._store.connection() as conn:
            owned_research(conn, research_id, owner_id)
            row = conn.execute("SELECT * FROM research_materials WHERE material_id=? AND research_id=?", (material_id, research_id)).fetchone()
            if row is None:
                raise KeyError("材料不存在于当前研究")
            meta = _metadata(row)
            content = self._financial.read(meta.financial_target, material_id, meta.name) if meta.financial_target else bytes(row["body"])
            if len(content) != meta.size or sha256(content).hexdigest() != meta.sha256:
                raise ResearchConflictError("附件原件完整性损坏")
            return meta, content
