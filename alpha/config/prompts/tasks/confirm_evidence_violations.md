复核目标：
- 仅复核下方“待复核的疑似证据违规”中的疑似 `E1/E2/E3` 违规是否属实。
- 你不是来重做全文审计，也不是来搜索新证据。

输出要求：
- 你只能输出 JSON 格式复核结果，禁止输出解释性文字。
- 输出必须是严格可解析 JSON。
- 第一字符必须是 { 或 [。
- 最后一个非空白字符必须是 } 或 ]。
- JSON 之外不得有任何字符。
- 输出 JSON schema：
{
  "results": [
    {
      "violation_id": "必须与输入中的 violation_id 一致",
      "rule": "E1|E2|E3",
      "excerpt": "必须与输入中的 excerpt 一致",
      "status": "confirmed_missing|supported_but_anchor_too_coarse|supported_elsewhere_in_same_filing|supported",
      "reason": "为什么得出该确认结论",
      "rewrite_hint": "可选；给人看的简短修正提示",
      "anchor_fix": {
        "kind": "same_filing_section|same_filing_statement|same_filing_evidence_line",
        "action": "append|refine_existing",
        "keep_existing_evidence": true,
        "evidence_line": "仅在你已能确定完整 evidence line 时填写",
        "section_path": "同一 filing 内的稳定标题路径",
        "statement_type": "income|cash_flow|balance_sheet",
        "period": "FY2025,FY2024",
        "rows": ["需要补入的报表行标签"]
      }
    }
  ],
  "notes": ["可选：整体复核备注"]
}

复核原则（强制）：
- 只处理输入中列出的疑似 `E1/E2/E3` 违规；不要新增新的违规点。
- 只允许复核“证据与出处”已经列出的 filings / sections / pages / URLs；不得搜索新证据、不得扩展研究。
- 若证据条目使用 `Financial Statement:{statement_type}` 格式，优先使用 `get_financial_statement` 复核对应的 `statement_type / period / rows`。
- 若证据条目使用 `XBRL Facts` 格式，优先使用 `query_xbrl_facts` 复核对应的 `concepts / period`。
- 只有当证据条目是 section/item 标题路径时，才优先使用 `get_document_sections / read_section` 这类文档定位工具。
- `search_document` 只可作为同一已引用 filing / item 内的辅助检索线索，用于定位已引用 section 的直接父级或相邻标题；不得把 `search_document` 命中本身当作证据，也不得借此扩展到未引用的新来源。
- 若 cited evidence 已能直接支持 claim，应输出 `supported`。
- 若 claim 是由已引用原始数据直接推导出的派生指标（如利润率、占比、同比变化），且分子、分母与计算关系都能由当前 cited evidence 直接支持，应输出 `supported`，不要仅因该派生指标未被原文逐字披露就判定 `confirmed_missing`。
- 若 cited evidence 是同一 filing 内的 section/item 路径，且 claim 仅是路径选窄、在同一 item 的直接父级 heading 中即可被支持，可输出 `supported_but_anchor_too_coarse`；不得跨 filing、不得跳到未引用的其它 item。
- 若原始证据能支持 claim，但当前 evidence line 的锚点过粗、过泛或未对准，应输出 `supported_but_anchor_too_coarse`。
- 若 claim 在同一 filing 内的其它已知 section 中可被直接支持，且你能明确指出正确 section，但当前 cited evidence 未把该锚点列出来，应输出 `supported_elsewhere_in_same_filing`；这类问题默认只补锚点，不删正文。
- 对 `supported_but_anchor_too_coarse` / `supported_elsewhere_in_same_filing`，优先返回结构化 `anchor_fix`；仅当你能给出可执行的结构化定位时才返回它。
- 若该条为 `supported`、`confirmed_missing`，或你无法稳定给出结构化定位，请省略 `anchor_fix` 字段；不要输出空对象 `{}`。
- `anchor_fix` 只描述“正确证据应该如何定位”，不要扩展到未引用的新 filing、不要改正文。
- 若正确证据是同一 filing 内的标题路径，使用 `kind=same_filing_section`。
- 若正确证据是同一 filing 内的财务报表定位，使用 `kind=same_filing_statement`，并尽量补齐 `statement_type / period / rows`。
- 只有当你已能确定完整 evidence line 时，才使用 `kind=same_filing_evidence_line` 并填写 `evidence_line`。
- 只有当 cited evidence 确实不能支持该 claim，或按已列出的来源与定位仍无法核实该 claim 时，才输出 `confirmed_missing`。
- 不要为了格式偏好而否定正文中本应保留的高价值买方信息。

状态定义：
- `supported`：
  - cited evidence 已足够支持对应 claim
  - 这类问题不应继续作为 E 类违规保留
- `supported_but_anchor_too_coarse`：
  - 原始证据存在支持，但当前 evidence line 锚点不够细或不够稳
  - 这类问题应保留正文，只修 evidence line
- `supported_elsewhere_in_same_filing`：
  - 支持该 claim 的证据在同一 filing 内明确存在，且你能指出正确 section
  - 当前问题是 cited evidence 漏列了正确锚点，不是正文一定错误
  - 这类问题应优先补锚点，不应直接删除正文
- `confirmed_missing`：
  - 原始证据不能支持该 claim，或按已列出的来源与定位仍无法核实
  - 这类问题应继续保留为 E 类违规

章节正文：
{{chapter_markdown_block}}

证据条目：
{{evidence_items_block}}

待复核的疑似证据违规：
{{suspected_evidence_violations_block}}
