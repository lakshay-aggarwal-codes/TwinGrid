# Task 5 — ENG-001 PUE in tuner feasibility + recommendation range failures          Status: PARTIAL
Base: TwinGrid-main.zip as uploaded 2026-10-20 (no git history; baseline tag made in the sandbox)   Date: 2026-10-20
Environment: Python 3.12.3, numpy 2.4.4; NO pytest, NO gymnasium/torch/fastapi, NO network, NO ruff. Tests were run
with a home-made pytest stand-in and a stub `gymnasium` (both outside the repo). That is not a real pytest run.

## Summary
The tuner kept its own three-metric feasibility set, so PUE-violating candidates could be tuned as feasible. It now imports
`pe.HARD_CONSTRAINT_METRICS` and derives `FEASIBILITY_RULE` from it; Lookup's per-step flag counts PUE too. The 8
inherited recommendation failures were stale test expectations (legacy 5..15 C numbers against physics-1 shipped
configs), not wrong code; they now set their own configs. The recommendation refuses stored hard-constraint violations and
carries config lineage.

## Acceptance checklist
- One hard-constraint set for tuner/harness/recommendation -> met (`tuning._ENVELOPE_METRICS is` the harness tuple; guard test also pins `run_export`'s copy). Evidence: stand-in run.
- `pue_over_max_steps > 0` is never feasible and never recommended; fails on baseline -> met. 18 of 23 new tests fail on baseline source (stand-in run); the 5 that pass there guard behaviour that was already right.
- Named tests green or documented-invalid -> green in the stand-in run except 5 that need `fastapi` (not installed here). Not verified under real pytest.
- Changed expectations carry a reason comment and are pinned on both physics versions -> met (see Decisions).
- Unsupported physics raises, not clips -> met (`_denormalise`/`_to_policy_scale` raise for "2", "999", ""); `recommend` now gives an accurate skip reason.
- Lineage on outputs -> met: `selected.lineage` (config lineage fields, tuner version, config sha256, feasibility rule, counted/not-counted constraints) and `selected.caveats`.

## Changed files
- src/baselines/tuning.py - constraint set imported, rule text derived, `is_feasible` strict, `step_violates_envelope` (PUE in Lookup)
- src/baseline_recommendation.py - `hard_constraint_status`, refuse stored violations, `lineage`/`caveats`, unsupported-physics reason
- tests/test_task5_hard_constraint_set.py - new (23 cases)
- tests/test_task19_optimizer_rules.py, tests/test_recommendation_ranges.py - stale legacy expectations replaced
- docs/roadmap/task-reports/TASK_5_REPORT.md - this file

## Commands run (stand-in runner, sandbox; NOT real pytest)
- tests.test_task5_hard_constraint_set: 23 pass / 0 fail (baseline source: 5 pass / 18 fail)
- tests.test_recommendation_ranges: all pass; tests.test_task19_optimizer_rules: all pass except `test_the_api_mode_vocabulary_is_the_optimizers` (no fastapi)
- tests.test_pue_hard_constraint: 19 pass / 4 fail (all 4 need fastapi). The stale-feasibility-rule test now RUNS and passes (it skipped on baseline because the old tuner text was "current").
- tests.test_baselines + test_repro_framework: 20 fail in the stand-in, mostly its own limits (generator fixtures, tmp_path_factory, chdir). Same failure set before and after my change except `test_shipped_baselines_run_reproduces_on_rerun` (red both times, now BaselineConfigStale).

## Pre-existing failures observed
`test_baselines.py` pins `tuner_version == /3` while the shipped configs are `/2` (red until Task 17, as the card says).

## Not run / blocked
Real pytest, `ruff check .; ruff format --check .`, the api-dependent cases. Commands are in the reply.

## Decisions and defaults used
- Root cause of the 8 failures: the shipped configs are physics-1-native (rule 20.5 C; PID nominal 20.5 C, gains all 0; rule and PID tie at -54.8095). The tests hard-coded legacy numbers (12.0, 10.0, -91.05/-92.16, 22.3). Tests now edit tmp config copies (22 C, kp=1, explicit rewards); no expectation was loosened. Evidence: Task 3 report logic, `CHILLED_WATER_ACTION_RANGE_C`, ADR 008.
- PID without inlet reports its nominal set-point by design; the old test helper had computed a rate-limited step from the 10 C reset (18 C under physics 1). The helper now starts at nominal.
- The legacy-scale PID conversion branch is kept covered by an explicitly built legacy-scale policy.
- `TUNER_VERSION` stays `/3` (three tests pin it); Task 17 owns the bump with the re-tune.
- Stored configs tuned under the old rule stay recommendable but are flagged (PUE "not measured", not zero). A stored count > 0 is refused. Switching to refuse-all-old-rule configs is one line in `recommend` if you prefer.

## Requested cross-task changes
`src/run_export.py` keeps its own `HARD_CONSTRAINT_METRICS` copy (equal today; guarded by a test). Import it from `policy_evaluation` when its owner next edits it.

## New limitations or risks
`src.baselines.cli run` / `bev.load_baselines` now refuse the shipped configs (`BaselineConfigStale: tuning.feasibility_rule`) until Task 17 re-tunes. That is Amendment A2's intended gate, which the tuner's omission had defeated. Lookup cell feasibility is stricter, so a re-tune can change the table.

## Next tasks unblocked
Task 17 (re-tune). Tasks 6 and 7 are unaffected.
