# Material Investment Data Contract

Use this contract when linked calculations depend on three or more material numbers, when rebuilding a model, or when reconstructing a historical decision. A Quick memo may show the same fields in a compact table; do not force a JSON artifact when no calculation depends on it.

The contract prevents unknown values from becoming zero, estimates from becoming facts, incompatible bases from being added, and later information from leaking into a historical view. It does not prove that a source supports a number; compare every material claim with the cited original passage.

Maintain two different checks: **input integrity** (this schema and calculator) and **underwriting support** (why a premise/range is justified and whether it supports the inference). For a load-bearing analyst assumption, retain its derivation, supporting observations/reference class, range and failure condition in the model or memo. `source.reference` pointing to that model is not independent support for its growth or margin. A validator pass, a large metric count or reproducible DCF cannot be presented as proof of investment depth or forecast reliability. These semantic checks do not add required JSON fields or change the v1 schema.

For extracted filings, preserve original row/concept, period/dimensions, scale and qualifiers in the existing source locator or companion evidence record; retain raw and normalized values with the conversion bridge. Use [financial-evidence.md](financial-evidence.md) for grounding or a source dispute. Do not replace original-document evidence with a parser confidence score, and do not treat a missing extraction field as an economic zero. This does not change the v1 interface.

## Metric record

Each material number is one item in `metrics`:

```json
{
  "id": "revenue_fy2025",
  "name": "Revenue",
  "value": 1250.0,
  "unit": "USD million",
  "currency": "USD",
  "period": "FY2025 ended 2025-12-31",
  "basis": "GAAP; continuing operations",
  "classification": "reported_fact",
  "source": {
    "reference": "https://example.com/10-k",
    "document_type": "10-K",
    "published_at": "2026-02-20T13:00:00Z",
    "available_at": "2026-02-20T13:02:00Z",
    "locator": "p. 42"
  },
  "missing_reason": null
}
```

Required semantics:

- `value` is a finite number or `null`. Zero is a measured value; unknown is `null` plus a non-empty `missing_reason`.
- `unit`, `currency`, `period`, and `basis` make the accounting and temporal basis explicit. `currency` may be explicit `null` for ratios, counts, or probabilities.
- `classification` is exactly one of `reported_fact`, `management_guidance`, `consensus`, or `analyst_assumption`. Do not disguise a forecast as a filing fact.
- `source.reference` identifies the original document or a clearly named analyst-model artifact. Record `document_type`, publication and availability timestamps with time zones when known, and a page/section `locator` when available; use explicit `null` when no stable locator exists. v1 requires exact timestamps; use v2 below when only a bounded date or unknown time is supported, never fabricate precision to satisfy v1.
- `available_at` is the first time the decision-maker could actually have used the item, which may be later than the document's nominal `published_at`.

## File and checks

```json
{
  "schema_version": 1,
  "as_of": "2026-09-05T10:00:00+08:00",
  "decision_time": "2026-09-05T10:00:00+08:00",
  "metrics": [],
  "checks": {
    "sums": [
      {"name": "segments to revenue", "components": ["segment_a", "segment_b"], "total": "revenue", "tolerance": 0.001}
    ],
    "growth_rates": [
      {"name": "revenue growth", "prior": "revenue_prior", "current": "revenue", "expected": 0.25, "tolerance": 0.001}
    ],
    "probability_groups": [
      {"name": "scenario probabilities", "items": ["bull_p", "base_p", "bear_p"], "target": 1.0, "tolerance": 0.001}
    ],
    "basis_groups": [
      {"name": "margin inputs", "items": ["gross_profit", "revenue"], "fields": ["unit", "currency", "period", "basis"]}
    ]
  }
}
```

- `decision_time` activates point-in-time validation. Any `available_at` later than it is a failure and cannot be backfilled into the historical judgment.
- Sum checks require the same unit, currency, period, and basis before arithmetic.
- Growth checks require the same unit, currency, and basis, a non-zero prior value, and a decimal expected growth rate.
- Probability values must each lie in `[0, 1]` and sum to the configured target.
- Basis groups explicitly require selected fields—unit, currency, period, basis, or classification—to match before linked calculations use them.

Run:

```bash
python -m alpha_invest validate_data path/to/data-contract.json
```

For compatibility, exit code `0` means that a JSON report was produced, even when its `status` is `fail`. Automation must parse the JSON and require `status == "pass"`; checking the process exit code alone does not validate the data. File/JSON loading errors still exit nonzero.

Treat every finding as a model-input issue to resolve or expose. The validator's two explicit limits remain in force: timestamps only validate the recorded evidence set, and arithmetic consistency cannot establish source support, economic comparability, or forecast quality.

## Opt-In v2: Time Precision And Cumulative Flows

Existing v1 records and checks remain supported. Set `schema_version: 2` for the following extensions; all other required metric fields and classifications remain unchanged. This is not a requirement to migrate old memos or turn every quick calculation into JSON.

### Source Time Without Invented Precision

Each of `published_at` and `available_at` accepts an exact zoned timestamp, or a justified inclusive bound:

```json
{"earliest":"2026-09-01T00:00:00+08:00","latest":"2026-09-02T00:00:00+08:00","reason":"Original record shows only the Hong Kong publication date"}
```

For a date-only source, next midnight is a conservative upper bound, not a claimed release time. Use the source's verified timezone; if neither timezone nor usable bounds can be established, use explicit `null` and `source.time_missing_reason`. A missing key or malformed bound is invalid. Do not infer actual publication from a retrieval time. A verified retrieval can establish an availability upper bound, not an invented first-publication timestamp.

Unknown times produce warnings without a historical cutoff. With `decision_time`, both source-time upper bounds must be at or before the cutoff; overlap with the cutoff or unknown time yields `point_in_time_unresolved` and status `fail`, and a definitely later source yields `point_in_time_violation`. Definite availability before publication is invalid. Overlapping bounds cannot prove the exact chronological order. A nonhistorical `pass` with warnings is not a point-in-time certification.

### Cumulative Flow Derivation

For metrics participating in a `period_differences` check, attach structured `statement` context alongside the human-readable `period` and `basis`:

```json
{
  "concept":"operating_cash_flow",
  "kind":"flow",
  "start":"2025-01-01",
  "end":"2025-09-30",
  "scope":"consolidated; continuing operations",
  "accounting_standard":"US-GAAP",
  "version_basis":"original-unrestated; compared notes verified",
  "security_basis":"not_applicable"
}
```

Other economic kinds include `instant`, `ratio`, `per_share`, and `weighted_average`; they cannot be used in this subtraction check. `concept` identifies the same economic metric across inputs, not an arbitrary common label. Match unit, currency, basis, classification, concept, scope, accounting standard, version basis and security basis. The two cumulative intervals must share a start, with the earlier ending before the later. The result starts the day after the earlier end and ends with the later interval. A script cannot establish whether periods were mislabeled or the source supports the chosen common basis.

For existing metric IDs, declare:

```json
{"period_differences":[{"cumulative":"ocf_9m","prior_cumulative":"ocf_6m","result":"ocf_q3","tolerance":0.001}]}
```

Put this object inside `checks`. The result metric must retain `derivation: {"operation":"subtract","inputs":["ocf_9m","ocf_6m"]}`. Reported-fact inputs can support a derived historical value with the same classification, but the output must remain labeled **derived**, not directly disclosed. Cite both input sources through their IDs; use a named calculation artifact/locator for the result, and never date its availability earlier than its latest input. Do not describe EPS or balance-sheet subtraction as a derived quarterly flow. Unknown inputs cannot pass the check.

The script validates these contexts only for declared period-difference checks; it does not automatically discover all derivations, version conflicts, duplicate translations, ADS ratios, or financial identities. Use the [extraction guide](financial-extraction.md) for those source-level decisions. The original sums/basis checks still use the original flat fields; do not assume merely attaching `statement` metadata changes their behavior. Add appropriate same-basis checks and inspect original evidence before calling a series comparable.
