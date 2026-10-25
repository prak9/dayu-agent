# Trace-Based Research Attribution

Use when diagnosing recurring failures, a regression, or diminishing returns from more context, retries, prompting or compute. A trace generates and constrains explanations; it does not by itself identify a cause. Reuse the existing run ledger rather than introducing another mandatory artifact.

## Reconstruct What Was Observable

Attach the relevant run/candidate, model, data, environment and evaluator revisions. Reconstruct only the decisive span: available inputs -> action/tool request -> returned result -> persistent state update -> verifier outcome. Include timestamps/order, artifact IDs and recorded costs where they matter. Preserve raw evidence behind a concise summary.

- Separate facts available at that step from facts discovered afterward; a replay must not silently reveal the answer or later information.
- Trace means observable actions and evidence, not hidden chain-of-thought. A self-explanation is a hypothesis, not privileged access to a cause. Do not reconstruct missing reasoning or expose credentials/private payloads merely to make a trace complete.
- Locate the earliest *observed* divergence from the contract, not automatically the final exception. It may be a symptom of an earlier unobserved fault; state logging gaps explicitly. Missing telemetry is not proof that an event never occurred.
- Compare relevant successes and failures from a declared sampling frame, not only one memorable failure. Match task difficulty, versions and operating conditions where possible; avoid treating repeated steps from one run as independent samples.

## Choose A Discriminating Intervention

Start with the few rival explanations that would change the next action. These lenses are not mutually exclusive or an exhaustive checklist:

| Candidate cause | Cheapest useful probe | Limit on inference |
|---|---|---|
| Required information absent or retrieval failed | Supply verified information available at the original decision time, leaving the task and evaluator fixed | Oracle facts from the future test an upper bound, not a deployable fix |
| Information present but current state lost or misreconstructed | Compare the same facts in ordinary history versus explicit current-state form; test interrupted recovery | A better summary may also change salience or token cost; separate those changes before claiming state is the sole cause |
| Reasoning/planning weak despite correct state | Isolate the failing decision with verified state and the same task constraints | Short-task success does not prove long-task reliability; short-task failure does not identify a particular architectural limit |
| Tool or environment failure | Replay recorded requests in an isolated fixture and inspect authoritative outcomes | A mock cannot establish real-service behavior; never replay a live side effect just to diagnose it |
| Feedback or scorer is misleading | Independently adjudicate raw successful and failed outputs against the original contract | Repair/refreeze the evaluator and rescore both arms; do not credit evaluator changes to the candidate |
| Sampling noise, task mix or resource imbalance | Repeat matched comparisons under fixed budgets and inspect uncertainty and missing runs | More retries can select lucky successes; report all attempts and total cost |

Predeclare what observation would favor each rival, what would weaken it, and the smallest authorized intervention. Patch or ablate one meaningful component when attribution matters; if causes interact, use a small factorial comparison rather than pretending one-variable changes isolate all effects. Deterministic replay helps reproduce a fault; stochastic claims need repeated comparable runs and uncertainty.

Do not infer compute/capacity limits just because more tokens failed, or state loss just because a task was long. When returns flatten, reassess the bottleneck before scaling again. Spend instrumentation effort only where the missing observation can change a decision.

## Close The Attribution, Not Just The Score

Record in the existing run entry: observed divergence and evidence span; competing causes; intervention and controls; result; attribution status (`unresolved`, `supported within tested scope`, or `contradicted`); remaining gaps and next action if needed. Do not invent numerical causal probabilities.

Distinguish three conclusions: the change helped these tasks; evidence supports the proposed mechanism; the benefit transfers to unfamiliar tasks. Each needs its own evidence. A reproducible held-out improvement may be accepted within scope with mechanism unresolved if the risk/guardrails permit; do not demand a complete causal theory for every useful fix or extrapolate it to general intelligence.

Confirm on untouched cases and preserve regressions before promoting a shared rule. Holdout failures become development evidence once inspected; use fresh confirmation for subsequent tuned candidates. Record added reads, calls, retries, latency and human judgment cost alongside quality. A local diagnostic success is not a demonstrated end-to-end gain.
