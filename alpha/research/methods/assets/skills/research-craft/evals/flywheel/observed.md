# Research flywheel pilot — 2026-09-28

## Result and boundary

The command runner captures execution and separate grading for two task families.
All four planned packets completed and verified; two known negative artifacts
were rejected and two controls passed. These are artifact replays and synthetic
fixtures, not four new model runs, independent holdouts or evidence of Skill
capability uplift. No speedup, token reduction or investment-return claim follows.

| Case/arm | Result | Decisive observation |
|---|---|---|
| pipeline / archived candidate-resume | Fail | Valid unhashable string input raises `TypeError`; normal and reordered categories pass |
| pipeline / archived candidate-pipeline | Pass | All three declared input checks pass |
| forecast / rewritten history | Fail | Replaces the original forecasts with outcomes and erases the prediction errors |
| forecast / retained history | Pass | Keeps 2800/2560 predictions, resolves errors as -760/-600, keeps Q4 not due |

The pipeline programs are preserved artifacts from the earlier iterate experiment;
the control is an existing alternative, not a newly discovered optimization.
The forecast producer is a structured synthetic adapter of the supplied invest
sequence, not a semantic regrade or rerun of its model-generated reports.

## Evaluator corrections made during development

The initial pilot used duplicate categories. Inspection of the original pipeline
README showed that categories must be distinct. The resulting rejection of the
otherwise passing control was an evaluator error, not a candidate defect. A
reference-behavior regression first failed; the packet advanced from v1 to v2,
using changed category order within the original contract, and both arms were
rerun. Prior local packets were preserved, not edited to appear successful.

Additional failing tests exposed a forecast grader that could accept an invented
actual alongside a correct residual, and Python equality treating `False` like
integer zero. The grader now checks the actuals, resolution state and exact JSON
output types. Both families were rerun after the final grader change. These are
harness repairs; score changes across graders are not credited to candidates.

## Evidence and reproduction

observed.json（原方法的历史样例，不随 alpha 分发） preserves captured stdout, raw grader output,
criterion judgments, process receipts, fingerprints and the generated summary.
Full local packets are under `.research/research-flywheel-2026-09-28-release/`.
The compact committed archive is not a standalone copy of every source snapshot;
the committed fixture, archived original programs and runner reproduce the path:

```bash
python3 research-craft/evals/flywheel/run_pilot.py --output /tmp/research-flywheel-pilot
python3 -B -m unittest discover -s tests -p test_research_experiments.py
```

Use a fresh output directory. The runner records measured preparation, candidate,
grader and total elapsed time in the archived summary. This is one local replay
observation, not training cost, full research-cycle cost or campaign speedup.
Nested tools, tokens, billing and human
effort are unmeasured and remain null. The runner is not an OS sandbox, audit of
all agent actions, holdout access controller or automatic promotion service.

Final verification covers the new execution/grade contract, the documented CLI
and pilot, existing root tests, iterate archive tests, plan tests and investment/
result-analysis tests. Source and metadata checks protect compatibility; they
are reported separately from model behavior.
