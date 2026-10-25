# Prediction And Simulation Validation

Use for probability forecasts, stochastic simulators, or predictive-model comparisons where representation or timing carries the claim. Select the relevant sections: probability scores apply to probability outputs, process checks to simulators, and execution checks to decision-value claims. Ordinary arithmetic, isolated point estimates and descriptive reports do not require this protocol.

## Freeze The Forecast Question

Define the target (including event exclusions where relevant), population/selection rule, forecast origin, horizon and resolution source. Separate states known at the forecast origin from future states that must be predicted or integrated over. Record when each feature, derived aggregate and annotation actually became available, not only its row's nominal date.

An attempt-level success probability conditional on a known distance is not a pre-event probability that an opportunity will arise and succeed. Selected completions cannot stand in for all opportunities. Predict actors' actual policies rather than silently replacing them with theoretically optimal behavior. State the dependence assumptions connecting opportunities, choices and outcomes; a product formula is not evidence of independence.

Fit preprocessing, feature selection, hyperparameters and probability calibration only within the training/validation protocol. Match chronological splits to the deployment question; keep related episodes such as one match or overlapping label windows from leaking across folds, with grouping, purge/gaps where needed. Historical aggregates must be as-of the forecast time. A test set used for adaptation is no longer untouched confirmation.

Compare models on the same event, forecast origin, usable information, evaluation population and scoring rule. Start with a relevant historical-rate or simple direct-prediction baseline. A process simulator must earn its extra cost through predictive improvement or a separately requested process capability; do not force a full simulator when a direct model answers the task.

## Test The Input Representation

When encoding or aggregation may limit performance, trace a raw example to the actual model input: which order, elapsed time, quantities, rare events or missingness survive? Use a contrastive pair with the same encoding but different required outputs to expose a lost distinction. Add the smallest relevant feature or state, and test on further cases; neither the pair nor retaining every raw event establishes the best representation.

Preserve actual availability. Distinguish event time, receipt time, aggregate completion and decision time when they differ materially. A complete clock-time bucket is usable after its required events arrive and processing finishes, not at its start timestamp. An event-count bucket likewise depends on its final required event; retain elapsed time where relevant. A partial bucket is a separate representation whose training and runtime semantics must agree. Represent late arrivals and revisions as known then rather than rewriting history with hindsight.

Compare encodings on the same target, source-information cutoff and evaluation population. A fixed model can isolate a local encoding effect; allow comparable tuning budgets when judging the best deployable systems and label joint changes accordingly. An aggregation rule under study is candidate work; correcting look-ahead is evaluator/data repair and requires rescoring both arms under the repaired protocol.

## Match The Horizon To The Decision Clock

Treat horizon, usable independent information, capacity and latency as coupled choices when they affect the task. Longer or shorter horizons have no universal signal-to-noise ranking. Overlapping targets and shared events or factors across entities reduce independent evidence; use a defensible dependence-aware split and uncertainty estimate rather than equating rows with sample size. A changed horizon defines a different target: compare prediction quality within that target, or compare downstream value under a common decision contract.

For time-sensitive value claims, measure data receipt, preprocessing, queueing, inference and action effectiveness along the real critical path. Use each candidate's actual information cutoff and action time; account for deadline misses or signal decay and relevant tail latency under load. Keep quality, cost and timeliness tradeoffs visible until the task selects among them. Offline accuracy and isolated forward-pass speed cannot establish timely value. These checks scale to the task's useful decision window; a long-horizon report need not inherit a trading latency budget.

## Separate Three Claims

| Claim | Evidence required |
|---|---|
| Implementation correctness | Formula/state invariants, boundary tests and reproducible outputs |
| Predictive usefulness | Frozen-pipeline performance against a defensible baseline on unused comparable data, with uncertainty |
| Decision value | Improvement under contemporaneously available prices, costs, constraints and execution conditions |

Passing one level does not pass the next. A prediction-only task can finish with a supported improvement or no demonstrated improvement; it need not discover a profitable strategy. Do not invent historical executable prices or extend the user's authority to satisfy an economic claim.

When attributing downstream value, locate the changed layer: evidence/forecast, target or allocation, action policy, or execution. Compare action policies using the same contemporaneous inputs, upstream targets, constraints and resource budget; compare forecasts with a fixed downstream policy where meaningful. Then check the integrated system, since policy feedback and interactions can change the visited states. A local improvement need not survive integration, and changing several layers together supports a system result rather than unique component attribution.

## Score Probabilities, Not Just Decisions

- Compare proper probability scores such as Brier score or log loss against the baseline, plus calibration/reliability and discrimination/resolution. State clipping or other numerical conventions if used; do not silently repair impossible predictions or invalid probabilities.
- A constant base-rate forecast can be calibrated while providing no discrimination. A lower Brier score does not by itself prove better calibration; it combines several aspects of predictive quality.
- Report sample counts and uncertainty in calibration groups. Select relevant groups before confirmation; post-hoc subgroup discovery needs fresh evidence. Account for clustered or dependent observations rather than treating every row as independent.
- Small perfect samples do not justify probabilities of exactly one. Consider an appropriate prior, shrinkage or partial pooling when supported; no particular algorithm is mandatory.
- A few hand-assigned scenario weights are not an empirically calibrated forecasting system. A single outcome cannot establish whether a probability was calibrated.

## Check The Simulated Process

Before judging a simulator adequate, choose a small set of use-relevant predictive checks: counts, durations, zero-event frequency, dispersion, tails, event ordering, serial dependence and conditional behavior. Compare generated data with observed data on the same basis, not just their means or aggregate payoff.

For trading, matching average P&L can hide wrong trade counts, holding times or loss clustering. Check those paths when they carry the claim. A process check may expose misspecification but cannot prove a unique mechanism; checks against fitting data do not replace held-out prediction evaluation. Keep evaluator repairs separate from candidate improvement and refreeze before comparison.

For action-conditioned simulation, ask which consequences of the candidate's actions the environment actually models. Audit relevant fills, market impact, latency, signal availability/decay and terminal inventory assumptions; perturb the assumptions that could reverse the conclusion. Historical replay may omit reactions to a changed policy. Fresh on-policy trajectories or randomized starts on the same history expand simulated experience, not independent market evidence. Additional exploration can expose a weakness while leaving a shared simulator error intact; separate simulation coverage, unused historical periods and any authorized real-environment validation.

## Separate Uncertainty Sources

| Source | What can address it |
|---|---|
| Monte Carlo sampling error | More effective simulations or appropriate variance reduction under the fixed model |
| Parameter uncertainty | Relevant data, justified shrinkage, parameter/posterior sensitivity with dependence preserved |
| Structural misspecification | Rival mechanisms, boundary cases, predictive checks and fresh evidence |

For independent Bernoulli simulations under fixed parameters, the estimated Monte Carlo standard error is `sqrt(p_hat * (1 - p_hat) / N)`. At `p_hat = 0.5, N = 100000`, it is about 0.158 percentage points. This describes numerical estimation under the model, not real-world probability accuracy. Correlated draws need dependence-aware effective precision; near-zero/one estimates require care rather than claiming zero uncertainty from no observed failures.

Distinguish these estimation errors from inherent outcome randomness, which can remain even under a correct, known model. More simulations are not more independent observations of reality. Arbitrarily chosen input distributions or independence assumptions do not become supported investment probabilities through repeated sampling.

## Handoff

Report the event and information boundary, strongest baseline, unused-data status, relevant score/process checks, dominant uncertainty and supported claim level. Keep unresolved links visible; do not require a positive result, new framework or economic proof to finish a narrower request.
