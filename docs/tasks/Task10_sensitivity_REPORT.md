# Task 10: physics sensitivity and invariants

This repository already has a `docs/tasks/Task10_REPORT.md` from another task list, so this report is named
`Task10_sensitivity_REPORT.md` instead of overwriting it.

## What changed

| | File | What |
|---|---|---|
| CREATE | `scripts/sensitivity.py` | Deterministic sensitivity study. Perturbs each documented physics parameter one at a time by -25 %, -10 %, +10 %, +25 % and reports mean PUE, energy, water, outlet and inlet temperature (mean and max) and safety-envelope violation steps. Study 1: the 31 physics-1 parameters of `docs/PHYSICS_V2.md` marked (v1), through the frozen harness `run_episode`, for the production rule and three constant set-points, on validation-split scenarios only. Study 2: every numeric `PhysicsParams` field on the physics-2 twin only (the RL environment refuses physics 2), replaying the same exogenous traces open loop. No physics file is edited: a parameter is changed by temporarily setting the module's own constant and restoring it. |
| CREATE | `tests/test_sensitivity.py` | 17 tests: registry completeness and defaults equal the documented ones; exact restore (also when the block raises); factor 1.0 and repeat runs identical; finite outputs, PUE >= 1, energy identity, envelope counting; physics-2 energy closure for perturbed parameter sets; an invalid physics-2 perturbation is reported as rejected; validation split only. No physical direction is asserted (the model does not guarantee one). |
| CREATE | `docs/SENSITIVITY.md` | Method, the real numbers, what they say, and what they do not show. |

## What I ran, and what happened

All in my sandbox (Linux, Python 3.12.3, numpy 2.4.4). `gymnasium` and `pytest` are not installed there and there is no network, so:

* `gymnasium` was replaced by a stand-in with only `Env` and `spaces.Box` on the path (not in the ZIP). The physics, shield, baselines and harness are the repository's own code.
* The tests ran under a small pytest stand-in, not real pytest: `passed 17, failed 0, skipped 0`.
* `python scripts/sensitivity.py --studies physics1` (279 s) and `--studies physics2` (99 s) ran to completion on 9 validation scenarios; their numbers are in `docs/SENSITIVITY.md`, merged `results_sha256` `b937a458...cdb6a` (full value in the doc).
* Over-long lines in the new files were wrapped by hand; the registry table is wrapped in `# fmt: off` / `# fmt: on`.

## What I did not verify

* Real `pytest`, `ruff check`, `ruff format --check` (CI runs both; no formatter was available, so formatting is by hand and may need `ruff format`), and `mypy`.
* That the numbers reproduce on your machine (last digits can differ across platforms; compare the tables).
* That `gymnasium`'s real `Env` base class behaves like the stand-in for this script (the script does not call anything on it beyond what the environment already does).

## Assumptions

* Three documented physics-1 parameters are literals in the equations (`cop_outside_derate_start_c`, `cop_chw_bonus_floor`, `water_warm_reference_c`) and cannot be perturbed without editing the physics file, so Study 1 lists them and Study 2 covers them.
* `cop_humidity_derate_per_pct` is perturbed through physics 1's single humidity constant (the documented value is half of it).
* The three constant set-points are the low, middle and high of the physics-1 actuator range, in closed-loop mode; the constants are not tuned.
* Scenarios are the first 3 per family of the validation split (9 scenarios); `--scenarios-per-family` changes that.
