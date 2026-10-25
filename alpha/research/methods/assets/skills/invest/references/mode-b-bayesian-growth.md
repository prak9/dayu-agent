# Mode B — Bayesian Intrinsic Growth Valuation

Use alongside Mode A by default for Standard/Full stock research, including a bare ticker, and for explicit Bayesian valuation, intrinsic versus implied growth, posterior updates or FOMO versus fundamentals. Start with coherent competing operating scenarios; a numerical posterior requires evidence, not merely activation of this mode. Business-only research can use the scenario/update lens without valuation.

The decision question is whether evidence-backed joint operating scenarios offer attractive value and net returns relative to the requirements of the current price. Choose a horizon appropriate to the business and decision; 3–5 years is an example, not a universal forecast window.

When the reverse-valuation question specifically uses PE and normalized EPS, [conditional PE implied growth](pe-implied-growth.md) provides an optional deterministic calculation. It produces neither priors nor posteriors and does not replace coherent joint scenarios.

When a reliable approximately one-year option surface is available, [the option-implied distribution](options-implied-distribution.md) can show which terminal prices the market currently makes expensive or cheap to insure. Keep those risk-neutral probabilities separate from evidence-based scenario probabilities: neither is a prior for the other without a justified bridge from state prices to real-world likelihoods.

## Inputs

Use verified company fundamentals, industry cycle, demand/supply, historical and guided growth, TAM and penetration, competitive position, valuation, price/multiple changes, consensus revisions, and the new information being evaluated. Mark missing inputs instead of manufacturing precision.

## Joint Hypotheses

Define scenarios from the company's actual mechanisms—contraction, normalization, share gain, or expansion as relevant. Do not assign universal growth buckets or midpoint values. Each scenario links growth path and duration, margins, reinvestment/incremental returns, financing/dilution, and terminal conditions. Preserve material dependencies; high growth and low reinvestment cannot be combined without an economic explanation.

Value each coherent scenario before aggregation:

```text
scenario inputs -> dated cash flows -> scenario equity value and net investor payoff
probability-weighted value = sum(p_s * V_s)
```

Use common valuation dates, currency, security basis, and return horizons. Growth-rate means may summarize the distribution but cannot replace it: generally `V(E[g]) != E[V(g)]`. State whether a scenario persists across years or transitions; those are different models. Withhold numeric values when the required inputs are absent rather than converting a growth midpoint into a target price. Probability-weighted values remain conditional on the valuation model and are not uniquely inferred market prices.

## Workflow

1. **Ground the prior.** Use an applicable reference class, company economics, cycle, TAM, and competition; expose selection and comparability limits. Put downside caution into scenario and risk tests rather than an arbitrary probability haircut. Market excitement alone does not justify an expansion scenario.
2. **Map each observation to a latent variable.** Write `observed signal -> latent growth/margin variable -> rival explanation -> disclosure lag`. Cluster observations caused by the same event; they are not independent confirmations.
3. **Update probabilities.** Show prior, likelihood interpretation, and posterior as ranges when supported. Without a defensible likelihood or prior, explain the direction and limits of the update or use explicitly hypothetical probability sensitivity; do not fabricate posterior precision to complete the format. Cyclical, one-off, or backlog-timing signals should not automatically raise long-run growth. If the mechanism or reporting entity changes, rebuild the model rather than force an update.
4. **Value the joint scenarios.** Calculate scenario cash flows, equity values, and net investor payoffs before applying posterior probabilities. Show sensitivity and tail outcomes, not just weighted growth or an average target. Apply the shared numeric-data rules, including the direct-arithmetic path for wholly hypothetical examples; a data validator does not validate the economic model.
5. **Reverse-engineer the price.** Treat market-implied growth as an inverse problem, not a unique observable. Show combinations of growth duration, steady-state margin, reinvestment/ROIC, dilution, discount rate, and terminal value consistent with price. Name fixed assumptions and free variables. A price alone identifies neither a unique joint forecast nor scenario probabilities; do not present these solutions as observed sell-side consensus.
6. **Compare evidence with price requirements.** Identify the exact observed forecast or conditional hurdle that differs, what it already includes, the original evidence supporting the variant, its incremental per-share cash-flow effect and strongest rival. Keep common assumptions fixed for attribution, then stress joint risks. Do not confuse public good news or an above-market target with an unpriced advantage. Keep the operating forecast independently evidenced rather than fitting it to a preferred verdict. Conclude attractive, unattractive, no demonstrated edge or unresolved only to the extent supported by the scenarios and estimation error.
7. **Measure price/fundamental divergence.** Separate changes in operating expectations from multiple expansion, liquidity, theme crowding, short squeeze, and index flow.
8. **Define verification.** Name competing observable predictions, the source and comparable metric, economically justified breakpoint, maturation/disclosure lag and decision effect. Where the decisive variable is unreported, expose proxy limitations instead of treating absent disclosure as falsification.

## Output

When integrated into Mode A, contribute the relevant scenarios, belief update, price requirements and uncertainty to one report; the standalone outline below is not a second mandatory report. Skip out-of-scope valuation/exposure sections for business-only work.

```markdown
## Company And Decision
## Prior And Posterior Joint Scenarios
## Scenario Cash Flows, Values, Net Returns, And Tail
## Reverse-DCF / Market-Implied Joint Assumptions
## Price Versus Fundamental Update
## Valuation State And Scenario Range
## Upside Requirements And Downside Risks
## Verification Window, Falsifier, And Conditional Exposure Posture
## Sources And Missing Inputs
```

Keep thesis quality, valuation, and exposure separate. Position language must be conditional research guidance—observe, small test, add after proof, trade-only, reduce, or exit—not personalized instruction.
