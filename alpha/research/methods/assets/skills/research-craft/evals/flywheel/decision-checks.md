# Completion, History And Perturbation Checks

The v3 pilot adds a synthetic decision contract to the existing artifact runner.
It classifies next actions; it never publishes, trades or trains a model.
decision-input.json（原方法的历史样例，不随 alpha 分发） declares the task and eight observations.
The quality threshold of 80 belongs only to this fixture, not to any Skill's
general acceptance policy. Required item identities, exposure history and
publication authority are explicit; optional deferred work stays optional.

| Check | Positive and negative observations |
|---|---|
| Completion | Complete work, a higher score with a missing required item, allowed deferral, and completed but below-threshold quality |
| History | Equal latest scores after fresh confirmation versus tuning on that same confirmation data |
| Irrelevant change | Equal facts with a different label or reordered unordered item sets |
| Meaningful boundary | Equal quality and completion with publication authorized versus local-only authority |

`candidate.py` implements a reference rule and four deliberate mutants:
score-only, history-blind, wording-sensitive and boundary-blind. These are
constructed controls, not discovered improvements or model responses.
`grader.py` checks captured actions against an independently specified expected
map, validates the complete unique observation inventory, and emits each named
criterion separately. It checks individual actions as well as pair relations:
always doing nothing cannot pass merely by looking stable. All criteria are
required, so a completion failure remains a failure despite high quality.

## Reproduce

From the repository root, using a fresh output directory:

```bash
python3 -B research-craft/evals/flywheel/run_pilot.py --output /tmp/flywheel-v3
python3 -B -m unittest discover -s tests -p test_research_experiments.py
```

The nine planned runs span three comparison groups. Expected results are three
artifact passes and six intentional failures: two earlier negative artifacts
and four decision mutants. Require a complete inventory, completed execution and
zero inconsistent packets; a successful `summarize` exit alone is not this check.
Inspect `summary.json`, each packet's raw output and criterion evidence. The
runner retains source/evaluator/input fingerprints and measured execution time;
unknown model, billing and nested-tool measurements remain unmeasured.

The existing [v2 observations](observed.md) and `observed.json` remain unchanged.
They are historical records under their original source and evaluator versions,
not observations of v3. Comparison across those versions cannot establish uplift.

## Observed local verification

The v3 replay completed all nine planned runs: three passes, six expected
failures, three comparison groups and zero inconsistent packets. Captured
receipts, exact sources, outputs and grades are retained locally under
`.research/hrt-decision-checks.3hTLVr/pilot/`, including `summary.json`.
That machine-local directory is not bundled with this document; the command
above generates fresh packets with the same declared checks.

The root test suite passed 81 tests and the iterate suite passed 17 tests.
The new decision tests first exposed the absent implementation, then passed
after the producer, grader and pilot were extended. Tests also check controlled
pair differences, permitted deferral, constant wrong actions, and missing,
duplicate, extra or malformed observations. All 27 local links checked in the
changed Markdown resolved, and the scoped whitespace check passed.

For actual Agent behavior use the separate visible development packet
research-decision-cases.jsonl（原方法的历史样例，不随 alpha 分发） and
its [execution/grading protocol](../../../tests/behavior-eval-contract.md#research-decision-development-packet).
Keep pair members in the same split but execute them in isolated contexts.
No model behavior, memory architecture benefit, training stability, trading return
or independent generalization follows from deterministic fixture passes.
