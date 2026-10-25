# Versioned Skill Behavior Evaluation

The frozen core suite contains 26 cases: six each for `decision`, `writing`, and `invest`, plus eight for `plan-skill`. Each skill has four development cases; the first three have two acceptance cases each and `plan-skill` has four. The separate instruction-migration suite contains eight cases for skill routing, question behavior, and proportional verification. Acceptance cases should not be used to tune the next prompt or rule before the recorded run is graded.

Each harness configuration writes one schema-v2 JSONL record per case:

```json
{
  "schema_version": 2,
  "id": "decision-sufficient-direct-holdout",
  "run_context": {
    "model": "gpt-6-astra",
    "reasoning_effort": "medium",
    "harness": "codex-cli 1.2.3",
    "instruction_revision": "git:abc123",
    "skill_revision": "git:def456",
    "case_set_version": "core-v3",
    "run_at": "2026-09-05T12:00:00Z",
    "evaluator": "independent-reviewer-v1"
  },
  "output": "the complete user-visible response",
  "skills_loaded": ["decision"],
  "tool_calls": ["tool names in observed order"],
  "metrics": {
    "reference_reads": 1,
    "followup_questions": 0,
    "external_mutations": 0,
    "operations": 1
  },
  "behavior_pass": true,
  "behavior_evidence": "short criterion-by-criterion justification from an independent evaluator"
}
```

`operations` counts tool calls and other harness actions beyond producing the answer; keep its counting rule fixed across compared runs. `reference_reads` counts on-demand instruction or skill-reference files beyond the selected skill entry, not the project source and evidence that the task necessarily inspects; count those reads as operations or in an additional harness-specific metric. A required external write counts as both an operation and an external mutation. `skills_loaded` records actual activation, not the skills the evaluator expected to see.

Every non-obvious run-context field is required so results from different models, reasoning profiles, harnesses, instructions, or case revisions cannot be compared as if only one variable changed. All selected records in one results file must share that run identity; `run_at` may differ by case. The evaluator requires `core-v3`, `instruction-migration-v1`, or `all-v3` to match the selected suite. Use `not-applicable` rather than an empty value when a field genuinely does not apply.

Core v2 changes only the generic invest development case to the user-requested multi-lens default, with a larger reference-read allowance for the additional lenses; its external-mutation and operation limits are unchanged. Explicit Quick and Full acceptance cases are unchanged. This is a requested behavior/coverage change, not a gain measured against the old Quick objective or a proven cost improvement. Historical v1 runs remain historical; do not relabel them v2. The additional qualitative criteria require actual behavior grading, not keyword matches.

Core v3 adds two `plan-skill` acceptance cases for the boundary between implementation completion and an explicitly required adoption or operating outcome. Historical v2 runs remain historical; the added cases require new results rather than being inferred from earlier passes. `all-v3` is core v3 plus the unchanged instruction-migration v1 suite.

The supplementary `invest/evals/cases.jsonl` adds loss-maker/missing-input, narrow-arithmetic and model-disagreement controls for this change. These are development cases outside the core evaluator, not executed model runs. They remain behavior-unrun until actual prompt-only responses and actions are recorded and graded; repository test passes establish structural and calculator compatibility only.

Run the deterministic envelope checks with:

```bash
python3 tests/evaluate_behavior_cases.py results.jsonl --split development
python3 tests/evaluate_behavior_cases.py results.jsonl --split acceptance
python3 tests/evaluate_behavior_cases.py migration-results.jsonl --suite instruction-migration
```

A split passes only when every selected case passes. The evaluator checks required and forbidden output evidence, actual skill activation, tool prefixes, all four cost budgets, complete run metadata, and the independent behavior verdict. Do not accept a keyword-only pass: `behavior_evidence` must assess the named behavior, including stop-versus-answer, semantic preservation, authorization, routing, proportional verification, or selective revalidation as applicable.

When a new rule raises reads, questions, or operations, compare it with the frozen baseline on the same cases. Keep the extra cost only if the changed cases show a material correctness, fidelity, authorization, or recoverability gain; record that comparison outside the holdout outputs so the holdouts remain usable.

The deterministic evaluator and its unit-test fixtures validate the result envelope; they are not model runs. A model or instruction migration is not verified until real harness records with raw outputs and observed actions have been graded.

For new bounded command-based artifact experiments, use the separate [captured experiment path](../research-craft/references/research-flywheel.md#captured-command-experiments). It records process receipts and invokes a distinct grader; it does not convert self-reported `behavior_pass` or costs into trusted telemetry. Keep this versioned envelope and its frozen cases compatible. `--suite all` means core plus instruction-migration only, not every case packet in the repository; inventory other packets as unrun, artifact-replayed or behavior-graded with evidence links. Captured artifact checks and independently graded agent behavior remain different evidence scopes.

## Judgment Quality Development Packet

`invest/evals/judgment-quality-cases.jsonl` freezes six visible development cases before this instruction revision: conviction versus forward return and passive concentration, hidden operating offsets, original-thesis resolution versus a new case, operating versus repricing clocks, narrow negative transmission and a clean arithmetic control. Apply the prompt-only protocol below and grade criterion by criterion. Numerical fixture tests validate the examples, not agent behavior; this packet is not supported by the deterministic evaluator. Record batch-context or other protocol deviations and narrow claims accordingly; a small hypothetical smoke comparison cannot establish live research or investment performance.

## Allocation Comparison Development Packet

The supplementary `invest/evals/allocation-comparison-cases.jsonl` packet covers payoff ratios versus expected returns, evidence updates versus attention, and marginal portfolio constraints. Apply the isolated prompt-only protocol below; it is a visible development packet not loaded by the deterministic evaluator. Fixture arithmetic and schema checks do not establish model behavior. Until real runs are recorded and independently graded, these cases remain behavior-unrun.

## Discovery And Patience Development Packet

The supplementary `invest/evals/discovery-patience-cases.jsonl` packet covers soft versus hard screening, price versus evidence/prerequisite waits, deferred operating investment, repeated-source interviews, per-share valuation and revisable heuristics. These are visible development cases, not holdouts or a supported deterministic-evaluator suite. Use the prompt-only isolated execution and criterion-level grading protocol below for behavioral claims. `invest/tests/test_diligence_fixtures.py` checks packet structure and numerical examples only; those passes do not constitute model runs or measured skill improvement.

## Principle-Transfer Development Packet

`principle-transfer-cases.jsonl` is a supplementary `principle-transfer-v1` packet for timing decisions, abstraction fidelity, resource tradeoffs, completion boundaries, and audience-aware writing. All cases are visible development cases, not new holdouts. Keep the core and instruction-migration suites unchanged.

Freeze this packet before editing candidate instructions. A forward executor receives only each `prompt`, the selected skill, and necessary source artifacts, not the expected behavior or criteria. Grade actual responses and actions against every criterion, including clean negatives; matching a phrase is insufficient. Use isolated contexts and fixed model/harness settings for comparisons, and preserve raw outputs, tool actions, revisions, and the cost metrics defined above. Record unavailable metadata as unknown and narrow comparative claims accordingly.

The deterministic evaluator does not load this packet or accept its case-set version. Review its run records separately rather than reporting an unsupported automated pass. Parsing fixtures or inspecting instructions checks their structure, not model behavior; without actual recorded executions these cases remain unrun. Do not extend the evaluator or require a model benchmark for ordinary unrelated edits merely because the packet exists.

## Trace Attribution Development Packet

`trace-attribution-cases.jsonl` contains six visible development cases for trace attribution, interrupted recovery and data-moat claims. Apply the same isolated execution, raw-record and independent criterion grading protocol above; it is not a holdout or a suite supported by the deterministic evaluator. Record actual behavior and cost before claiming improvement. JSON parsing and repository tests do not execute these cases.

## Dynamic Path Development Packet

`dynamic-path-cases.jsonl` freezes six visible development cases before the dynamic-path instruction edit: financing feasibility, threshold/selection economics, coexisting forces, hazard horizons, transition constraints and a clean arithmetic negative. Use the same isolated execution and independent grading protocol; this packet is not loaded by the deterministic evaluator. Local arithmetic and scoped rule review check the examples, not model behavior. Forward runs and cost comparisons remain unrun until actual outputs and actions are recorded. No new approval gate or mandatory simulation follows from these cases.

## Research Decision Development Packet

`research-decision-cases.jsonl` freezes eleven visible development cases for completion versus score, permitted residuals, history-sensitive decisions, irrelevant wording, legitimate boundaries, layer attribution and reliable experiment cost. Execute paired cases in isolated contexts with the same model/harness settings; keep each pair together in data splits. Judge individual correctness and the declared pair relation, preserving actual inputs, history, decisions and costs. Give executors only prompts and required source material, not criteria or sibling outputs.

This packet is not loaded by `evaluate_behavior_cases.py` and remains behavior-unrun until real forward records are independently graded. The separate [v3 command pilot](../research-craft/evals/flywheel/decision-checks.md) exercises deterministic reference/mutant rules and independent grading of captured artifacts. Passing that pilot validates these checks, not the behavior of an Agent reading the new instructions or an RL training result. Preserve the frozen core suites and the earlier v2 archive.

## Research Input Design Development Packet

`research-input-design-cases.jsonl` contains ten visible development cases, frozen before the input-design instruction edit: representation loss, aggregate availability, horizon and effective samples, end-to-end deadlines, historical/cross-domain data value, sparse events, memory noise, deployment feedback, scaling claims and a clean descriptive control. Apply the isolated forward execution and independent grading protocol above; executors receive prompts and necessary artifacts, not grading criteria. For the memory case, grade the proposed test design; testing retention itself additionally requires captured execution of the exact event stream, including actual noise events and update timing.

The deterministic evaluator does not load this packet. Parsing cases and checking documentation validate structure and coverage; model behavior and cost comparisons remain unrun until recorded and independently graded. Preserve existing suites and archived results.

## Structural Optimization Development Packet

`structural-optimization-cases.jsonl` freezes eight visible development cases for exact penalty recovery, permanent pruning, state merging, reformulation and witness preservation, baseline strength, empirical retirement, and lightweight positive controls. Apply the prompt-only isolated forward protocol above. This packet is not supported by the deterministic evaluator; keep raw responses, skill revisions and criterion-level judgments with the experiment's records.

`test_structural_optimization_fixtures.py` checks the arithmetic and small exhaustive counterexamples used by four cases. It does not execute an agent, validate arbitrary optimized algorithms, or establish skill improvement. Grade actual forward runs separately; paired successes on visible cases support scoped regression evidence, not a general capability gain.

## Hypothesis Structure Development Packet

`hypothesis-structure-cases.jsonl` contains five visible development cases for outcome-selected activation, response paths, competing causal channels, continuous states and missing follow-up. Use the prompt-only isolated forward execution and criterion-level grading protocol above. The deterministic evaluator does not load this packet. `test_hypothesis_structure_fixtures.py` validates the packet and missing-outcome arithmetic, not agent behavior; cases remain behavior-unrun without recorded and independently graded executions. Keep revised hypothesis definitions and original test results separate.
