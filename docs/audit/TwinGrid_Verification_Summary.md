# Verification Summary (audit sandbox, 2026-10-18)

Environment: Linux sandbox, Python 3.12.3, NumPy 2.4.4, gymnasium 1.3.0, pytest. **No** TensorFlow, PyTorch, Postgres/Redis, Docker, Node. Nothing here was run on the owner's machine.

## Confirmed passing
- `tests/test_audit_regressions.py`: 13 passed, 1 strict xfail (TG-A-05).
- `tests/test_policy_evaluation.py`: 53 passed, 2 xfailed.
- `tests/test_physics_v1_invariants.py`, `tests/test_physics_v2.py`: pass (run in the first targeted pass).
- Reproduction: committed baselines-only report's first rule episode reproduces under legacy-0 to 1e-9 (test above).

## Whole-suite comparison, original vs modified (94 test files, run in 6 chunks of <=120 s)
Failure sets are identical between the original repo and the modified repo for 5 of 6 chunks; in the 6th the original had one extra failure (`test_runtime_fanout.py::test_two_hundred_clients...`, a timing-sensitive test, not touched by this work; treat as flaky, not as fixed). **No new failures were introduced.** The failures that remain (identical before/after) fall into:
- Missing TensorFlow/torch in the sandbox: anomaly detector tests, parts of `test_artifact_gate.py`, `test_t27_env_v2.py` (not run).
- Database/migration tests (`test_facility_migration.py`): need Postgres; not available.
- `test_baselines.py` (6): genuinely stale shipped baselines (TG-A-07). **Confirmed failing, not fixed.**
- `test_gitignore_source_dirs.py`: 1 failure, cause not investigated.
These are counted as failures here; I did not separate environment-caused from real ones beyond the baselines group.

## Not executed
Frontend build, Vitest, Playwright E2E, contract tests; Docker/compose demo; Alembic migrations; load tests; GitHub Actions; pyrefly; any RL training; any PPO evaluation; accessibility checks.

## Benchmarks
Single run of `benchmark_performance.py`: main twin ~3.3 ms (legacy-0) / ~3.7 ms (v1) per 288-step day, "optimized" ~1.1 ms with different outputs. No warm-up or repeat control; indicative only.

## Needs external validation
Every physical result is from a lumped simulator with no real-facility calibration; carbon intensity is a flat 475 g/kWh fallback; no claim of real-world safety, calibration or real-time operation is supported.

## Commands for you (PowerShell)
```powershell
Expand-Archive .\TwinGrid_Audit_Fixes.zip -DestinationPath . -Force
python -m pytest tests\test_audit_regressions.py tests\test_policy_evaluation.py -q
# re-tune baselines under a physics-1 protocol (untested path; see TG-A-07)
python -m src.policy_evaluation prereg --out reports\policy_evaluation_physics1
python -m src.baselines.cli tune --prereg reports/policy_evaluation_physics1/PREREGISTRATION.json
python -m src.baselines.cli run  --prereg reports/policy_evaluation_physics1/PREREGISTRATION.json --run-id baselines-v3
python -m pytest tests\test_baselines.py -q   # still expects the legacy PREREG path and baselines-v2; update those constants first
```
