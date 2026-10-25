# Mode C — GF-DMA Module Diagnostics

Use for explicit GF-DMA, DMA/ATR trend health, price-to-DMA divergence or EscapeRatio requests, or when company research discovers a material price/fundamental divergence that this diagnostic could clarify. Do not trigger from a bare ticker or generic stock-analysis request alone. State the question and check data availability; qualitative interpretation is valid when numeric gates are not met.

GF-DMA is an **uncalibrated heuristic**, not a return probability or causal model. Report its version, source dates, inputs, missing modules, and sensitivity. Never let the model improvise a numeric module score: use [scripts/calculate_gf_dma.py](../../../alpha_invest/gf_dma.py), or return qualitative module observations / `N/A` when the required inputs or gates are missing. The aggregate score is disabled even when all module inputs exist.

## Units And Windows

All rates and divergences are decimals (`0.10` means 10%); scores are 0–100.

- `fundamental_speed_63d`: expected fundamental growth over a normalized 63-trading-day horizon. Derive revenue, gross-profit, and EPS growth on the same comparable basis, then apply the weights below. Do not mix YoY, sequential, and annualized values without first converting them to one horizon; seasonal or sign-changing comparisons are invalid.
- `dma_speeds_63d[x] = (SMA_x(t) / SMA_x(t-k) - 1) * (63/k)`, with the same `k` (normally 5 or 10 trading days) for all DMAs.
- `dX = price / SMA_X - 1` for X = 20, 50, 100, 200.
- `z20 = (price - SMA20) / ATR20`; price, SMA, and ATR must use the same currency and adjusted-price basis, and ATR20 must be positive.
- `price_daily_slope_5d = (price_t / price_t-5 - 1) / 5` and `dma50_daily_slope_5d = (SMA50_t / SMA50_t-5 - 1) / 5`.
- `revenue_30d` and `eps_30d` are 30-calendar-day changes in the same forward consensus estimate; `guide_vs_consensus` is guidance midpoint / pre-release consensus - 1.

For positive prices and SMAs, every `dX` must be strictly greater than `-1`, and each normalized five-day daily slope must be strictly greater than `-0.2`. `d20` and `z20` must share the same sign, including zero, because their denominators are positive. The calculator returns a null module score with a reason for violations; present it as `N/A`. These checks cannot detect every percentage/decimal mix-up or verify adjustment basis: use decimal inputs and retain source prices, SMAs, ATR, and windows for verification. Do not impose a guessed growth/revision domain when its required window or sign basis is unavailable.

Record whether prices are split-adjusted, which consensus period is used, the time zone/as-of timestamp, `k`, and any fallback. If comparable history is unavailable, do not guess.

## Fundamental Speed

```text
G_f = 0.35*G_Revenue + 0.25*G_GrossProfit + 0.30*G_EPS + 0.10*G_Revision
```

Fallbacks: gross profit missing → `0.5*G_Revenue + 0.5*G_EPS`; EPS missing → `0.5*G_Revenue + 0.5*G_GrossProfit`; only comparable revenue available → `G_Revenue`. A component crossing zero, a seasonal mismatch, or `G_f <= 0.01` fails the GrowthMatch gate.

## Deterministic Module Mappings (`gf-dma-v1`)

The calculator uses clamped piecewise-linear interpolation between the listed anchors. These thresholds are hypotheses to calibrate on point-in-time data, not universal market laws.

### `S_GrowthMatch`

Compute `R_x = G_DMAx / G_f` for both 50DMA and 100DMA, then use their median. Require finite `G_f > 0.01` and both 50/100DMA speeds.

| Median R | Score anchor | Interpretation |
|---:|---:|---|
| -1.0 | 10 | price trend contradicts positive fundamentals |
| 0.0 | 35 | no price confirmation |
| 0.5 | 75 | under-reflected |
| 0.8 | 90 | entering healthy range |
| 1.0 | 100 | matched |
| 1.3 | 90 | upper healthy range |
| 2.0 | 60 | hot |
| 2.5 | 35 | escape risk |
| 4.0 | 10 | extreme escape |

### `S_Divergence`

Require all `d20`, `d50`, `d100`, `d200`, `z20`, plus the two boolean gates `fundamentals_stable_or_improving` and `revisions_nonnegative`.

Start at 90 and apply:

- `d20`: no penalty through 5%; interpolate penalty 0→15 at 5%→12%, 15→35 at 12%→20%, then add up to 25 more points by 40%.
- add up to 20 points of penalty for `d50 > 30%`, up to 15 for `d100 > 50%`, and up to 10 for `d200 > 100%`.
- `z20`: no penalty through 2; penalty 10 at 3, 20 at 4, and 35 at or above 5, linearly interpolated.
- stable/improving fundamentals and nonnegative revisions add 5 for either a mild pullback below 20DMA while at/above 50DMA, or a 0%–15% pullback below 50DMA while still above 100/200DMA.
- if either fundamental gate is false, subtract up to 25 for being below 50DMA, 20 for below 100DMA, and 25 for below 200DMA. A falling price is not “cheap” merely because divergence is negative.

Clamp the result to 0–100.

### `S_Parallel`

Compute `EscapeRatio = price_daily_slope_5d / dma50_daily_slope_5d`. If the 50DMA slope is within `±0.00001` per day, return `N/A`. If the 50DMA slope is negative, return `N/A`; two negative slopes must never produce a healthy positive ratio.

| EscapeRatio | Score anchor |
|---:|---:|
| -1.0 | 10 |
| 0.0 | 30 |
| 0.5 | 60 |
| 0.8 | 85 |
| 1.0 | 100 |
| 1.2 | 90 |
| 1.8 | 65 |
| 2.5 | 35 |
| 4.0 | 10 |

### `S_Revision`

Require at least two finite values among revenue revision, EPS revision, and guide-versus-consensus; use their median.

| Median revision | Score anchor |
|---:|---:|
| -10% | 10 |
| -5% | 35 |
| 0% | 60 |
| +5% | 85 |
| +10% | 100 |

## Aggregate Status

`HealthScore` and the named aggregate state are currently always `N/A`. The module mappings remain useful as inspectable diagnostics, but their joint weights, effective domains, and state boundaries have not passed point-in-time holdout calibration. Do not average available modules, renormalize missing modules, or reconstruct the retired aggregate formula from an older memo.

An aggregate may be restored only under a new explicit parameter version after documenting the calibration sample, holdout period, asset universe, missing-data policy, weights, state boundaries, and sensitivity. Until then, report which modules are available, their versioned outputs, failed gates, and how the observations affect the investment question qualitatively.

## Output

```markdown
# [Ticker] — GF-DMA Modules (`gf-dma-v1`)
- Aggregate score/state: N/A; list failed gates and available modules
- As-of timestamps, source set, units, k, and adjustment basis

## Fundamental Speed And Growth Match
## Price/DMA/ATR Divergence
## Parallelism And EscapeRatio
## Revision Confirmation
## Aggregate Disabled, Interpretation, And Limits
## Data Needed For A Valid Recalculation
```
