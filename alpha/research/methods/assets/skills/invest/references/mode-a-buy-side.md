# Mode A — Buy-Side Equity Research

Use for business understanding/quality, a bare ticker, stock analysis, an IC memo, re-underwriting or a thesis update. Start with the business rather than a target price.

## Depth And Required References

- **Standard multi-lens, the default:** read [business understanding and quality](business-quality.md) and apply the multi-lens pass below. Use the recent-four-period baseline, latest annual filing and current price/expectations for stock-opportunity analysis. Broaden discovery before selecting the decisive questions; do not wait for the user to name specialist modes.
- **Quick:** when a quick or brief view is requested, compress to the most informative lenses and evidence, retaining the four-period baseline for new underwriting. Do not silently use Quick for an unrestricted company-analysis request.
- **Full:** deep/comprehensive research, an IC memo, re-underwriting, long history or financial-model reconstruction (including DCF/normalized EPS/reverse DCF) uses [the longitudinal underwriting loop](underwriting-loop.md). It supplies the longer history, recent-three-month research/interview discovery, forecast support, valuation attribution and consistency audit. Do not simulate missing history or replace a requested model with a toy bridge; narrow supplied-input arithmetic is not a Full-model request.
- **Monitoring:** use [thesis reconciliation](thesis-reconciliation.md) for the affected prior claims, earnings update or cross-case error review. Reuse valid operating history; no material change means a concise `no thesis change` and the checked evidence window, not a new report.

Business-only work ends with supported business understanding/quality and remaining questions. Do not force valuation, a pricing dispute or exposure advice. Narrow arithmetic and technical requests follow the entrypoint's direct routes.

## Default Multi-Lens Pass

For Standard and Full, examine the company across the perspectives below before narrowing. For stock-opportunity research, read and apply Mode B alongside A. Proactively look for material operating changes and runway constraints, then read D and E when those conditions apply; they do not require explicit user keywords. For business-only work, use the relevant operating/scenario reasoning without forcing numerical valuation. This is analytical model composition, not a requirement to call multiple language models or agents.

| Perspective | Question and analytical route |
|---|---|
| Business and financial quality | A: who pays, why this company wins, cash conversion, governance and capital allocation; distinguish demand, accounting and financing explanations. |
| Competing outcomes and belief updates | [B — Joint scenarios](mode-b-bayesian-growth.md): which coherent paths fit the evidence, what separates them, and how new evidence changes support; probabilities may remain unquantified. |
| Expectations and valuation | A + B: independently supported cash-flow/per-share outcomes versus dated consensus and conditional price requirements; use economically compatible valuation cross-checks. |
| Options-market distribution | [One-year option-implied distribution](options-implied-distribution.md): when reliable data exist, show the dated risk-neutral probabilities attached to terminal price thresholds/ranges and compare them with—not substitute them for—the fundamental scenarios. |
| Runway and competition | [E — Runway/quality](mode-e-tam-adj-peg.md): obtainable profitable demand, penetration, growth duration, reinvestment and competitive response; use normalized economics when PEG is inapplicable. |
| Change and transmission | [D — News to financials](mode-d-serenity-alpha.md): how a product, contract, supply, cost or regulatory change reaches cash, on what timing and with which offsets. Search for relevant changes rather than wait for pasted news. |
| Downside and survivability | [Uncertainty and exposure](uncertainty-exposure.md) for opportunity/risk research: joint failure, funding, dilution, liquidity and the strongest countercase; a good business or upside scenario is not sufficient. |
| Price behavior versus fundamentals | [C — GF-DMA](mode-c-gf-dma.md) when evidence raises a meaningful trend/divergence question. A rally or fall alone is not proof of a fundamental change; unavailable comparable price/estimate history limits diagnostics. |

Each applied lens should contribute a distinct evidence-backed inference, challenged assumption or material unresolved question. Do not merely list model names. If a relevant lens lacks inputs, seek accessible evidence, retain its qualitative insight and mark unsupported calculations unavailable; missing data is different from economic inapplicability. No fixed quota of models, sources or report sections is required.

Integrate the results into one judgment. Explain agreement, consequential disagreement and which observation would resolve it; do not count shared assumptions or repeated news as independent confirmation. Several models can all be wrong for the same reason. Preserve differentiated views such as strong business quality but demanding price, or improving earnings but worsening funding risk. Do not average incompatible values or fabricate probabilities, quality multipliers or a composite score to make the models agree.

## Recent Four Earnings Periods

For new company underwriting, prioritize the latest four reported fiscal quarters and their earnings materials/calls, including prepared remarks and available Q&A. Q4 and its annual filing cover one economic period, not two. Use the actual cadence for semiannual or irregular issuers, compare equal-duration periods and label missing quarters/calls. This baseline is distinct from Full's recent-three-month external research window; older necessary filings remain relevant.

Extract the sequence that changes judgment: operating/economic metrics; contemporaneous guidance/consensus versus actuals; revised ranges; promised versus delivered milestones; and revealing Q&A with original period/section links. An analyst's question is not guidance, an unanswered question is not confirmation or failure, and later revised estimates are not the original expectation. Test seasonality, mix, acquisitions, accounting and disclosure lag before declaring a trend or turning point. Full retains the period comparison in the underwriting reference; Quick compresses decisive changes. Let table headers and adjacent explanations show periods and overlaps rather than narrating template compliance.

## Investigate Toward A Judgment

1. **Resolve the boundary.** Confirm security/exchange, fiscal year, reporting currency, segments and source cutoff; ask only if unresolved ambiguity risks selecting the wrong company.
2. **Map the business and its constraints.** Follow a customer transaction to collected cash, then identify material cohorts/segments, competitors, substitutes, suppliers and capital requirements. Establish who pays, who captures incremental value and who can interrupt it. Business quality comes from observable behavior and economics, not labels.
3. **Locate the live dispute.** Identify the few uncertain relationships that could change the requested judgment, preserving material interactions and survival constraints. Select the lens by the business model and company-specific bottleneck, not a sector label. A GPU owner awaiting acceptance and a software vendor dependent on one distributor require different inquiry.
4. **Obtain discriminating evidence.** Test the strongest plausible rival, inspect original footnotes/contracts/call exchanges and pursue relevant customer, competitor or supplier evidence now. A source list and a plan to investigate are not substitutes for an accessible decisive check.
5. **Rebuild and price where requested.** Bridge demand, unit economics, support costs, reinvestment, working capital, financing and dilution into per-share outcomes. Preserve reported/guided/consensus/assumed layers and use [the data contract](data-contract.md) for linked calculations. Choose suitable valuation methods, justify load-bearing assumptions and reconcile coherent scenarios; do not average away conflicts.
6. **State what survives and what would change it.** Give the supported quality/thesis conclusion, conditional value/return when possible, strongest countercase, and economically meaningful falsifier with source and observation window. If several necessary links can fail, retain that set rather than invent a single-variable story.

These are decision criteria, not compulsory report sections. Mean reversion or structural change can be useful hypotheses when evidence distinguishes them; neither is a required asset label.

## Find Information That Changes The Answer

Seek gaps between a reported metric and the economic mechanism it is supposed to represent. Growth can come from acquisitions rather than demand; favorable gross margins can conceal necessary support costs; bookings can precede revenue while collections lag. Use the [business-quality lenses](business-quality.md) to discover material omitted dependencies, then investigate the few that matter most.

Judge a new perspective by its differential prediction: what observable fact would look different if it were right? Identify what a source adds beyond the current information set and how it changes an operating assumption, quality judgment, uncertainty or price requirement. Different opinions repeating management are not new evidence. A familiar public fact can yield a useful inference after correcting a denominator or connecting costs; do not manufacture secret information, expert access or disagreement.

Allocate effort by economic impact, uncertainty and feasibility of resolution, without a fixed variable/source count or composite score. Use a comparable incumbent, challenger or predecessor when it can teach unfamiliar economics, reconciling business mix and accounting before transferring margins or multiples. Borrow methods by mechanism and prerequisites—horizon, capital, control rights, liquidity—not allegiance to a famous investor. Investigate accessible contrary evidence as seriously as confirmation.

Deep preparation may rationally end in waiting. Preserve the business conditions, valuation hurdle and invalidation evidence that would justify reopening the work; a later filing, operating change or price dislocation can then trigger a focused comparison instead of a fresh story. Do not confuse inactivity with insight, research time with earned conviction, or a reached price threshold with permission to ignore deteriorating economics. The objective is readiness for a high-quality decision, not a low trade count or a performance of patience.

End each consequential inquiry with the supported inference and its limit. Unsupported but testable explanations remain research hypotheses; `no demonstrated edge` is a useful outcome. Stop low-information repetition, not requested work. Separate research effort from capital commitment: observing a company requires no purchase. User-strategy exclusion, unattractive price and insufficient understanding are different conclusions. Use `Too Hard at present` only for a decisive link still unbounded after feasible inquiry, with the unresolved question and reopening evidence.

## Expectations And Valuation

Keep three objects distinct: dated observed consensus, conditional price-implied requirements and an independently supported forecast. Missing consensus stays missing; a conditional reverse valuation may still be useful. One price does not identify a unique growth path or probability distribution. Forward and reverse models sharing assumptions are not independent confirmations.

A liquid option surface can identify a dated risk-neutral terminal-price distribution under explicit market and contract assumptions. It is a fourth, distinct object: market state prices shaped by risk premia, hedging demand and technical frictions—not the market's objective forecast. Use the approximately one-year expiry and [the option-distribution method](options-implied-distribution.md) when reliable inputs are accessible; do not infer the distribution from spot price or implied volatility alone.

Use price to locate the hurdle, not to tune the forecast until mispricing appears. To claim a variant, show the specific difference, original evidence, credible rival and effect on per-share value. Public good news, a target above the quote or low coverage alone does not establish neglect. A conditional positive or negative value gap can be reported without inventing market beliefs; label assumption-sensitive conclusions accordingly.

After an earnings miss or sharp selloff, separate at least three possible changes: the underlying customer/economic engine, the timing or magnitude of reported results, and the price/holder/liquidity response. Reconcile the miss to the previously supported operating mechanism and longer sequence before calling it noise or structural damage. A still-intact engine plus a lower price can improve prospective payoff; neither the company's historical scale nor the size of the decline proves that the engine is intact. Claims that short-horizon mandates or forced selling created the gap require observable support and remain a mispricing hypothesis, not a default explanation.

Choose DCF, normalized earnings, reverse DCF, SOTP, NAV, EV/revenue, EV/EBITDA or other methods by economic fit. Full triangulates where informative; do not force incompatible models. Distinguish present-value gaps from dated holding-period returns, and reported growth from value reaching common shareholders. A risk-free yield is not the equity discount rate; long-run moat analysis does not justify precise annual forecasts for a decade.

Preserve evidence/authorization requirements and explicit user strategy constraints; revise empirical heuristics when counterevidence warrants it. Positive FCF, accelerating revenue, founder ownership and fixed PE bands are not universal quality/value laws. Test investment-phase losses, cyclical normalization, distributions and governance on their economics. Record consequential changes to a heuristic and its limits, without inferring the user's temperament.

## Deliver A Decision-Useful Report

Lead with the answer and what the research changed or clarified. Then expose the mechanism, decisive evidence and counterevidence, economics, uncertainty and next resolving observation. A reader should understand why the conclusion follows and what could overturn it—not merely see completed headings. Preserve claim-level citations and the [required writing handoff](../SKILL.md#required-writing-pass-for-final-articles).

| Depth | Preserve in the deliverable, where applicable |
|---|---|
| Quick | Concise answer from the most informative lenses; decisive evidence, countercase, uncertainty and next check, with valuation only where in scope |
| Standard multi-lens | Business/quality and operating changes; competing scenarios, expectations/value, approximately one-year option-implied distribution when reliably observable, runway and material event transmission; downside, material disagreements across lenses, evidence gaps and falsifiers |
| Full | Standard conclusions plus source/history coverage, customer/value-chain/competitive economics, reproducible financial model and allocation/financing bridges, assumption support, valuation triangulation/attribution and coherent scenarios with detailed tables |
| Monitoring | Prior claim and due observation, actual evidence, what changed in mechanism/estimate/price, consequence and next validation point; retain old versions |

Organize supporting detail around the argument; use appendices/tables for auditability rather than repeating a full template for each model. Make the substantive contributions and consequential limits of the selected lenses visible in the report, without a boilerplate list of irrelevant exclusions. Probabilities can be unavailable, but required research cannot disappear because the verdict is unresolved. Full applies [financial evidence and claim audit](financial-evidence.md) before delivery; propagate corrected inputs to affected scenarios and conclusions, not unrelated work.
