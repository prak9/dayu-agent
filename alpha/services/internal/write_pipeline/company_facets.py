"""公司级 facet 归因与章节裁剪辅助。

该模块负责：
- 解析 facet 归因 JSON 输出。
- 基于公司级 facet 过滤章节 `preferred_lens` 与 `ITEM_RULE`。
- 生成面向写作 prompt 的“公司业务类型与关键约束”摘要。
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from alpha.services.internal.write_pipeline.chapter_contracts import ChapterContract, ItemRule, PreferredLens
from alpha.services.internal.write_pipeline.models import CompanyFacetProfile

_MAX_MATCHED_PREFERRED_LENSES = 6
_MAX_CONDITIONAL_RULES = 4
_MAX_OPTIONAL_RULES = 3


def parse_company_facets(raw_text: str, *, facet_catalog: dict[str, list[str]]) -> CompanyFacetProfile:
    """解析公司级 facet 归因 JSON。

    Args:
        raw_text: 模型返回的原始文本。
        facet_catalog: 来自模板的候选词表。

    Returns:
        结构化 facet 归因结果。

    Raises:
        ValueError: 当 JSON 非法、字段缺失或标签超出词表时抛出。
    """

    normalized_text = str(raw_text or "").strip()
    if not normalized_text:
        raise ValueError("公司级 facet 归因输出为空")
    try:
        payload = json.loads(normalized_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"公司级 facet 归因输出不是合法 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("公司级 facet 归因输出必须为 JSON 对象")
    profile = CompanyFacetProfile.from_dict(payload)
    _validate_company_facets(profile, facet_catalog=facet_catalog)
    return profile


def filter_chapter_contract_by_facets(
    contract: ChapterContract,
    company_facets: CompanyFacetProfile | None,
    facet_catalog: dict[str, list[str]],
) -> ChapterContract:
    """按公司级 facet 过滤章节合同中的 `preferred_lens`。

    Args:
        contract: 原始章节合同。
        company_facets: 公司级 facet 归因结果。
        facet_catalog: 来自模板的“主业务类型 / 关键约束”候选词表。

    Returns:
        过滤后的章节合同。

    Raises:
        无。
    """

    if company_facets is None:
        return contract
    filtered_lenses = filter_preferred_lenses(
        contract.preferred_lens,
        company_facets,
        facet_catalog=facet_catalog,
    )
    return replace(contract, preferred_lens=filtered_lenses)


def filter_item_rules_by_facets(
    item_rules: list[ItemRule],
    company_facets: CompanyFacetProfile | None,
    facet_catalog: dict[str, list[str]],
) -> list[ItemRule]:
    """按公司级 facet 过滤章节条件写作规则。

    Args:
        item_rules: 原始规则列表。
        company_facets: 公司级 facet 归因结果。
        facet_catalog: 来自模板的“主业务类型 / 关键约束”候选词表。

    Returns:
        过滤后的规则列表。

    Raises:
        无。
    """

    if company_facets is None:
        return list(item_rules)
    generic_conditional_rules = [rule for rule in item_rules if rule.mode == "conditional" and not rule.facets_any]
    generic_optional_rules = [rule for rule in item_rules if rule.mode == "optional" and not rule.facets_any]
    conditional_matched = _select_item_rules(
        item_rules,
        company_facets=company_facets,
        facet_catalog=facet_catalog,
        mode="conditional",
        matched=True,
    )
    optional_matched = _select_item_rules(
        item_rules,
        company_facets=company_facets,
        facet_catalog=facet_catalog,
        mode="optional",
        matched=True,
    )
    filtered = list(generic_conditional_rules)
    filtered.extend(
        _take_rules(
            [rule for rule in conditional_matched if rule not in filtered],
            _MAX_CONDITIONAL_RULES,
        )
    )
    filtered.extend(generic_optional_rules)
    filtered.extend(
        _take_rules(
            [rule for rule in optional_matched if rule not in filtered],
            _MAX_OPTIONAL_RULES,
        )
    )
    if filtered:
        return filtered
    return list(item_rules[: min(len(item_rules), _MAX_CONDITIONAL_RULES + _MAX_OPTIONAL_RULES)])


def filter_preferred_lenses(
    preferred_lenses: list[PreferredLens],
    company_facets: CompanyFacetProfile,
    *,
    facet_catalog: dict[str, list[str]],
) -> list[PreferredLens]:
    """按公司级 facet 过滤 `preferred_lens`。

    Args:
        preferred_lenses: 原始认知口径列表。
        company_facets: 公司级 facet 归因结果。
        facet_catalog: 来自模板的“主业务类型 / 关键约束”候选词表。

    Returns:
        过滤后的认知口径列表。

    Raises:
        无。
    """

    generic_lenses = [item for item in preferred_lenses if not item.facets_any]
    core_matched = _select_lenses(
        preferred_lenses,
        company_facets=company_facets,
        facet_catalog=facet_catalog,
        priority="core",
        matched=True,
    )
    supporting_matched = _select_lenses(
        preferred_lenses,
        company_facets=company_facets,
        facet_catalog=facet_catalog,
        priority="supporting",
        matched=True,
    )
    matched_lenses = _take_lenses(core_matched, _MAX_MATCHED_PREFERRED_LENSES)
    matched_lenses.extend(
        _take_lenses(
            [item for item in supporting_matched if item not in matched_lenses],
            _MAX_MATCHED_PREFERRED_LENSES - len(matched_lenses),
        )
    )
    filtered = list(generic_lenses)
    filtered.extend([item for item in matched_lenses if item not in filtered])
    if filtered:
        return filtered
    return list(preferred_lenses[: min(len(preferred_lenses), _MAX_MATCHED_PREFERRED_LENSES)])


def render_company_facets_for_prompt(company_facets: CompanyFacetProfile | None) -> str:
    """渲染面向 prompt 的公司业务类型与关键约束摘要。

    Args:
        company_facets: 公司级 facet 归因结果。

    Returns:
        多行 Markdown 文本。

    Raises:
        无。
    """

    if company_facets is None:
        return "- 主业务类型\n未推断\n\n- 关键约束\n未推断"
    primary = "、".join(company_facets.primary_facets) if company_facets.primary_facets else "未命中"
    cross_cutting = (
        "、".join(company_facets.cross_cutting_facets)
        if company_facets.cross_cutting_facets
        else "未命中"
    )
    lines = [
        "- 主业务类型",
        primary,
        "",
        "- 关键约束",
        cross_cutting,
    ]
    if company_facets.confidence_notes:
        lines.extend(["", "- 简短说明", company_facets.confidence_notes])
    return "\n".join(lines)


def _validate_company_facets(
    profile: CompanyFacetProfile,
    *,
    facet_catalog: dict[str, list[str]],
) -> None:
    """校验 facet 归因结果是否合法。

    Args:
        profile: 待校验的归因结果。

    Returns:
        无。

    Raises:
        ValueError: 当标签超出词表时抛出。
    """

    business_model_candidates = set(facet_catalog.get("business_model_candidates", []))
    constraint_candidates = set(facet_catalog.get("constraint_candidates", []))
    invalid_primary = sorted(set(profile.primary_facets) - business_model_candidates)
    invalid_cross_cutting = sorted(set(profile.cross_cutting_facets) - constraint_candidates)
    if invalid_primary:
        raise ValueError(f"business_model_tags 包含未受控标签: {', '.join(invalid_primary)}")
    if invalid_cross_cutting:
        raise ValueError(f"constraint_tags 包含未受控标签: {', '.join(invalid_cross_cutting)}")


def _lens_matches(
    lens: PreferredLens,
    *,
    company_facets: CompanyFacetProfile,
    facet_catalog: dict[str, list[str]],
) -> bool:
    """判断单条 lens 是否命中当前公司的 facet 路由。

    Args:
        lens: 待判断的认知口径。
        company_facets: 公司级 facet 归因结果。
        facet_catalog: 来自模板的“主业务类型 / 关键约束”候选词表。

    Returns:
        是否命中。

    Raises:
        无。
    """

    if not lens.facets_any:
        return False
    return _matches_facet_route(
        lens.facets_any,
        company_facets=company_facets,
        facet_catalog=facet_catalog,
    )


def _rule_matches(
    rule: ItemRule,
    *,
    company_facets: CompanyFacetProfile,
    facet_catalog: dict[str, list[str]],
) -> bool:
    """判断单条 item rule 是否命中当前公司的 facet 路由。

    Args:
        rule: 待判断的条件规则。
        company_facets: 公司级 facet 归因结果。
        facet_catalog: 来自模板的“主业务类型 / 关键约束”候选词表。

    Returns:
        是否命中。

    Raises:
        无。
    """

    if not rule.facets_any:
        return False
    return _matches_facet_route(
        rule.facets_any,
        company_facets=company_facets,
        facet_catalog=facet_catalog,
    )


def _select_lenses(
    preferred_lenses: list[PreferredLens],
    *,
    company_facets: CompanyFacetProfile,
    facet_catalog: dict[str, list[str]],
    priority: str,
    matched: bool,
) -> list[PreferredLens]:
    """按优先级和匹配状态筛选 lens。

    Args:
        preferred_lenses: 原始认知口径列表。
        company_facets: 公司级 facet 归因结果。
        facet_catalog: 来自模板的“主业务类型 / 关键约束”候选词表。
        priority: 当前筛选的优先级。
        matched: 是否仅保留已命中的规则。

    Returns:
        命中的 lens 列表或通用 lens 列表。

    Raises:
        无。
    """

    selected: list[PreferredLens] = []
    for item in preferred_lenses:
        if item.priority != priority:
            continue
        is_matched = _lens_matches(
            item,
            company_facets=company_facets,
            facet_catalog=facet_catalog,
        )
        if matched and is_matched:
            selected.append(item)
        if not matched and not item.facets_any:
            selected.append(item)
    return selected


def _select_item_rules(
    item_rules: list[ItemRule],
    *,
    company_facets: CompanyFacetProfile,
    facet_catalog: dict[str, list[str]],
    mode: str,
    matched: bool,
) -> list[ItemRule]:
    """按模式和匹配状态筛选 item rule。

    Args:
        item_rules: 原始条件规则列表。
        company_facets: 公司级 facet 归因结果。
        facet_catalog: 来自模板的“主业务类型 / 关键约束”候选词表。
        mode: 当前筛选的规则模式。
        matched: 是否仅保留已命中的规则。

    Returns:
        命中的规则列表或通用规则列表。

    Raises:
        无。
    """

    selected: list[ItemRule] = []
    for item in item_rules:
        if item.mode != mode:
            continue
        is_matched = _rule_matches(
            item,
            company_facets=company_facets,
            facet_catalog=facet_catalog,
        )
        if matched and is_matched:
            selected.append(item)
        if not matched and not item.facets_any:
            selected.append(item)
    return selected


def _matches_facet_route(
    route_facets: list[str],
    *,
    company_facets: CompanyFacetProfile,
    facet_catalog: dict[str, list[str]],
) -> bool:
    """按“业务类型优先、关键约束补充”的语义判断 facet 路由。

    设计原则：
    - 若某条 lens / rule 声明了业务类型 facet，则必须先命中主业务类型。
      这能避免像 AAPL 因 `监管敏感` 而错误命中医药或金融业务口径。
    - 只有当一条 lens / rule 完全不声明业务类型 facet、只声明横切约束时，
      才允许仅凭 `cross_cutting_facets` 命中。

    Args:
        route_facets: 单条 lens / rule 的 `facets_any`。
        company_facets: 公司级 facet 归因结果。
        facet_catalog: 来自模板的“主业务类型 / 关键约束”候选词表。

    Returns:
        当前公司是否命中该条路由。

    Raises:
        无。
    """

    business_candidates = set(facet_catalog.get("business_model_candidates", []))
    constraint_candidates = set(facet_catalog.get("constraint_candidates", []))
    route_business_facets = {item for item in route_facets if item in business_candidates}
    route_constraint_facets = {item for item in route_facets if item in constraint_candidates}
    active_primary_facets = set(company_facets.primary_facets)
    active_constraint_facets = set(company_facets.cross_cutting_facets)

    if route_business_facets:
        return bool(route_business_facets.intersection(active_primary_facets))
    if route_constraint_facets:
        return bool(route_constraint_facets.intersection(active_constraint_facets))
    return False


def _take_lenses(items: list[PreferredLens], limit: int) -> list[PreferredLens]:
    """按给定上限截取 lens 列表。"""

    if limit <= 0:
        return []
    return list(items[:limit])


def _take_rules(items: list[ItemRule], limit: int) -> list[ItemRule]:
    """按给定上限截取规则列表。"""

    if limit <= 0:
        return []
    return list(items[:limit])
