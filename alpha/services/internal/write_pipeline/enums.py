"""写作流水线内部枚举与固定集合。

该模块集中承载 write pipeline 内部稳定的固定字符串集合，避免
业务分支在多个模块里散落硬编码字面量。
"""

from __future__ import annotations

from enum import StrEnum


class WriteSceneName(StrEnum):
    """写作流水线 scene 名称。"""

    WRITE = "write"
    REGENERATE = "regenerate"
    FIX = "fix"
    REPAIR = "repair"
    INFER = "infer"
    DECISION = "decision"
    AUDIT = "audit"
    CONFIRM = "confirm"
    OVERVIEW = "overview"


PRIMARY_WRITE_SCENES: tuple[WriteSceneName, ...] = (
    WriteSceneName.WRITE,
    WriteSceneName.REGENERATE,
    WriteSceneName.FIX,
    WriteSceneName.REPAIR,
)
"""主写作模型使用的核心 scene 集合。"""


PRIMARY_MODEL_WRITE_SCENES: tuple[WriteSceneName, ...] = PRIMARY_WRITE_SCENES + (
    WriteSceneName.OVERVIEW,
)
"""使用主写作模型的 scene 集合，包含概览页。"""


AUDIT_WRITE_SCENES: tuple[WriteSceneName, ...] = (
    WriteSceneName.INFER,
    WriteSceneName.DECISION,
    WriteSceneName.AUDIT,
    WriteSceneName.CONFIRM,
)
"""使用审计模型的 scene 集合。"""


class WritePhaseName(StrEnum):
    """写作流水线固定 phase 名称。"""

    INITIAL = "initial"


class RepairStrategy(StrEnum):
    """章节重写策略。"""

    PATCH = "patch"
    REGENERATE = "regenerate"
    NONE = "none"


class RepairResolutionMode(StrEnum):
    """修复合同中单条违规的处置模式。"""

    DELETE_CLAIM = "delete_claim"
    REWRITE_WITH_EXISTING_EVIDENCE = "rewrite_with_existing_evidence"
    ANCHOR_FIX_ONLY = "anchor_fix_only"


class AuditCategory(StrEnum):
    """审计分类。"""

    OK = "ok"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    CONTENT_VIOLATION = "content_violation"
    STYLE_VIOLATION = "style_violation"


class AuditRuleCode(StrEnum):
    """审计规则编号。"""

    UNKNOWN = "unknown"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    E1 = "E1"
    E2 = "E2"
    E3 = "E3"
    C1 = "C1"
    C2 = "C2"
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"
    S5 = "S5"
    S6 = "S6"
    S7 = "S7"


EVIDENCE_AUDIT_RULE_CODES: tuple[AuditRuleCode, ...] = (
    AuditRuleCode.E1,
    AuditRuleCode.E2,
    AuditRuleCode.E3,
)
"""证据类审计规则集合。"""


CONTENT_AUDIT_RULE_CODES: tuple[AuditRuleCode, ...] = (
    AuditRuleCode.C1,
    AuditRuleCode.C2,
)
"""内容类审计规则集合。"""


STYLE_AUDIT_RULE_CODES: tuple[AuditRuleCode, ...] = (
    AuditRuleCode.S1,
    AuditRuleCode.S2,
    AuditRuleCode.S3,
    AuditRuleCode.S4,
    AuditRuleCode.S5,
    AuditRuleCode.S6,
    AuditRuleCode.S7,
)
"""风格类审计规则集合。"""


LOW_PRIORITY_AUDIT_RULE_CODES = frozenset(
    {
        AuditRuleCode.C2,
        AuditRuleCode.S4,
        AuditRuleCode.S5,
        AuditRuleCode.S6,
        AuditRuleCode.S7,
    }
)
"""低优先级规则集合，不单独阻断章节通过。"""


BLOCKING_EVIDENCE_AUDIT_RULE_CODES = frozenset(EVIDENCE_AUDIT_RULE_CODES)
"""会直接打回证据不足的规则集合。"""


BLOCKING_CONTENT_AUDIT_RULE_CODES = frozenset({AuditRuleCode.C1})
"""会直接打回内容违规的规则集合。"""


REGENERATE_EVIDENCE_AUDIT_RULE_CODES = frozenset({AuditRuleCode.E3})
"""必须整章重建的证据规则集合。"""


STRUCTURAL_REPAIR_AUDIT_RULE_CODES = frozenset(
    {
        AuditRuleCode.P1,
        AuditRuleCode.P2,
        AuditRuleCode.P3,
    }
)
"""必须走结构性修复或重建的规则集合。"""


CONFIRMABLE_EVIDENCE_AUDIT_RULE_CODES = frozenset(
    {
        AuditRuleCode.E1,
        AuditRuleCode.E2,
    }
)
"""允许进入 confirm 复核环节的证据规则集合。"""


def build_audit_scope_rules_payload() -> dict[str, list[str]]:
    """构建 audit prompt 使用的规则范围摘要。

    Args:
        无。

    Returns:
        包含 evidence/content/style 三组规则码的 JSON 兼容字典。

    Raises:
        无。
    """

    return {
        "evidence_rules": [rule.value for rule in EVIDENCE_AUDIT_RULE_CODES],
        "content_rules": [rule.value for rule in CONTENT_AUDIT_RULE_CODES],
        "style_rules": [rule.value for rule in STYLE_AUDIT_RULE_CODES],
    }


class RepairTargetKind(StrEnum):
    """repair patch 的目标粒度。"""

    SUBSTRING = "substring"
    LINE = "line"
    BULLET = "bullet"
    PARAGRAPH = "paragraph"


class EvidenceConfirmationStatus(StrEnum):
    """证据复核结论状态。"""

    CONFIRMED_MISSING = "confirmed_missing"
    SUPPORTED = "supported"
    SUPPORTED_BUT_ANCHOR_TOO_COARSE = "supported_but_anchor_too_coarse"
    SUPPORTED_ELSEWHERE_IN_SAME_FILING = "supported_elsewhere_in_same_filing"


def normalize_repair_resolution_mode(raw_value: object) -> RepairResolutionMode:
    """把单条修复处置模式规范化为枚举。

    Args:
        raw_value: 原始处置模式值。

    Returns:
        规范化后的修复处置模式；未知值回退为 ``REWRITE_WITH_EXISTING_EVIDENCE``。

    Raises:
        无。
    """

    try:
        return RepairResolutionMode(
            str(raw_value or RepairResolutionMode.REWRITE_WITH_EXISTING_EVIDENCE).strip()
            or RepairResolutionMode.REWRITE_WITH_EXISTING_EVIDENCE
        )
    except ValueError:
        return RepairResolutionMode.REWRITE_WITH_EXISTING_EVIDENCE


def is_initial_write_phase(phase: str) -> bool:
    """判断当前 phase 是否为初始写作阶段。

    Args:
        phase: 当前阶段名。

    Returns:
        若为初始阶段返回 ``True``，否则返回 ``False``。

    Raises:
        无。
    """

    return phase == WritePhaseName.INITIAL


def normalize_repair_strategy(raw_value: object) -> RepairStrategy:
    """把原始 repair_strategy 规范化为枚举。

    Args:
        raw_value: 原始策略值。

    Returns:
        规范化后的重写策略；未知值回退为 ``PATCH``。

    Raises:
        无。
    """

    try:
        return RepairStrategy(str(raw_value or RepairStrategy.PATCH).strip() or RepairStrategy.PATCH)
    except ValueError:
        return RepairStrategy.PATCH


def normalize_audit_category(raw_value: object) -> AuditCategory:
    """把原始审计分类规范化为枚举。

    Args:
        raw_value: 原始分类值。

    Returns:
        规范化后的审计分类；未知值回退为 ``STYLE_VIOLATION``。

    Raises:
        无。
    """

    try:
        return AuditCategory(str(raw_value or AuditCategory.STYLE_VIOLATION).strip() or AuditCategory.STYLE_VIOLATION)
    except ValueError:
        return AuditCategory.STYLE_VIOLATION


def normalize_audit_rule_code(raw_value: object) -> AuditRuleCode:
    """把原始审计规则码规范化为枚举。

    Args:
        raw_value: 原始规则码值。

    Returns:
        规范化后的规则码；未知值回退为 ``UNKNOWN``。

    Raises:
        无。
    """

    normalized = str(raw_value or "").strip().upper()
    if not normalized:
        return AuditRuleCode.UNKNOWN
    try:
        return AuditRuleCode(normalized)
    except ValueError:
        return AuditRuleCode.UNKNOWN


def normalize_repair_target_kind(raw_value: object) -> RepairTargetKind:
    """把 repair patch 目标粒度规范化为枚举。

    Args:
        raw_value: 原始目标粒度值。

    Returns:
        规范化后的目标粒度；未知值回退为 ``SUBSTRING``。

    Raises:
        无。
    """

    try:
        return RepairTargetKind(str(raw_value or RepairTargetKind.SUBSTRING).strip() or RepairTargetKind.SUBSTRING)
    except ValueError:
        return RepairTargetKind.SUBSTRING


def normalize_evidence_confirmation_status(raw_value: object) -> EvidenceConfirmationStatus:
    """把证据复核状态规范化为枚举。

    Args:
        raw_value: 原始状态值。

    Returns:
        规范化后的证据复核状态。

    Raises:
        ValueError: 当状态值不受支持时抛出。
    """

    return EvidenceConfirmationStatus(str(raw_value or "").strip())


def build_rewrite_phase_name(*, strategy: RepairStrategy, retry_count: int) -> str:
    """根据重写策略生成动态 phase 名称。

    Args:
        strategy: 当前重写策略。
        retry_count: 当前重试次数。

    Returns:
        动态 phase 名称。

    Raises:
        无。
    """

    if strategy == RepairStrategy.REGENERATE:
        return f"regenerate_{retry_count}"
    return f"repair_{retry_count}"


__all__ = [
    "AUDIT_WRITE_SCENES",
    "AuditCategory",
    "AuditRuleCode",
    "BLOCKING_CONTENT_AUDIT_RULE_CODES",
    "BLOCKING_EVIDENCE_AUDIT_RULE_CODES",
    "build_audit_scope_rules_payload",
    "CONFIRMABLE_EVIDENCE_AUDIT_RULE_CODES",
    "CONTENT_AUDIT_RULE_CODES",
    "EVIDENCE_AUDIT_RULE_CODES",
    "EvidenceConfirmationStatus",
    "LOW_PRIORITY_AUDIT_RULE_CODES",
    "PRIMARY_MODEL_WRITE_SCENES",
    "PRIMARY_WRITE_SCENES",
    "REGENERATE_EVIDENCE_AUDIT_RULE_CODES",
    "RepairResolutionMode",
    "RepairStrategy",
    "RepairTargetKind",
    "STRUCTURAL_REPAIR_AUDIT_RULE_CODES",
    "STYLE_AUDIT_RULE_CODES",
    "WritePhaseName",
    "WriteSceneName",
    "build_rewrite_phase_name",
    "is_initial_write_phase",
    "normalize_audit_category",
    "normalize_audit_rule_code",
    "normalize_evidence_confirmation_status",
    "normalize_repair_resolution_mode",
    "normalize_repair_strategy",
    "normalize_repair_target_kind",
]