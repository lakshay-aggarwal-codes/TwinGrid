# Task 4 — Re-register, re-tune, re-run, repair the baseline tests

## What was run (owner's machine, Windows, Python 3.12.10) — NOT the sandbox
1. `python -m src.policy_evaluation prereg --out reports\policy_evaluation_physics1` -> wrote the physics-1 protocol (after deleting the provisional pre-fix one, which the tool correctly refused to overwrite).
2. `python -m src.baselines.cli tune --prereg …` -> four configs, `tuner=baselines-tuner/2`, `physics=1`, `range=16.0..25.0`.
3. `python -m src.baselines.cli run … --run-id baselines-v3` -> `baselines-v3`.

## Measured (VALIDATION scenarios, flat 475 g/kWh assumed carbon — not test results, not real carbon)
| baseline | status | tuned | validation reward |
|---|---|---|---|
| rule (not tuned) | feasible | 20.5 C + production mode rule | -54.8095 |
| constant | feasible | 22.75 C, `closed_loop` | -36.3247 |
| lookup | feasible | 5x5 bins, 7 of 25 cells fell back to the best constant | not captured |
| pid | feasible | kp=ki=kd=0 | -54.8095 (identical to rule) |
All four satisfy zero outlet/inlet-over/inlet-under steps on every validation episode. These are real physics-1 temperatures; before the fix the same labels meant different temperatures (TG-A-13).
A sandbox re-run (Linux, scratch copy, not shipped) reproduced the same selections (22.75 C closed_loop; 7 fallback cells; zero PID gains).

## Findings
- **TG-A-16:** the PID is degenerate because its target inlet (22 C) is fixed and below what the reward prefers; see the register. Not blocking.
- The best constant beats the production rule by ~18.5 reward on validation, driven by cooling mode. PPO must beat the constant, which is a strong comparator.

## Code/test changes in this ZIP
- `src/baselines/evaluation.py`: `PHYSICS1_PREREG` constant; `evaluation_document` default points at the physics-1 protocol.
- `src/baselines/cli.py`: `PREREG` default is the physics-1 protocol (so `tune`/`run` work without `--prereg`).
- `tests/test_baselines.py`: shipped-artifact tests use `SHIPPED_PREREG` / `SHIPPED_RUN = "baselines-v3"`; scratch-world tests keep their own tmp-root protocol path; the tune-command test passes an explicit `prereg`; new test pins CLI default == evaluation default == shipped path. (The two obsolete version-bump tests were already fixed in Task 2.)

## Verification
- Owner's machine before this ZIP: `test_baselines.py` 84 passed, 3 failed — exactly the three shipped-artifact tests (expected: they pointed at the legacy protocol hash and `baselines-v2`).
- Sandbox after this ZIP: 84 passed + the 3 shipped tests fail ONLY because the sandbox has no `baselines-v3`/physics-1 artifacts. In a scratch copy where the artifacts were generated with the same commands: `tests/test_baselines.py` **88 passed**. This validates the tests' logic, not your files; your run is the real check.

## Not done
- Held-out (test-split) results of `baselines-v3` were not inspected. Lookup's validation reward was not captured.
- PID target search (optional Task 4b). Recommendation/API ranges (Task 3). Carbon is still assumed.
