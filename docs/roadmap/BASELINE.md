# TwinGrid — Exact-tree baseline (Task 1, BASE-001)

**Status: PARTIAL.** The live test, type-check, lint and build runs could not be executed in this environment. What follows separates **run here**, **verified in source** and **inherited** (taken from logs shipped inside the ZIP, not re-run). Nothing below claims a pass that was not observed.

Date: 2026-10-20. Tree: `TwinGrid-main.zip` (1,501 files, no `.git`; a baseline commit was created locally for diffing only).

## 1. Environment actually used

| Item | Value |
|---|---|
| OS | Linux 6.18 (container) |
| Python available | 3.13.16 (system) and 3.12.3 (via uv). **Repo pins 3.12.10** (`runtime.txt`). |
| Node / npm | 22.22.0 / 10.9.4 (repo wants `>=22.20.0 <23`: OK) |
| PostgreSQL / Docker | not available |
| PyPI | **unreachable**: DNS failure for `pypi.org`; the internal mirror answers 401 (credentials not provided). |
| npm | `npm ci` aborted ("Exit handler never called"); `node_modules/.bin` was not created. |

## 2. What was run here

| # | Command | Result |
|---|---|---|
| 1 | `git init; git add -A; git commit; git tag baseline` | done (diff base only) |
| 2 | `python3 -I -m compileall -q api src models scripts tests alembic *.py` (Python 3.13.16) | **exit 0**: every file parses. This proves syntax only; no module was imported. |
| 3 | `python3 -I scripts/check_register.py` | **`data/external/REGISTER.json: OK (15 datasets)`**, exit 0 |
| 4 | Static read of `alembic/versions/*.py` | 14 revisions, one linear chain, head `20261008000000` (not confirmed with `alembic heads`) |
| 5 | Parse of the junit XML files shipped in the ZIP | see §4 (inherited evidence) |

## 3. What could not be run (and the exact command to run elsewhere)

All of these are **BLOCKED** by the missing packages/services above. None is reported as passed.

```
# Python 3.12.10, repo root
pip install --require-hashes --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.lock
pip install -r requirements-dev.txt
export JWT_SECRET_KEY=ci-test-secret-not-for-production ENVIRONMENT=development PYTHONHASHSEED=0
ruff check . && ruff format --check .
pytest tests/test_audit_regressions.py -q -rs
pytest tests -m "not postgres" -rs --junitxml=junit.xml
export TWINGRID_TEST_PG_URL=postgresql://postgres:postgres@localhost:5432/twingrid_ci DATABASE_URL=$TWINGRID_TEST_PG_URL
alembic heads && alembic upgrade head && alembic check && alembic downgrade base
pytest tests/test_alembic_chain.py -rs && pytest tests -m postgres -rs
pyrefly check --output-format=json            # compare with PYREFLY_ERROR_CEILING=881
pip-audit --requirement requirements.lock --require-hashes --disable-pip --strict
cd twin-stream-insight-main && npm ci && npm run typecheck && npm run lint:ci && npm run test
VITE_API_BASE_URL=https://api.ci.invalid npm run build && npm audit --audit-level=high
```

## 4. Inherited test evidence (re-checked by reading, not re-run)

| Source | Tests | Failed | Skipped | Where/when |
|---|---|---|---|---|
| `t7_junit_0.xml` | 655 | 25 | 5 | Windows, 2026-10-18 |
| `t7_junit_2.xml` | 624 | 13 | 1 | Windows, Python 3.12.10, 2026-10-19 |
| `reports/junit.xml` | 214 | 0 | 0 | 2026-09-29 (older, partial) |

**These logs cover about 624 of roughly 4,700 tests. There is no complete-suite log on file.** None of the 25 failures in the first run appear in the second run, and none of the 13 failures in the second run appear in the first run's failure list (the runs covered different test selections and different code states: 655 vs 624 tests), so the two runs are not directly comparable. The 13 below are the latest recorded failures on that machine. Whether they still fail on this exact tree is **Unverified**.

The ledger (`docs/roadmap/failure-ledger.csv`, 21 rows) classifies each. Summary:

| Group | Count | Category | Cause |
|---|---|---|---|
| Recommendation/optimizer-rule tests expecting `pid` or legacy-scale values | 8 | test-protocol **and** product | see §5 |
| `test_pue_hard_constraint` | 1 | product | PUE missing from `_ENVELOPE_METRICS` (verified in source) |
| `test_repro_framework` | 2 | unresolved / environment | one shows a `requirements.lock` sha256 mismatch (consistent with Windows line endings); one verify result not isolated |
| `test_t23_carbon_aqueduct_contracts` | 2 | unresolved | not isolated |
| Sandbox-only failures from the Final Assessment (93 in a TF-less, DB-less environment) | not re-run | unresolved | 22 artifact-gate failures include a verified source cause (`src/optimizer.py:397`); the rest were never diagnosed |

## 5. Diagnosis: why the recommendation tests fail (`assert 20.5 == 10.0`)

Verified by reading source and shipped configs (no run needed):

1. `src/baseline_recommendation.py:28` sets `CANDIDATES = ("pid", "rule")` with the comment "an exact tie goes to the LATER entry: the simpler rule controller"; line 144 implements it (`later in CANDIDATES wins a tie`).
2. `configs/baselines/pid.json` has `selected_gains = {kp: 0, ki: 0, kd: 0}`, `nominal_setpoint_C = 20.5`, and its stored validation reward is **-54.8094982…**, identical to `configs/baselines/rule.json` (`chilled_C: 20.5`, validation reward **-54.809498221131**).
3. So PID and rule tie exactly, the selector returns `rule`, and every test that expects `name == "pid"` fails. Obtained values 20.5 / 21.5 / 10.0 come from the rule path.
4. Separately, `tests/test_task19_optimizer_rules.py` still contains **legacy-scale expectations** (current 8 °C → 10 °C; bounds `5.0 <= x <= 15.0`; nominal `12.0`) that contradict physics 1's 16–25 °C actuator range. Those assertions are stale regardless of the config.

**Conclusion:** the failures are mostly caused by the stale, degenerate shipped PID config (D-02, fixed by Task 17 re-tuning), compounded by stale legacy-scale expectations in the tests (Task 5). They are not evidence that the recommendation logic is broken. One test (`test_legacy_0_recommendation_is_the_stored_celsius`, a `TypeError`) is **not** explained by this and remain unresolved until run.

Implication for task order: Task 5 should fix the legacy-scale expectations and make tests build their own PID-wins fixture instead of depending on the shipped config; Task 17 then supplies a real tuned PID.

## 6. Other confirmations

| Item | Result |
|---|---|
| `TG-A-05` (register says open; Final Assessment says resolved by removal) | **Confirmed resolved**: `src/digital_twin_optimized.py` is absent (`ls`); `tests/test_physics_v1_invariants.py:773` asserts `not (root / "src" / "digital_twin_optimized.py").exists()`; no `src/` or `api/` file references it. The register should say RESOLVED-BY-REMOVAL. |
| Tuner version mismatch | **Verified**: all four `configs/baselines/{constant,lookup,pid,rule}.json` carry `baselines-tuner/2`; `src/baselines/tuning.py:51` is `baselines-tuner/3`. |
| `docs/api/` | **Verified absent** (tests/test_task9_api_reference.py expects it). |
| PUE in tuner | **Verified**: `src/baselines/tuning.py:64` lists three metrics; `src/policy_evaluation.py:113` lists four. |
| What-if range | **Verified**: `twin-stream-insight-main/src/features/what-if-lab/model.ts:31` `setpointC: { min: 5, max: 15 }`. |

## 7. Not run / still unknown

Every pytest, ruff, pyrefly, pip-audit, alembic, frontend typecheck/lint/test/build/audit command in §3; Playwright; Docker demo. Exact counts for this tree, the real list of failing tests, and the frontend error counts (16 `tsc`, 3 lint warnings are inherited from the Final Assessment) remain unknown until §3 is run in a full environment.

## 8. Next tasks affected

Tasks 5, 6, 7, 17 and 21 should treat the ledger as a hint, not a result, and begin with their own focused run. Task 5 gains a specific diagnosis (§5). A full Task 1 re-run on a machine with network, TensorFlow/torch and Postgres is still needed to close this task as DONE.
