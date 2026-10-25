"""财报解析器子包。"""

from .fmp_company_alias_resolver import (
    FmpAliasInferenceError,
    FmpAliasInferenceResult,
    infer_company_aliases_from_fmp,
)

__all__ = [
    "FmpAliasInferenceError",
    "FmpAliasInferenceResult",
    "infer_company_aliases_from_fmp",
]
