# Task 6 (TwinGrid roadmap) — PUE as a counted hard constraint (TG-A-12, amendment A2)

> `docs/tasks/Task6_REPORT.md` may already exist for a different task list; this report has its own name.

## What changed
See `docs/audit/Amendment_A2_PUE_hard_constraint.md` (full list and disclosure). In short: `pue_over_max_steps`
(`not pue <= SAFETY_ENVELOPE.pue_max`; NaN counts, exactly 2.0 does not) is counted per step in `run_episode`, is the
fourth `HARD_CONSTRAINT_METRICS`, and enters the outcome A/C rules and text, the report table, the baseline tuner's
feasibility rule and `results.json` schema 2. `api/services/evaluation_service.py` accepts schema 1 and 2 and adds the
additive key `hard_constraints {counted, not_measured, note}`; a schema-1 report says PUE was *not measured* (no zero is
invented). `baselines run` refuses configs tuned under the old feasibility rule (`tuning.feasibility_rule`).
The frozen legacy report is untouched (SHA-256 pinned in a test).

## Result: does any baseline violate PUE under physics 1?  No.
Sandbox measurement (Linux, Python 3.12.3, flat 475 g/kWh carbon curve, which does not affect PUE) of the shipped
physics-1 configs plus the five-point constant grid on the registered validation (30 episodes) and test (60) scenarios:
max per-step PUE 1.2625-1.3652 vs the limit 2.0; 0 violating steps for rule, constant, lookup, pid and every grid
constant. This is the committed configs, not a re-tune.

## Files
MODIFY `src/policy_evaluation.py`, `src/baselines/tuning.py`, `src/baselines/evaluation.py`,
`api/services/evaluation_service.py`, `tests/test_audit_regressions.py` (test renamed "four limits"),
`tests/test_evaluations.py` (DETAIL_KEYS; the "unsupported schema" case now uses 99 since 2 is supported),
`docs/audit/TwinGrid_Issue_Register.md`, `docs/frontend/contracts/G-EVAL.md`.
CREATE `tests/test_pue_hard_constraint.py` (23), `docs/audit/Amendment_A2_PUE_hard_constraint.md`, this report.
`src/baselines/config.py` is NOT changed: staleness is enforced in `load_baselines` only, so the API recommendation and
the rest of the suite keep working until you re-tune.

## Tests (Linux sandbox; not your machine)
* New file: 23 pass; on the unmodified tree 20 fail, 2 pass, 1 skipped.
* Full suite (ignoring `test_runs.py`, `test_t27_env_v2.py`, which need torch), unmodified vs changed: 84 failed + 2
  collection errors in both. The sets differ by one: `test_shipped_baselines_run_reproduces_on_rerun` now fails
  (expected: shipped configs were tuned before the PUE rule; passes after re-tune), and
  `test_artifact_integrity.py::test_anomaly_endpoint_reports_unavailable_when_the_artifact_is_tampered` failed only on
  the unmodified run (not investigated, unrelated).
* 10 failures pre-exist on your uploaded tree (not root-caused): 5 `test_task19_optimizer_rules`, 4 in my Task 3
  `tests/test_recommendation_ranges.py` (they assumed the provisional pre-Task-4 configs and need updating to the
  retuned ones), 1 `test_baselines::test_shipped_baselines_run_verifies_and_lists_all_four`.

## Not run / not verified
Your Windows machine; frontend tests; a scratch re-tune (started, did not finish: NOT MEASURED); `baselines-v4`;
torch tests; Postgres.

## You must repeat Task 4's human steps (and why)
The hard-constraint set is part of the protocol: the tuner's feasibility rule changed, so shipped configs record a rule
that no longer matches, and the metric list / outcome-rule text in `PREREGISTRATION.json` (outside the hash) is outdated.
PowerShell from the repo root (follows Task 4's report; not run by me on Windows):
```
Remove-Item -Recurse reports\policy_evaluation_physics1   # the tool refuses to overwrite a registration
python -m src.policy_evaluation prereg --out reports\policy_evaluation_physics1
python -m src.baselines.cli tune
python -m src.baselines.cli run --run-id baselines-v4
python -m src.baselines.cli verify baselines-v4 --rerun --strict
python -m pytest tests\test_baselines.py tests\test_pue_hard_constraint.py -q
```
Expect the tuned parameters to be unchanged (nothing violates PUE) but they must be regenerated; do not edit the JSON.

## Remaining risks
1. Frontend: `twin-stream-insight-main/src/evaluation/schema.ts` has `schema_version: z.literal(1)`; a schema-2 report in
   `reports/policy_evaluation/` would be rejected as a contract violation. Fix before adding one (none exists today).
2. `scripts/eval_policies.py` `ENVELOPE_METRICS` (outlet, inlet-over) is a separate pre-registered protocol; unchanged.
3. A2 was decided after `baselines-v3` existed (disclosed in the amendment). No PPO result was scored under any rule.
