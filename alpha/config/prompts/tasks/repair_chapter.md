当前任务：
- 你不是来重写整章，而是对下方“章节正文”做最小必要修复。
- 只修“修复合同”命中的违规点；未命中的合规内容一律不动。
- 默认不重新做研究；优先保住本章最小判断链。
- 若“是否允许补入新事实”为 true，且“修复合同”中存在 evidence 缺口（如 `missing_evidence_slots`），可使用工具做最小必要检索，优先寻找能直接支撑本章最低必需判断链的少量事实、数字或计算基础。
- 若问题无法在既有事实边界内通过 patch 修复，应在 `notes` 中说明原因，并只输出能安全执行的最小 patch；不得擅自扩写或重写整章。

先读这几个字段，再决定下一步动作：
- `修复合同.remediation_actions[*].resolution_mode` 是代码侧已经为你收口好的处置模式，不要自己重新发明规则。
- `delete_claim`：表示该 claim 已被 confirm 证实缺证。你的下一步动作不是“弱化后保留”，而是删除包含该 claim 的完整语义单元；优先删完整 `bullet`、完整 `line` 或完整 `paragraph`。
- `rewrite_with_existing_evidence`：表示可以只用当前正文与现有证据区里已经出现、已经被支持的事实做最小改写；不得补入新的 unsupported 事实。
- `anchor_fix_only`：表示问题主要在证据锚点，不在正文事实本身。本任务不改 `### 证据与出处`，不要试图自行修 evidence line；只有在正文里确实存在可安全删去的多余细节时，才改正文。
- `target_kind=substring`：只改某个完整句子/完整 bullet/完整段落中的一小段文字。它只适用于确实找不到稳定完整单元的场景，不适用于 `delete_claim`。
- `target_kind=line`：替换一整行。
- `target_kind=bullet`：替换一个完整 bullet 条目。
- `target_kind=paragraph`：替换一个完整段落。

动作顺序（强制）：
1. 先读 `修复合同.remediation_actions`，逐条决定本轮要删、要改，还是只能在 `notes` 说明剩余问题。
2. 再看 `章节合同`，只保留支撑本章最小判断链所必需的内容。
3. 最后才为每个动作选择最稳定的 `target_kind`；能用完整 `bullet` / `line` / `paragraph` 就不要退回 `substring`。

修复原则（强制）：
- 只修正文，不修改 `### 证据与出处`。
- 允许使用工具时，只做最小必要检索；不要为保留次要细节做扩展研究。
- 先看“章节合同”要求的最低必需回答项，判断某条内容是否属于本章最小判断链。
- 若不是最小判断链内容：优先删除，或改成不带该细节的客观事实表述。
- 若“修复合同”里的某条命中 `resolution_mode=delete_claim`：必须删除该 unsupported claim 所在的完整语义单元，不得改成更弱但仍保留同一 unsupported claim 的表述；即使它属于最小判断链，也要删除该 claim，再让其余已证实内容承担最小判断链。
- 若是最小判断链内容，且命中的处置模式不是 `delete_claim`：才允许优先弱化断言、删去无证据数字或改写正文；若在既有事实边界内仍无法安全修复，应在 `notes` 中说明原因，而不是补入新事实。
- 若 evidence 缺口理论上可通过工具找到支撑，但找到的新事实仍需要修改 `### 证据与出处` 才能闭环，应在 `notes` 中说明“已定位到可用证据，但本任务不改证据区”，并仅删除、弱化或改写正文中的 unsupported 细节。
- 若同一片段同时涉及实质问题（断言过强、证据不足、数字无锚点）和样式问题，先修实质问题，再修样式。
- 证据锚点过粗、同一 filing 内有更准 section、statement rows/period 缺失等问题，不属于本任务。
- 不得生成任何命中 `### 证据与出处` 的 patch；即使你判断 evidence line 更准确，也不要在本任务里改它。
- 若“修复合同”里只命中 rule `C2` 或 `S4/S5/S6/S7` 这类低优先级提示，默认不要为了消掉低优先级问题而削弱原本更准确、更有买方价值的表述；仅在能明显减少歧义且不损失信息价值时才做弱化。
- 对“修复合同”里命中的 `S4/S5/S6`，默认优先自然改写，让读者能区分“事实 / 分析 / 前瞻 / 公司披露”；不要通过添加 `【分析】`、`【前瞻】`、`【前瞻（原文）】` 这类句首标签机械修复。
- 若前瞻性内容不属于本章最小判断链，优先删除，不要仅通过添加 `【前瞻】` 保留。
- 删除内容后，必须一并清理残留空行、空 bullet 和空小节。
- 若目标内容位于完整 bullet 或完整段落中，优先删除完整 bullet / 完整段落，不要只删其中一半。
- 若命中的处置模式是 `delete_claim`，`target_kind` 不得使用 `substring`；优先输出 `bullet`、`line` 或 `paragraph`，确保一次删除完整语义单元。
- 不得留下 `-`、`- 。`、`- ：` 这类空条目或残片标点；若删除会留下这类残片，应扩大 patch 范围，一次删除干净。
- 不得改写“章节正文”原有的小节标题文本，不得在标题前添加 `【分析】`、`【前瞻】` 或其它标签；若某个小节整体不该保留，应删除完整小节，而不是修改标题。
- `target_section_heading` 只能从“当前正文中的真实可见标题”中选，不得填写输出项名称、bullet 标签、问句、`None/null` 或其它并不存在的标题。
- 生成 patch 时，优先命中完整 bullet、完整单行或完整段落；只有确实找不到稳定的完整片段时才使用 `substring`。
- `replacement` 必须是完整、可直接落盘的最终片段；不得输出残句、悬空冒号、悬空转折、残片标点或需要再拼接才能成立的半句。

输出要求（强制）：
- 你只能输出 JSON 格式修复结果，禁止输出解释性文字。
- 输出必须是严格可解析 JSON。
- 第一字符必须是 { 或 [。
- 最后一个非空白字符必须是 } 或 ]。
- JSON 之外不得有任何字符。
- 输出 JSON schema：
{
  "patches": [
    {
      "target_excerpt": "必须与当前正文中的原文完全一致；优先使用完整 bullet、完整句子或完整小段",
      "target_kind": "可选；substring|line|bullet|paragraph",
      "target_section_heading": "可选；若目标位于某个明确小节内，填写该标题，且必须与当前正文中的标题完全一致",
      "occurrence_index": 1,
      "replacement": "替换后的完整片段；若表示删除，可输出空字符串",
      "reason": "为什么要这样改（简短）"
    }
  ],
  "notes": ["可选：补丁应用注意事项"]
}
- `patches` 必须至少包含 1 条 patch；不要输出空数组。
- 若仍有剩余问题暂时无法安全修复，把未完成部分写进 `notes`，但仍要输出至少 1 条本轮可安全执行的最小 patch。
- `target_excerpt` 必须逐字复制自“章节正文”；不得改写、概括或截断到无法稳定命中。
- 能明确为完整 bullet / 单行 / 段落时，应显式填写 `target_kind`，不要一律使用 substring；若对应 `delete_claim`，必须显式填写非 `substring` 的 `target_kind`。
- 若 `target_excerpt` 可能重复出现，必须补 `target_section_heading`；且该标题必须从下方“当前正文中的真实可见标题”中逐字选择。若在该 section 内仍重复，必须再补 `occurrence_index`（1-based）。
- 每条 patch 必须是最小修改单元；不要把整章都塞进一个 patch。

章节标题：
{{chapter}}

是否允许补入新事实：
{{allow_new_facts}}

本轮修复范围：
{{retry_scope}}

章节合同：
{{chapter_contract_block}}

修复合同：
{{last_repair_contract_block}}

当前正文中的真实可见标题：
{{current_visible_headings_block}}

章节正文：
{{last_wrote_content_block}}
