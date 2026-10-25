# Conditional PE ↔ EPS Growth

Use only for an explicit PE-growth question or a material Mode A/B price hurdle. This is a two-stage equity-cash-flow calculator, not a new research mode, default ten-year forecast, PEG rule, trading signal or observed market consensus. A single price cannot identify growth, cash conversion, duration and risk simultaneously.

## Model And Scope

Define annual decimal rates, end-of-year cash flows, a positive normalized base common-share EPS (`EPS0`), and a fixed diluted-share/security basis. For years 1 through `n`, EPS grows at constant `g` and FCFE/net income is `c`. From year `n+1`, EPS growth is `h` and FCFE/net income is `ct`. Discount equity cash flows at cost of equity `r`, not WACC:

```text
q = (1 + g) / (1 + r)
PE0 = c * sum(q^t, t = 1..n) + ct * (1 + h) / (r - h) * q^n
price = EPS0 * PE0
EPS_n = EPS0 * (1 + g)^n
```

The second term is terminal value discounted from year `n`, including the first terminal cash flow at `n+1`. Sum directly when `g = r`; do not divide by `1-q`. With cash-conversion assumptions fixed, positive discounted cash flows make PE strictly increasing in `g > -1`, supporting bisection. Linking conversion to growth or capital returns changes the problem; do not reuse this monotonicity claim for that different model.

Required boundaries:

- PE uses normalized **base EPS**, not next-year EPS, revenue, EBIT/NOPAT, or enterprise value. For a supplied forward PE, explicitly provide `forward_eps_ratio = EPS1/EPS0`; then `PE0 = forward_PE * forward_eps_ratio`. This ratio is an independently supplied conversion, not the ten-year growth rate being solved. If EPS1 is an explicit forecast path to preserve, use a year-by-year FCFE model rather than assuming the constant-growth result reproduces it.
- Inputs need `EPS0 > 0`, `PE > 0` for inversion, `r > 0`, `h > -1`, and `r > h`. Calculator duration is integer 1–100 years (computational scope, not an investment recommendation). Negative/zero EPS or a distorted cyclical base calls for normalization or another valuation method, not a manufactured positive EPS.
- This bounded calculator accepts `c, ct` in `[0,1]`, not both zero. Real FCFE can be negative or exceed earnings; those cases need explicit financing/investment paths in a fuller model, not clipping. Near-zero terminal spreads can dominate value despite being mathematically valid; show sensitivity rather than treating a positive spread as economic validation.
- FCFE is cash available to common equity after investment and net borrowing; it is not synonymous with dividends or reported net income. Cash-flow timing, EPS and share basis must be consistent. Do not add dividends or buybacks again on top of a value already capturing that distributable cash. If repurchases/dilution drive EPS, model changing shares and funding explicitly outside this fixed-share shortcut.
- No separately added nonoperating assets. If stripping excess cash/investments from price, also reconcile the associated earnings and claims; do not automatically add net cash to a PE model retaining its interest/investment income. Keep currency, ADR/ADS conversion, minority interests and common-equity claims aligned.

## Run The Calculator

Run `python3 invest/scripts/calculate_pe_implied_growth.py /path/to/input.json` from the repository root. It reads one JSON file and prints JSON; it does not fetch data, write an archive or place orders. All six economic fields below are required; none has an economic default. Rates are decimals, multiples are ratios, and price uses the base EPS currency/security unit.

Illustrative inputs, **not company data or recommended assumptions**:

```json
{
  "base_eps": 5,
  "years": 10,
  "cost_of_equity": 0.12,
  "cash_conversion": 0.8,
  "terminal_cash_conversion": 0.9,
  "terminal_growth": 0.03,
  "pe": 20,
  "pe_basis": "base",
  "scenarios": [
    {"name": "lower equity discount", "overrides": {"cost_of_equity": 0.10}},
    {"name": "higher equity discount", "overrides": {"cost_of_equity": 0.14}},
    {"name": "lower cash conversion", "overrides": {"cash_conversion": 0.60}},
    {"name": "shorter duration", "overrides": {"years": 5}}
  ]
}
```

Supply exactly one of `pe` (solve for growth) or `growth` (calculate PE and price). For forward valuation, replace `pe` with e.g. `"growth": 0.08`. For forward-PE inversion, use `"pe_basis": "forward"` plus an explicit positive `"forward_eps_ratio": 1.2`; 20 forward becomes 24 base, not 20 base. `pe_basis` defaults only to the defined base-EPS convention, never to an economic assumption.

Optional `growth_bounds` defaults to `[-0.99, 1.0]`, a numerical search bracket, not a prior/confidence interval. Supply a wider economically relevant bracket if needed. `unbracketed` returns null growth/value and endpoint PEs; it is not proof no solution exists. `not_converged` also withholds a result. The bisection limit is 200 iterations with PE residual tolerance `1e-10 * target_PE`. Invalid/missing/nonfinite inputs exit 2 with no result; never fill missing inputs. Floating-point overflow/underflow requires rescaling or a narrower bracket, not extrapolation.

Optional named `scenarios` override only duration, cost of equity, first/terminal conversion or terminal growth, retaining the same input price hurdle or independently specified forward growth. One-field changes isolate sensitivity; joint changes can test a coherent stress. Every result echoes its effective inputs. These are assumption sensitivities, not confidence intervals; reject invalid scenarios rather than silently dropping them.

With the illustrative base inputs, expected outputs are:

| Check | Result |
|---|---:|
| PE 20 → required annual EPS growth | 13.2382% |
| Terminal share of present value | 57.4853% |
| Independently supported growth 8% → PE | 13.7452 |
| EPS0 5 at that 8% growth → price | 68.7259 |
| PE 20, discount 10% / 14% → growth | 9.2016% / 16.8687% |
| PE 20, conversion 60% → growth | 14.7496% |

These are arithmetic regression examples. Do not cache this table as a universal PE-growth rule. A negative first-stage solution followed by positive terminal growth embeds a recovery; the output flags it, and research must justify it.

## Growth Must Be Funded

High EPS growth and high cash conversion are not two free advantages. Under fixed shares, comparable accounting, a stable financing policy, and growth driven by net equity reinvestment rather than improvement of existing assets:

```text
equity reinvestment rate proxy = 1 - FCFE / net income
required incremental equity return ≈ growth / equity reinvestment rate proxy
```

This is a **conditional consistency diagnostic**, not measured ROE, not ROIC/WACC, and not a universal identity. The example requires about **66.19%** incremental equity return in stage one and **30%** in perpetuity under those premises. That exposes a substantial claim to investigate; it does not prove impossibility. Efficiency gains, intangible investment/accounting, changing leverage or shares may break the proxy. Reconcile the actual mechanism instead of giving such cases an automatic pass or rejection. For zero/near-zero reinvestment (proxy <= `1e-12`) or contraction, the script returns null required return with a reason; positive growth without reinvestment needs another explanation.

## Turn A Hurdle Into Research

For real-company calculations, use [data-contract.md](data-contract.md) for source-backed inputs, timestamps and compatible bases, and retain the calculation inputs/output alongside the analysis. Hypothetical arithmetic uses the skill's direct-calculation exception. No additional database or mandatory ledger is created by this helper.

Compare the solved hurdle with an **independently evidenced** operating path. Use the recent four financial periods and prepared remarks/Q&A to reconcile revenue drivers, net margins, maintenance/growth capex, working capital, funding and diluted shares. When AI/cloud investment is material, link the recent-three-month research/interview evidence to capacity, utilization, pricing, depreciation and cash conversion; do not infer durable EPS growth from headline demand alone. Neither four strong quarters nor management guidance proves decade-long growth or terminal durability.

Deliver only the decision-useful bridge:

1. Price/EPS basis and fixed assumptions → required growth/duration and terminal dependence.
2. Independently supported growth **and cash capacity**, with original evidence and strongest rival → forward value under comparable assumptions.
3. The precise operating gap, its per-share consequence, and what is already in observed dated consensus. A model solution is not observed consensus; shared forward/reverse premises are not independent corroboration.
4. A discriminating metric, economic breakpoint, original source and disclosure window that would reject the gap (e.g. required cash conversion cannot coexist with the capacity spend needed for growth). If unreported, disclose the proxy limit and unresolved conclusion.

Do not turn a valuation gap into a probability, loss ceiling or automatic sizing rule. Cost-of-equity sensitivity, terminal fragility and operating downside still matter. A valid calculation may end with `model-sensitive`, `no demonstrated edge` or `unresolved`; it does not expand trading, monitoring or Notion authority.
