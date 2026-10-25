# AI Cloud And Compute Investment Costs

Read only when compute/cloud costs, data-center investment or AI infrastructure economics are material to the thesis. This is a diligence lens, not a full checklist for every technology stock. Use the recent research/interview pass in `underwriting-loop.md`; keep changing prices and industry estimates in the dated research artifact, not as permanent Skill constants.

## Define Whose Economics And Which Unit

Separate the chip supplier, facility/power owner, GPU cloud operator, model lab and end customer. A customer's rental bill is an operator's revenue, not the operator's hardware purchase cost. Hyperscaler segment margins are not stand-alone AI margins. State hardware generation, location, vintage, workload, contract duration, currency and period. Training, inference and idle capacity have different cost/performance profiles.

Distinguish announced/nameplate power, contracted power, energized IT capacity, service-ready GPUs, billable/reserved capacity and actual useful compute. Customer take-or-pay terms can decouple billing from physical use. Model FLOP utilization (MFU), uptime, scheduler occupancy and paid utilization are not interchangeable; multiply separate factors only when denominators and conditional relationships justify it. Aggregate capex divided by announced GW is not automatically the cost of a productive MW.

## Investigate The Cost Lines That Can Change Value

| Layer | Drill-down | Original evidence to seek |
|---|---|---|
| Installed capital and delivery | GPU/CPU/HBM servers, networking, storage, racks, land/buildings, cooling/electrical fit-out, commissioning, deposits, taxes and construction delays | Asset and capex footnotes; OEM/contractor quotes with scope; acceptance and project milestones; cash paid versus accrued additions |
| Power and availability | Delivered tariff including demand charges, load-weighted power, PUE, cooling/water, grid connection, firm fuel, on-site generation, backup and maintenance | Utility tariff or contract, permits and energization record, measured workload/site data; not device TDP or an OEM efficiency claim alone |
| Realized revenue and work | GPU-hour price after discounts/credits, reservation/spot mix, deployment ramp, idle or failed jobs, networking bottlenecks, customer concentration and renewals | Actual contract/invoice, customer/operator evidence, measured workload goodput and SLA; public list price is not a realized transaction |
| Asset economics | Book depreciation, economic useful life, repair/replacement, residual/redeployment value, price/performance erosion of older generations | Accounting policy plus renewal/resale and reliability evidence for the specific vintage; architecture launch date is not that asset's installation date |
| Funding and cash | Debt rates/fees/amortization, leases, capitalized interest, customer prepayments, collateral and refinancing; build-before-revenue funding gap | Debt/lease and cash-flow notes, payment schedules and capacity-delivery conditions; backlog is not cash collected |
| Operating service | Software, engineering/support, security, bandwidth/egress, storage, sales and ongoing site overhead | Cost allocation, service contracts and workload measurements; distinguish allocation from incremental avoidable cost |

Use operator/customer technical interviews to explain a discrepancy, not replace contract or financial evidence. Separate speaker estimates, sponsored benchmarks and reported measurements. Cross-check the hardware bill with project scope and financial additions; explain ranges and residuals instead of forcing a perfect reconciliation from incompatible data.

## Keep Three Models Separate

1. **Provider accounting bridge:** revenue -> cash operating costs -> EBITDA -> depreciation/amortization -> EBIT -> interest/tax. Disclose adjustments. Extending book life can change depreciation and earnings; by itself it does not improve EBITDA, undo cash capex or establish a longer economic life. Model aging fleet price, costs and availability rather than a universal four- or six-year replacement rule.
2. **Provider project/shareholder cash:** date equipment and construction payments, lease obligations, working capital/prepayments, receipts, replacement and residual value. Use unlevered project cash with an appropriate capital cost, or levered equity cash after financing flows with an equity return requirement. Do not double-charge capex and depreciation, owned equipment and rental expense for the same asset, or financing cost in both cash flows and an incompatible discount rate. Reconcile capitalized interest with its actual payment timing.
3. **Customer effective TCO:** relate the bill plus integration, storage/network, support and failure/rework cost to useful work at comparable output quality, latency and reliability. Cost per reserved GPU-hour, billed GPU-hour, successful training run and million served tokens answer different questions. Do not treat peak FLOPs or an unqualified vendor benchmark as delivered useful output; avoid charging downtime both as extra paid time and again as the same loss surcharge.

For a simple metered provider with one uniform price and variable cost, a diagnostic break-even is:

```text
billable hours = service-ready GPUs * period hours * billed utilization
revenue = billable hours * realized price per GPU-hour
profit = billable hours * (price - variable cost per billed hour) - fixed costs
break-even billed utilization = fixed costs / [GPUs * period hours * (price - variable cost)]
```

State which fixed costs are included: cash operating, EBIT, pre-tax or debt-service break-even are different thresholds. This formula assumes positive contribution per billed hour and a stable cost/price basis; nonpositive contribution, a threshold above 100%, ramping inventory or take-or-pay contracts require a different interpretation/model. Do not multiply metered revenue by MFU. Missing realized prices, vintage data or cost terms permit conditional bounds, not a fabricated point estimate.

Connect the decisive cost range to FCF/per-share value and the current price hurdle. Stress joint price/utilization, energization delay, renewal, replacement and funding changes where relevant. Derive falsifiers from observable contract prices, accepted capacity, cash cost or cash collection—not from total AI spending, a popular interview or an arbitrary industry utilization threshold.
