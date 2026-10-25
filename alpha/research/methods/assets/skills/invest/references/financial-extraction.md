# Structured Financial Extraction: U.S., Hong Kong And A-Shares

Use for requested filing extraction or material statement inputs to research. Read the common rules and only the applicable market branch. For a dual-listed issuer, both may be needed to reconcile documents; two listings do not create two sets of consolidated earnings. This module structures evidence, not an investment verdict. Use [financial-evidence.md](financial-evidence.md) for original-source verification and [data-contract.md](data-contract.md) for calculations.

## Three Layers, One Evidence Chain

Keep these distinguishable in a compact table, JSON or the existing model, according to the requested output:

- **Original evidence:** issuer identity; original document ID/URL, type, language, publication time/precision, revision, audit/review status; row label or concept, table, column headers, printed/PDF page, unit/scale, sign and material notes. Retain raw text/value before normalization. Do not call unaudited results audited because an auditor agreed figures to an underlying statement.
- **Normalized facts and calculations:** metric ID, actual period dates, instant versus duration, fiscal-year label and reporting cadence; currency/scale, accounting standard and adjustments; consolidated/segment scope, continuing operations, ownership attribution and security basis. Keep reported and derived values distinguishable, with formulas and source metric IDs for derivations. Missing is not zero; a dash requires its table convention to be understood.
- **Research interpretation:** what the change may mean, plausible rival explanations and missing evidence. Do not insert interpretation into a reported field or label an analyst estimate as management guidance.

Do not extract every line by default. Cover the requested statements/periods and load-bearing operating detail; report what is missing, incomparable, derived or only partially read. Extraction completeness and economic correctness are separate judgments.

## Common Comparability And Derivation Rules

**Document/version identity.** Build a small inventory of the relevant earnings announcement, full report, presentation, call and amendment. Link complementary documents by economic period. Repeated comparative columns, translations and duplicate exchange/IR copies are not new observations. Keep original and restated versions separately, identify what changed and use a consistent basis for comparisons. A latest amended number must not replace a historical input before that amendment was available. Different filing IDs need not mean different accounting bases; a shared version basis must be established from the disclosures, not invented to pass validation.

**Periods.** Use fiscal start/end dates, not upload date, calendar-quarter guesses or labels alone. Preserve both single-quarter and year-to-date columns where present. For additive flows on a reconciled basis, Q3 = nine months minus six months; Q4 = full year minus nine months; H2 = full year minus H1. Keep inputs and formula and label the result derived. Do not manufacture Q1/Q2 from H1, or Q3/Q4 from H2. Balance-sheet amounts are instants. EPS, margins, customer counts, retention rates and weighted-average shares cannot be mechanically differenced like cash flow. Compute ratios from comparable underlying amounts when supported; differences in cumulative diluted EPS are not reliable standalone quarterly EPS. Preserve 52/53-week and unequal-duration comparisons explicitly.

**Currency and ownership.** Report currency is not trading currency. Distinguish consolidated net income, profit attributable to owners/common shareholders and non-controlling interests. Retain basic versus diluted EPS, weighted-average versus period-end shares, and ordinary shares versus ADS. For an explicitly verified ratio of one ADS to N ordinary shares, EPS per ADS = N × ordinary-share EPS on the same basis; equivalent underlying ordinary shares = N × ADS count. Do not add equivalent dual-listed shares twice. Verify the ratio's effective date and splits; leave a missing ratio unresolved. Currency conversion needs a dated rate, direction and appropriate balance/flow context, not a silent spot conversion of historical statements.

**Adjustments.** Keep US GAAP, IFRS/HKFRS or another disclosed standard explicit; listing venue alone does not establish the standard. Preserve statutory and non-GAAP/non-IFRS values separately and extract the issuer's reconciliation when material. FCF and adjusted earnings definitions differ: show capex, capitalized software, leases, tax and SBC treatment rather than mapping identical labels to identical economics. Do not force banks/insurers into an industrial cash-flow template.

**Checks proportional to the output.** Reconcile assets with liabilities and equity; opening/closing cash with operating, investing, financing, FX and other disclosed movements; consolidated totals with segments plus eliminations/unallocated items; and adjusted figures with their reconciliation. Respect signs, rounding, restricted-cash definitions and changing segment scope. The existing sum checks can test prepared, same-basis identities; they do not discover missing components. Use v2 `period_differences` for explicit cumulative-flow derivations. Other mappings, ADS ratios and version selection still need source inspection; a script pass is not that inspection.

## U.S. Branch

Resolve issuer identity/CIK and filing history first. For relevant domestic issuers, distinguish 10-K/10-Q statements from earnings-release exhibits to 8-K and amendments. For foreign private issuers, inspect the applicable 20-F/40-F annual disclosure and 6-K attachments; not every 6-K is an earnings report, and U.S. listing does not imply quarterly 10-Q reporting or US GAAP.

When available, use SEC structured data/iXBRL to locate facts, then verify the material table and notes. Retain accession, taxonomy/concept, unit, duration/instant and dimensions from the actual filing context. Standard-concept aggregate APIs are not complete segment/KPI or custom-tag extraction. Do not select the last returned value blindly: repeated filings may contain the same period, amended comparatives or different durations. SEC calendar frames are not a substitute for an issuer-specific fiscal series. Use filing HTML/iXBRL tables and IR originals where aggregate data omits the required scope; never invent a missing custom tag.

For calls, use [earnings-transcripts.md](earnings-transcripts.md) to link prepared remarks and complete question/answer exchanges to their actual earnings period.

## Hong Kong Branch

Resolve issuer, stock code, board and reporting cadence from HKEXnews and issuer IR. Match annual/interim results announcements to the subsequent full reports. Use the actual disclosures rather than imposing quarterly financial statements: quarterly operating updates may contain only revenue or sales KPIs, not a full income statement or cash flow. Annual less interim can support a derived second half on a consistent basis, not two invented quarters.

Keep Chinese/English versions linked as versions of one disclosure. Extract original row names as well as normalized names; language or OCR differences should not create new metrics. Verify units such as 元/千元/百万元/亿元 and whether parentheses denote negatives. For image-only tables, use the [PDF fallback](pdf-retrieval.md), inspect headers and relevant footnotes visually, and preserve uncertainty for unreadable cells instead of filling them from neighboring rows.

Retain disclosed accounting standard, reporting currency, profit attribution, share classes and material related-party/associate/joint-venture scope. Revenue from associates is not automatically consolidated revenue. Segment reorganizations need the issuer's restated comparison or an explicit break in series. Profit alerts, trading updates and management outlook are not replacements for subsequently reported statements.

## A-Share Branch

Resolve legal issuer, stock code and exchange (Shanghai, Shenzhen or Beijing); distinguish similarly named entities and A/H share classes. Retrieve original exchange disclosures, CNINFO or issuer-published documents rather than relying on a finance portal's normalized table. Associate the full annual/interim/quarterly report with its summary, correction and relevant attachments. Preserve the actual disclosure date and audit status. Verify current filing requirements separately if asked about compliance; this is not a deadline checklist.

Keep `业绩预告` (forecast range), `业绩快报` (preliminary result), formal reported results and subsequent corrections as separate dated evidence states. A preliminary historical result is not automatically a forecast, but its document type/status must remain visible; a forecast midpoint is a derived assumption, not a reported fact. Reconcile later changes without overwriting what was available earlier. Do not infer withdrawal of a forecast from its omission in a later document.

Read the actual column headers: `本报告期`, `年初至报告期末`, `上年同期`, and `期末` may describe different windows within the same quarterly report. Derive Q2 from H1 minus Q1, Q3 from nine months minus H1, and Q4 from year minus nine months only for comparable additive flows with cited inputs. Preserve single-quarter disclosures separately from calculated values. Apply the common prohibition on mechanically subtracting cumulative EPS, ratios or balance-sheet stocks.

Separate **合并** from **母公司** statements throughout the income, balance-sheet and cash-flow series. Separate consolidated net profit, profit attributable to parent owners (`归母净利润`) and the issuer's disclosed `扣非归母净利润`. Retain the non-recurring-items reconciliation, tax and minority-interest effects where material; deducting a pretax item from after-tax attributable profit is not a valid reconciliation. Recurring cash generation is a research judgment, not a synonym for `扣非`. Keep reported accounting standard and adjustments rather than treating A/H reports as automatically interchangeable.

For material cash-quality questions, inspect the notes connecting `货币资金` to cash equivalents and restricted deposits; receivables, notes receivable, receivables financing, factoring/derecognition and recourse; contract assets/liabilities, inventory and impairments; development expenditure and capitalized R&D. These are possible distinctions, not allegations or a checklist for every company. Do not call all monetary funds spendable, all receivables financing cash, or reduced receivables proof of customer collection. Cross-check capital expenditure with relevant cash-flow lines and asset notes rather than assuming one line captures all investment.

Keep period-end share capital, weighted-average shares and basic/diluted EPS distinct. Preserve effective dates and restated comparatives for bonus shares, capitalization issues, repurchases, issuance and convertibles; do not apply a current share count retroactively without a justified bridge. Units such as 元、万元、亿元 and negative parentheses must follow the table, not the portal default.

Use the existing contract: encode consolidated/parent scope and profit/adjustment attribution explicitly in `basis` for flat v1 sums/basis checks, and use matching `statement.scope`, `concept` and version fields for v2 period differences. Automated equality checks cannot infer scope from a Chinese row label. Do not imply a new A-share parser exists: source selection, forecast/preliminary/final classification and note interpretation still require original-document checks.

## Operating Information Beyond Three Statements

For decision-relevant segments, customers, backlog/orders, retention, pricing, capex and management guidance, retain: original definition; value/range or exact qualitative qualification; population/scope; actual observation period or forecast horizon; source/speaker; and changes from the prior comparable disclosure. Record a KPI as missing/not disclosed only after the applicable material has been checked; inaccessible is a different state. Preserve guidance conditions, withdrawn/redefined metrics and explanatory notes. Do not turn backlog into guaranteed revenue, bookings into cash, or management's causal explanation into an established fact.

For a financial update, carry comparable extracted facts into the existing four-period comparison and anomaly investigation. For extraction only, stop with the requested data, sources, derivations and limitations; no forced target price or new persistent database.

## Primary References

- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces): aggregate API coverage and calendar-frame limits.
- [SEC Form 6-K](https://www.sec.gov/about/forms/form6-k.pdf): foreign-issuer current information, not a universal quarterly report.
- [HKEX issuer disclosure guidance](https://www.hkex.com.hk/Listing/Explore-By-Role/Listed-Issuers/Equity-Securities?sc_lang=en) and [HKEXnews report search](https://www1.hkexnews.hk/search/predefineddoc.xhtml): identify actual report types and publication records. Verify current requirements when the task concerns filing compliance; do not infer them from this extraction guide.
