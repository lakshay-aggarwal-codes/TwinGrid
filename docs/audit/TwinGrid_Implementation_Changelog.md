# Implementation Changelog (deep audit)

| # | Files | Problem | Change | Verified by |
|---|---|---|---|---|
| 1 | `src/rl/env.py`, `src/optimizer.py` | v2 -> `KeyError` in reset (TG-A-03) | `RL_SUPPORTED_PHYSICS_VERSIONS`, `assert_rl_supported_physics_version`, `UnsupportedPhysicsVersionForRL`; checked in `DataCentreEnv` and `JointOptimizer` | 3 tests (v2 rejected x2, legacy-0/1 still run) |
| 2 | `src/policy_evaluation.py` | label/execution split (TG-A-01) | canonical default `1`; `resolve_physics_version`; legacy label alias; explicit env arg; `PhysicsMismatchError`; `physics_version_executed` in results and report | 6 tests incl. reproducing the committed report |
| 3 | `src/policy_evaluation.py` | relative safety gate (TG-A-02) | `HARD_CONSTRAINT_METRICS`, `hard_constraint_total`; absolute gate; feasible-only best constant; rule text amended (A1) | 5 tests; `test_policy_evaluation.py` 53 pass |
| 4 | `src/baselines/config.py`, `evaluation.py`, `cli.py` | lineage/physics split (TG-A-04) | guard + `--prereg` | 1 test |
| 5 | `tests/test_policy_evaluation.py` | tests encoded old rule | synthetic fixture default 0 under-min; relative test replaced by absolute tests; committed-prereg test now asserts legacy-0 protocol differs from default only in physics | pass |
| 6 | `tests/test_audit_regressions.py` | no regression coverage | new file, 14 tests (1 strict xfail for TG-A-05) | 13 pass, 1 xfail |
| 7 | `PERFORMANCE_OPTIMIZATION.md`, `benchmark_performance.py` | false claims, hardcoded success banner | rewritten / banner replaced | manual |
| 8 | `docs/CLAIMS.md`, `docs/architecture/system.md` | stale versions/migration count | corrected | manual |

Behavioural changes to be aware of: `EvalConfig()` default physics is now `"1"` (was a label that executed as v1 while reporting legacy-0); `python -m src.baselines.cli tune/run` now refuses the committed legacy-0 protocol until a physics-1 protocol is registered and passed via `--prereg`. Unchanged on purpose: committed PREREGISTRATION and its report, so the API and frontend fixtures keep working.
Known remaining concerns: see the issue register (TG-A-05, 07, 08, 11, 12).
