"""以原子目录提交不可变研究快照，校验覆盖全部证据和报告。"""

from __future__ import annotations

import errno
import re
import json
from pathlib import Path
from typing import cast

from alpha.contracts.research import ResearchConflictError
from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research_working import ResearchReportContent
from alpha.research.evidence import decode_research_evidence
from alpha.research.storage.encoding import canonical_json, content_hash
from alpha.research.storage.atomic import staged_directory, sync_directory, write_bytes_synced

_REPORT_FILE = "report.md"
_EVIDENCE_FILE = "evidence.json"
_METADATA_FILE = "metadata.json"
_CONTRACT_FILE = "data-contract.json"
_HASH_FILE = "sha256"
_PAYLOAD_FILES = (_REPORT_FILE, _EVIDENCE_FILE, _METADATA_FILE, _CONTRACT_FILE)
_OPAQUE_ID = re.compile(r"(?:research|revision)_[a-f0-9]{32}\Z")


def _snapshot_hash(payload: dict[str, str]) -> str:
    """计算完整快照摘要。参数：payload 文件文本。返回：摘要。异常：无。"""
    return content_hash(canonical_json({name: payload[name] for name in _PAYLOAD_FILES}))


class FsResearchArtifactStore:
    """目录 rename 为提交点，已存在版本只接受完全相同的重放。"""

    def __init__(self, root: Path) -> None:
        """设置产物根目录。参数：root 根目录。返回：无。异常：I/O 错误。"""
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _directory(self, research_id: str, revision_id: str) -> Path:
        """解析受限版本目录。参数：研究、版本 ID。返回：目录。异常：非法 ID 或路径越界。"""
        if not _OPAQUE_ID.fullmatch(research_id) or not research_id.startswith("research_"):
            raise ValueError("研究 ID 格式非法")
        if not _OPAQUE_ID.fullmatch(revision_id) or not revision_id.startswith("revision_"):
            raise ValueError("研究版本 ID 格式非法")
        directory = self._root / research_id / "revisions" / revision_id
        if not directory.resolve().is_relative_to(self._root):
            raise ValueError("研究产物路径越界")
        return directory

    def commit_snapshot(
        self, research_id: str, revision_id: str, *, report_markdown: str,
        evidence_json: str, metadata_json: str, data_contract_json: str | None,
    ) -> str:
        """原子提交快照。参数：研究、版本及四类显式正文。返回：摘要。异常：冲突或 I/O 错误。"""
        destination = self._directory(research_id, revision_id)
        payload = {
            _REPORT_FILE: report_markdown, _EVIDENCE_FILE: evidence_json,
            _METADATA_FILE: metadata_json, _CONTRACT_FILE: data_contract_json if data_contract_json is not None else "null",
        }
        fingerprint = _snapshot_hash(payload)
        if destination.exists():
            self.read_report(research_id, revision_id, fingerprint)
            return fingerprint
        destination.parent.mkdir(parents=True, exist_ok=True)
        # 临时目录与目标同文件系统；中断留下的临时目录从不参与版本读取。
        with staged_directory(destination.parent) as staging:
            for name, text in {**payload, _HASH_FILE: fingerprint}.items():
                write_bytes_synced(staging / name, text.encode("utf-8"))
            sync_directory(staging)
            try:
                staging.rename(destination)
            except OSError as exc:
                # 多个恢复者可能计算同一快照；不得覆盖已经提交的目录。
                if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                    raise
                self.read_report(research_id, revision_id, fingerprint)
            sync_directory(destination.parent)
        return fingerprint

    def _read_snapshot(self, research_id: str, revision_id: str, expected_hash: str) -> dict[str, str]:
        """一次读取并核验全部快照。参数：研究、版本、数据库摘要。返回：文件文本。异常：缺失或篡改。"""
        directory = self._directory(research_id, revision_id)
        if any((directory / name).is_symlink() for name in (*_PAYLOAD_FILES, _HASH_FILE)):
            raise ResearchConflictError("研究快照校验失败：文件不能是符号链接")
        try:
            payload = {name: (directory / name).read_text(encoding="utf-8") for name in _PAYLOAD_FILES}
            recorded_hash = (directory / _HASH_FILE).read_text(encoding="utf-8")
        except (FileNotFoundError, UnicodeError) as exc:
            raise ResearchConflictError("研究快照校验失败：文件缺失或损坏") from exc
        if recorded_hash != expected_hash or _snapshot_hash(payload) != expected_hash:
            raise ResearchConflictError("研究快照校验失败：内容摘要不匹配")
        return payload

    def read_report(self, research_id: str, revision_id: str, expected_hash: str) -> str:
        """校验并读取报告。参数：研究、版本、数据库摘要。返回：原报告。异常：缺失/篡改时冲突。"""
        return self._read_snapshot(research_id, revision_id, expected_hash)[_REPORT_FILE]

    def read_content(self, research_id: str, revision_id: str, expected_hash: str) -> ResearchReportContent:
        """读取完整报告及原始证据。参数：研究、版本、数据库摘要。返回：强类型内容。异常：完整性或证据结构损坏。"""
        payload = self._read_snapshot(research_id, revision_id, expected_hash)
        evidence = decode_research_evidence(cast(JsonValue, json.loads(payload[_EVIDENCE_FILE])))
        contract = cast(JsonValue, json.loads(payload[_CONTRACT_FILE]))
        return ResearchReportContent(payload[_REPORT_FILE], evidence, canonical_json(contract) if contract is not None else None)
