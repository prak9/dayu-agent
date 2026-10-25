# Approximately One-Year Option-Implied Price Distribution

Use this method when the user asks what current options imply about the stock price roughly one year ahead, and as a default market-expectations check in stock-opportunity research when reliable data are accessible. It answers a pricing question, not “what will the stock probably do?”

## Object And Interpretation

European option prices encode discounted **risk-neutral** state prices. For a call price `C(K,T)` at strike `K` and expiry `T`:

```text
Q(S_T > K) = -exp(rT) * dC/dK
```

The second strike derivative gives the risk-neutral density under regularity assumptions. With discrete strikes, a call spread estimates the tail probability at the midpoint:

```text
Q(S_T > (K_i + K_{i+1})/2)
  ~= exp(rT) * (C(K_i)-C(K_{i+1})) / (K_{i+1}-K_i)
```

These are probabilities under the pricing measure. They include risk premia, crash-insurance demand, dealer positioning, liquidity and model/market frictions. They are not observed consensus, physical probabilities, fundamental scenario weights or personalized odds. Compare the distribution with independently built operating scenarios; do not replace those scenarios with it.

## Data And Expiry

Use the listed expiry closest to 365 calendar days from the extraction time, and report its actual days to expiry. Prefer an expiry in roughly the 9–15 month range; outside it, label the horizon mismatch rather than calling it one year. Record:

- underlying/security, spot, quote timestamp and exchange/session;
- expiration, exercise/settlement style, multiplier and known corporate-action adjustments;
- strike-level bid, ask, last, volume and open interest;
- continuously compounded risk-free rate matched to expiry, and the source/time of every input;
- whether prices are raw, midpoint, vendor-fitted, or converted to European-equivalent values.

Use synchronized quotes. Exclude crossed, stale, zero-bid or implausibly wide markets according to an explicit rule, but do not hide how much of the surface this removes. Use put-call parity and the forward where possible to diagnose dividend/borrow and quote problems. A single at-the-money implied volatility cannot recover a strike distribution.

U.S. single-stock options are generally American style. Raw American call prices do not satisfy the European derivative identity exactly, especially around dividends or hard-to-borrow names. Use a reputable European-equivalent/arbitrage-free surface or an explicit early-exercise adjustment. If that cannot be obtained and the distortion could matter, do not present precise probabilities.

## Estimation And Validation

Prefer a documented arbitrage-free surface fitted jointly to reliable calls and puts. The bundled calculator is deliberately narrower: it converts cleaned European or European-equivalent call prices into adjacent-strike tail and interval probabilities without smoothing or extrapolating.

Before reporting, require calls to be nonnegative and decreasing in strike, and the call curve to be convex. The resulting tail probabilities must lie in `[0,1]` and decline as the threshold rises. Violations indicate quote noise, timing mismatch, American-exercise effects or a bad fit. Do not silently clip, monotonize or renormalize material violations; repair the inputs or mark the estimate unreliable.

Do not extrapolate unobserved tails into a claim about all possible prices. The first and last open-ended buckets show probability mass outside the usable strike range, not its internal shape. Sparse strikes produce coarse buckets. Repeat the estimate with bid/mid/ask or reasonable surface variants when spreads are material; report a range if the conclusion moves.

Run the deterministic extraction from the repository root:

```bash
python3 invest/scripts/calculate_option_implied_distribution.py /path/to/input.json
```

Input example:

```json
{
  "quote_timestamp": "2026-10-11T16:00:00-04:00",
  "expiration": "2027-10-15",
  "spot": 100.0,
  "risk_free_rate": 0.04,
  "option_style": "european_equivalent",
  "price_basis": "arbitrage_free_mid_fit",
  "calls": [
    {"strike": 80, "call_price": 25.0},
    {"strike": 100, "call_price": 13.0},
    {"strike": 120, "call_price": 5.0}
  ]
}
```

Rates are decimals and continuously compounded; `quote_timestamp` must include a timezone. The script sorts strikes, derives actual/365.25 time from the quote date, rejects duplicate strikes and material no-arbitrage violations, and emits strict JSON. It fetches no market data, performs no American-option conversion and does not infer missing tails.

## Deliverable

Show the extraction timestamp, expiry and days to expiry before the probabilities. Use a compact table such as:

| Terminal threshold/range | Risk-neutral probability | Evidence quality |
|---|---:|---|
| `S_T <= 90` | … | strike spacing / spread note |
| `S_T > 100` | … | interpolated only if a supported surface permits it |
| `90 < S_T <= 110` | … | adjacent call spreads |

Give both price levels and returns from current spot. Include only thresholds supported by the fitted surface; “each price” means a disclosed strike/grid resolution, not false point-by-point precision. End with:

1. what the options surface prices relative to the fundamental scenarios;
2. whether the difference could reflect risk premium or liquidity rather than belief;
3. the strongest data-quality limitation;
4. what later option or operating evidence would resolve the disagreement.

If reliable inputs are unavailable, write `期权隐含分布不可可靠估计`, identify the missing or failed condition, and continue the rest of the research. Do not substitute a lognormal distribution derived from one implied volatility unless the user explicitly requests that hypothetical model; label it a model sensitivity, not the observed option-implied distribution.
