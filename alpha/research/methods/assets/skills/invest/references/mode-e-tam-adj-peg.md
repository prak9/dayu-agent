# Mode E — TAM-Adjusted PEG

Use in default Standard/Full research whenever growth duration, penetration, competition or reinvestment runway materially affects the case, without requiring the user to name this mode. Also use for explicit TAM-Adj-PEG or quality-adjusted growth valuation. Apply the qualitative runway/quality lens first; activating it does not require an adjusted PEG number.

This is an **uncalibrated screening heuristic**, not a fair-value model or a standalone trade signal. Its factors and legacy bands have no demonstrated out-of-sample calibration here. Report that status with any calculation; a lower adjusted PEG alone does not establish cheapness.

## Formula And Units

```text
Adjusted Growth = EPS CAGR x TAM Runway Factor x Quality Factor
TAM-Adj-PEG = Forward PE / Adjusted Growth
```

Use EPS CAGR as a percentage number: Forward PE 40 and adjusted growth 50% produce 0.8. Show ordinary PEG alongside the adjusted result, with the factor inputs and their provenance. “Adjusted Growth” is an index denominator, not a forecast EPS growth rate. Do not add TAM CAGR to EPS CAGR. TAM mainly modifies duration and confidence, and each factor must add information not already embedded in the EPS forecast.

If PE or EPS CAGR is not meaningful, mark the method inapplicable and use normalized earnings, EV/revenue, milestone scenarios, or an option-style framework.

## TAM Runway Factor

When a supported duration estimate is available, `sqrt(high-growth duration / 5)`, capped at 2.0, is an optional heuristic. Declare the formula or user-supplied convention and retain precision until final rounding. If duration is unsupported, leave the factor and adjusted result `N/A`, or calculate an explicitly hypothetical sensitivity rather than filling a default.

Do not assign runway from a sector label. Test penetration, TAM growth, share durability, capacity, competition, substitution, technology iterations, requalification, and whether frontier AI shifts the profit pool.

## Quality Factor

There is no calibrated mapping from a qualitative label such as moat or platform to a numeric multiplier. Use an explicit user-supplied factor or clearly hypothetical sensitivity; otherwise leave the factor and adjusted result `N/A`. Do not invent a factor from the business description.

Evaluate accrual of TAM to the company, pricing power, customer concentration, technology/requalification risk, sustainable margins, capex, second sourcing, financing/dilution, and AI substitution.

## Interpretation

Report supported or explicitly hypothetical Low/Base/High factor combinations. If a plausible parameter change materially alters the screening result, label the conclusion `model-sensitive`; do not turn a band crossing into a buy/sell rule. An explicitly requested legacy or personal band may be reported as that convention, not as independently established fair value.

Do not double-count moat, margins, cyclicality, or TAM already present in the forecast. Explain how much of the result comes only from changing factors. For example, PE 40 / EPS growth 20 gives ordinary PEG 2; user-specified factors 1.4 and 1.4 lower it to about 1.02 without adding cash-flow evidence. Put durable advantages into margin, incremental return, reinvestment duration/fade, or scenario probabilities in a cash-flow model instead of awarding another quality premium for the same effect. If those economics cannot be checked, conclude `valuation unresolved`, not “cheap.”

Special cases:

- **Loss-making:** no direct PE/PEG; focus on milestones, normalized economics, financing, and dilution.
- **Cyclical:** use mid-cycle EPS; separate structural demand from inventory/capacity/margin cycle.
- **Turnaround:** show current/base and successful-normalization cases separately.

## Output

Within Mode A, integrate the supported runway, competitive constraints and valuation consequences into the joint analysis. Use the calculation outline below only for a meaningful supported or explicitly hypothetical PEG exercise; do not create empty factor tables for ordinary research.

```markdown
# [Ticker] — TAM-Adj-PEG
## Current Valuation And Input Quality
## EPS/Revenue/TAM Growth And Penetration
## Runway Factor: Low / Base / High
## Quality Factor: Low / Base / High
## Calculation And Sensitivity
## Calibration Status, Model Sensitivity, And Cash-Flow Cross-Check
## Upside Requirements, Risks, And Milestones
## Conditional Position Type
## Sources And Missing Inputs
```
