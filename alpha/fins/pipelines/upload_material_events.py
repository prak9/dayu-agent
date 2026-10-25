"""上传材料事件模型。

该模块定义 `upload_material_stream` 对外输出的标准事件结构，
用于 GUI/Web 实时消费上传过程。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from alpha.fins.domain.document_models import now_iso8601


class UploadMaterialEventType(StrEnum):
    """上传材料事件类型。"""

    UPLOAD_STARTED = "upload_started"
    CONVERSION_STARTED = "conversion_started"
    FILE_UPLOADED = "file_uploaded"
    FILE_SKIPPED = "file_skipped"
    FILE_FAILED = "file_failed"
    UPLOAD_COMPLETED = "upload_completed"
    UPLOAD_FAILED = "upload_failed"


@dataclass(frozen=True)
class UploadMaterialEvent:
    """上传材料事件。

    Attributes:
        event_type: 事件类型。
        ticker: 股票代码。
        document_id: 可选文档 ID（文档级事件会携带）。
        payload: 事件负载（字段按事件类型动态扩展）。
        emitted_at: 事件生成时间（ISO8601）。
    """

    event_type: UploadMaterialEventType
    ticker: str
    document_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    emitted_at: str = field(default_factory=now_iso8601)
