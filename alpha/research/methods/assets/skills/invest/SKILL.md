---
name: invest
description: Research public companies and stocks using filings, earnings calls, business quality, valuation, and thesis monitoring. Use for U.S., Hong Kong, or A-share equity analysis.
---

# Invest

## Decision Contract

Answer the user's research question, not a report template. Fundamental research explains how customer value becomes retained cash, what is changing, and what evidence could change the judgment. Business-only work can end there; valuation, technical calculations and narrow updates retain their scope.

Keep business quality, thesis support, price attractiveness and exposure/survivability separate. The load-bearing chain is **operating mechanism -> discriminating evidence -> supported forecast -> price requirements when relevant -> per-share payoff -> observable falsifier**. A citation supports an observation, not automatically the inference built on it.

Seek information that changes an important estimate, distinguishes plausible explanations or exposes a neglected constraint. An insight may confirm the prevailing view or show that no edge is demonstrated; novelty, contrarianism and source volume are not objectives. Complete accessible decisive checks instead of merely proposing them. Distinguish a supported case, an illustrative sensitivity and an unresolved underwriting question. Mark unavailable inputs `未核验`, name the resolving evidence and bound the conclusion; do not invent targets or probabilities to finish a template. Outputs are research analysis, not personalized trading instructions.

## Route By Request

Use Mode A as the synthesis spine for company research, not an exclusive model choice. Load and apply complementary modes through its default multi-lens pass; direct extraction, calculation and explicitly narrow requests keep their scope.

| Request | Route |
|---|---|
| Business/quality, bare ticker, stock analysis, IC memo, re-underwriting or thesis update | [Mode A — Buy-Side Research](references/mode-a-buy-side.md) |
| Default stock research, joint operating scenarios, intrinsic vs implied growth, posterior update or FOMO vs fundamentals | [Mode B — Joint Scenarios](references/mode-b-bayesian-growth.md), integrated with A |
| GF-DMA request, or a material price/fundamental divergence discovered during research that trend diagnostics could clarify | [Mode C — GF-DMA](references/mode-c-gf-dma.md) |
| Material news/product/procurement/supply-chain change, whether supplied or discovered; beneficiary search when requested | [Mode D — News To Financials](references/mode-d-serenity-alpha.md) |
| Growth duration, penetration or reinvestment runway matters to value; explicit TAM-Adj-PEG | [Mode E — TAM-Adj-PEG](references/mode-e-tam-adj-peg.md), with its qualitative runway lens before any heuristic calculation |
| Conditional PE-to-growth hurdle or forward-price arithmetic | [PE implied growth](references/pe-implied-growth.md), without requiring Mode B or a full report |
| One-year option-implied terminal-price probabilities or an options-market expectations check | [Option-implied distribution](references/options-implied-distribution.md) |
| Opportunity search, universe screen or candidate-list review | [Opportunity discovery](references/opportunity-discovery.md), with the relevant domain lens |
| Standalone financial-report or call extraction | [Financial extraction](references/financial-extraction.md) or [earnings transcripts](references/earnings-transcripts.md) directly |

A bare ticker or generic stock-analysis request starts broad company research; the user need not name B, D or E for their relevant lenses to activate. Consider C when price behavior raises a material question, not merely to fill a technical section. More lenses mean distinct questions and evidence, not a vote or an aggregate score. A single-company request does not authorize a universe sweep or persistent watchlist.

Inside Mode A, **Standard multi-lens** is the default; **Quick** applies when brevity or a quick view is requested. **Full** adds deep/comprehensive research, IC memos, re-underwriting, long history or requested financial-model reconstruction (including DCF/normalized EPS/reverse DCF); **Monitoring** reconciles affected claims against the prior thesis. Narrow supplied-input calculations retain their direct route. Follow Mode A's four-period operating baseline and Full's longer-history/recent-research instructions. Breadth and depth are separate: Standard crosses relevant perspectives without automatically requiring every model's full report. Missing inputs narrow claims, not all feasible work; identify undelivered components rather than silently downgrading Full to Quick. Ask only for consequential user-owned choices that authorized research cannot resolve.

## Shared Source Discipline

Verify time-sensitive prices, filings, guidance, estimates, valuation inputs, calls, catalysts and regulations. Prefer original exchange/regulatory filings and company IR for reported facts; test interpretation with relevant customer, supplier, competitor, regulator and industry evidence. Reputable data providers and specialist research/interviews can add estimates or mechanisms, but their authority does not validate proprietary underlying data. Full includes the recent-three-month discovery pass.

Preserve source, document type, publication/filing and access dates, and actual section/page/timecode where available. Distinguish reported facts, management statements, dated third-party estimates/consensus and analyst inference. Cite the original document next to material claims and table values; a bibliography alone is insufficient. Trace borrowed claims to their source or label `二手转引，原始证据未核验`. A transcript proves what was said, not its truth. Show derived calculations and cite inputs without implying that the source endorsed the result. Never invent locators or claim full-text access from snippets; preserve these links in authorized archives.

For material numeric inputs retain value, unit, currency, period, accounting/estimate basis, first-available timestamp and missing reason. Linked calculations, model reconstruction and historical evaluation use [the data contract](references/data-contract.md) and `scripts/validate_invest_data.py`; Quick may express the same semantics in a compact table. Unknown is not zero, and arithmetic validation is not source verification. Self-contained hypothetical arithmetic needs stated premises, units, horizon and checked formulas—not a fabricated source ledger. Real-company portions of mixed tasks retain the source contract.

For stock-opportunity research, attempt the [approximately one-year option-implied distribution](references/options-implied-distribution.md) when a sufficiently liquid chain and reproducible inputs are accessible. Report it as a dated **risk-neutral market-pricing distribution**, not an objective forecast or analyst posterior. Business-only work and narrow requests do not inherit this calculation. When the chain, rate, corporate-action adjustment or no-arbitrage fit is unreliable, state `期权隐含分布不可可靠估计` and the reason instead of manufacturing probabilities.

Use [financial evidence and claim audit](references/financial-evidence.md) for extraction, disputed support, citation repair and the Full pre-delivery check. When a material PDF fails, follow [PDF retrieval](references/pdf-retrieval.md) before declaring it unavailable. Historical research preserves the original information cutoff; current revisions and known outcomes cannot leak backward. Cluster repeated underlying observations rather than counting publishers as independent confirmation.

For U.S. filings, use current SEC/IR access; `edgartools` is optional if installed. Installing software or configuring a real SEC identity needs authorization. Do not arrange interviews, buy data or seek nonpublic information without applicable authorization.

## Exposure And Monitoring

For opportunity/risk, entry, sizing, allocation comparisons, evidence overlap or news changing a thesis, read [uncertainty and exposure](references/uncertainty-exposure.md). Monitoring distinguishes no change, confidence update, valuation-only change, core-assumption breach and new regime. Price, belief and capital commitment need not move together. Analysis does not authorize trading, alerts, watchlist mutation or continuous monitoring; those require authorization and actual persistent tooling.

## Skill Boundary And Handoff

`invest` owns investment research. Reuse supplied `decision` or `plan-skill` results; do not rerun upstream work unless needed evidence or constraints are missing/contradictory, and do not invoke all four skills by default. Final articles follow the writing pass below.

### Required Writing Pass For Final Articles

After research and necessary evidence checks, actually read and apply [writing](../writing/SKILL.md) and its [revision checklist](../writing/references/revision-checklist.md) before delivering a research report, substantive memo or article-form update, including reports delivered directly in chat without saving or publishing. For analytical arguments, also read and apply the [reasoning guide](../writing/references/reasoning-guide.md). Pure calculations, raw extraction and brief status answers retain their scope. A separate agent or user confirmation is unnecessary.

Lock the conclusion, as-of date, units/currencies/periods, scenario assumptions, fact-versus-estimate labels, valuation math, contrary evidence, risk conditions and claim-level citations. The research outline and self-written draft structure remain editable: merge, reorder or rewrite them around the reader's question. Writing cannot change conviction, evidence, numbers or requested coverage. Reconcile final text/tables against those items; send genuine evidence/model conflicts back to research. Deliver the checked article without internal handoff narration. User text and existing published content respect the authorized edit scope. Writing never authorizes publication.

Compose the article around the company's economics and the reader's investment question. Research checklists establish coverage; they do not prescribe the same advantage–caveat–verdict sequence for every business. Explain material limitations beside the claim or estimate they constrain, including their consequence for valuation or confidence. Shared model conventions can live in table notes or the methodology section; preserve local qualifiers needed to read a claim independently.

Apply the writing checklist's whole-document rhetoric review (全文修辞复核) before delivery: read paragraph openings, endings and bold statements together, then inspect suspect passages in context. Actually merge or remove repeated conclusions, repair mechanical section structures and remove internal research-process narration while retaining distinct counterevidence and necessary qualifications. Each paragraph must advance the argument; multi-company coverage should give each business the structure and space its decisive questions require. Reading the skill, validating arithmetic or finding few flagged words does not establish that the article passed this review. Stop when the identified prose defects are resolved and the protected research content still matches; no extra publication approval or separate agent is required.

## Notion Delivery

Research **does not authorize a Notion write**. Require a current explicit request or an unrevoked standing authorization covering this research type and exact target; do not re-ask when already resolved, infer it from unrelated prior writes, or expand it because the thesis changed.

When authorized, resolve one destination from context and read-only search; ask only if ambiguity remains. Preserve the dated thesis, crux, scenarios, falsifiers and claim-level citations. Choose a revision of the relevant text, a separate appendix or a dated update according to the requested deliverable and authorized edit scope; do not automatically append complete chat answers. Integrate repeated claims and retain the new evidence and its effect. Preserve historical judgments and information cutoffs, and honor an explicitly requested chronological log. Routine no-change logging requires explicit coverage. Verify the returned page ID/URL, destination/parent and expected content with proportionate readback, and report the direct link. An uncertain response calls for checking whether the write exists before retrying.

If archiving remains blocked after feasible checks, deliver completed research with `Notion archive pending`, the precise missing access/target and recovery action. Distinguish research completeness from delivery; an authorized unfinished archive remains required work.
