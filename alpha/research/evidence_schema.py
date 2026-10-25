"""报告证据字段的声明真源，供直接提交与候选稿工具共用。"""

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research import EvidenceClassification

EVIDENCE_SCHEMA: dict[str, JsonValue] = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "evidence_id": {"type": "string", "minLength": 1}, "source_ref": {"type": "string", "minLength": 1},
        "document_type": {"type": "string", "minLength": 1}, "excerpt": {"type": "string", "minLength": 1},
        "classification": {"type": "string", "enum": [item.value for item in EvidenceClassification]},
        "accessed_at": {"type": "string", "format": "date-time", "description": "实际访问时间，ISO 8601，必须带时区。"},
        "locator": {"type": ["string", "null"]},
        "published_at": {"type": ["string", "null"], "format": "date-time", "description": "已核验公开时间；不接受日期范围对象，不知道时填 null 并说明原因。"},
        "available_at": {"type": ["string", "null"], "format": "date-time"},
        "time_missing_reason": {"type": ["string", "null"]},
    },
    "required": ["evidence_id", "source_ref", "document_type", "excerpt", "classification", "accessed_at"],
}
