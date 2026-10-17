# QA sweep (Task 32)

Scope: the repository ZIP you uploaded (through Task 25), plus the Task 26 and 28 output ZIPs and your Task 27 and Task 30 ZIPs, merged in that order. **Tasks 29 and 31 were not provided**, so they are not in this tree and not swept.

## What I could and could not run

This sandbox has no network and none of the project's dependencies (no FastAPI, SQLAlchemy, Alembic, prometheus_client, gymnasium, bcrypt, httpx, pytest, pytest-asyncio, `node_modules`). So **neither `pytest -q` nor `npm run verify` was run**, and there is no green output to quote. What I ran instead, and what it covers:

| Check | Result |
|---|---|
| Every `tests/**/test_*.py` through a small pytest stand-in (fixtures, `tmp_path`, `monkeypatch`, `raises(match=)`, conftest fixtures) | 124 modules; 40 import here; **615 tests pass, 76 do not pass**; 24 of the 40 modules are fully green. See "Remaining non-passes" below: all 76 are missing dependencies or data, or limits of the stand-in, and none is a confirmed code defect after the fixes below. 84 modules cannot even be imported here (missing: `pytest_asyncio` 20, `sqlalchemy` 15, `fastapi` 15, `prometheus_client` 8, `gymnasium` 8, `aiosqlite` 3, `redis` 2, others 1 each). |
| `python audit_alembic_graph.py` | 14 revisions, 14 unique, one chain ending at `20261008000000`. Single head. |
| Secrets and demo credentials (private keys, AWS/GitHub/Slack/Google/JWT token shapes, assigned password/secret literals, demo accounts) across the repo and the frontend source | **Nothing found.** The demo accounts' passwords are generated at seed time and printed once (`scripts/demo_seed.py`); `VITE_DEMO_*` is dev-only, documented as public, and refused in production builds; CI uses a labelled placeholder. Only test fixtures and a recorded report contain fake credentials. No `.env`, key or certificate file is committed (`.env.example` only). |
| `python scripts/gen_api_reference.py` | **Not run** (it imports the FastAPI app). See the first open item. |
| Unused imports (AST scan of `api/`, `src/`, `models/`, `scripts/`) | 0 before and after my removals. |
| Duplicate `(method, path)` routes across plugins and routers | 60 routes, 0 duplicates. |

## Real defects found and fixed

1. **`.env.example` was missing six variables that `api/config.py` reads** (`RATE_LIMIT_GENERAL`, `HTTP_LIMITS_ENABLED`, `MAX_BODY_BYTES`, `MAX_CONCURRENT_COMPUTE`, `BROADCAST_MODE`, `READYZ_CHECK_SCHEMA`), so `tests/test_startup_checks.py::test_env_example_contains_every_variable_read_by_startup_checks_and_config` failed. Added, with the defaults from the code.
2. **`api/config.py` raised a plain `RuntimeError` for a missing `CORS_ALLOWED_ORIGINS` in production**, but `test_config_cors_error_is_a_startup_config_error` (and the startup contract) expect `StartupConfigError` naming only the variable. It now raises `StartupConfigError(["CORS_ALLOWED_ORIGINS"], ...)`, which is still a `RuntimeError`. `tests/test_startup_checks.py`: 57 pass, 1 left (needs `bcrypt`).
3. **`docs/DATA_LICENSES.md` lost two sentences that `tests/test_external_register.py::test_data_licenses_doc_covers_every_entry` requires** (a later rewrite dropped them): the plain statement that no licence is verified, and the PowerShell `Get-FileHash` command for recording a terms hash. Restored. `test_external_register.py`: 72 pass; `test_task11_data_truth.py`: 10 pass.
4. **Lane merge conflict in `twin-stream-insight-main/src/features/registry.test.ts`**: the Task 30 version of the feature list lacked `capacity`, `carbon-scheduling`, `economics` and `maintenance`. The list is now the union, all 19 feature directories.
5. **Two nav entries tied** (Capacity and Fleet view, both Explore, order 40). Fleet view is now order 50.
6. **Env docs referenced by code were missing from the repository**: `docs/env/Task15.md`, `Task23.md`, `Task24.md`, `Task25.md`. Recreated from the code (variable names and defaults read from `api/plugins/*` and `api/config.py`). `docs/env/Task1.md`, `Task5.md`, `Task7.md`, `Task9.md` are also referenced and still missing; I could not reconstruct them without guessing.

## `.env.example`

Appended, under section comments: the six core variables (item 1), every variable in `docs/env/Task6.md`, `Task15.md`, `Task24.md`, `Task25.md`, `Task26.md`, `Task27.md`, and a note for `Task28.md` (no new variable; its two scopes were already present). No duplicate keys. Variables read in code but still not in `.env.example` and outside what the tests check (listed so you can decide): `ALLOW_PUBLIC_REGISTRATION`, `ANOMALY_EPISODE_CLOSE_AFTER`, `ANOMALY_SCORE_TIMEOUT_S`, `ANOMALY_SERVER_SIDE`, `AQUEDUCT_TEMPORAL`, `ARTIFACT_COMPAT`, `ARTIFACT_PROFILE`, `ARTIFACT_VERIFY`, `CLIENT_ERRORS_MAX_BYTES`, `CLIENT_ERRORS_RATE_LIMIT`, `CLIENT_ERRORS_REPORT_KEY`, `FALLBACK_TRAIN_TIMESTEPS`, `OPTIMIZER_CANDIDATE_DIR`, `PHYSICS_VERSION`, `RUN_RESULT_TTL_SECONDS`, `SIM_STEP_SECONDS`, `SITE_TIMEZONE`, `SQL_ECHO`, `WEBHOOK_ALLOW_HTTP`, `WEBHOOK_ON_SIMULATED`, plus load-test and smoke-test script variables (`LOAD_*`, `SMOKE_*`, `GIT_SHA`, `GIT_DIRTY`).

## Dead code removed (nothing in the repo referenced it, including tests)

`api/plugins/performance.py::get_cache`; `api/repositories/proposal_repository.py::get_proposal`; `api/repositories/facility_repository.py::get_pose_as_of`, `list_poses`, `list_sensors_for_asset`; `api/repositories/data_repository.py::save_sensor_reading` (the bulk writer is the one in use); from my own Task 28 code, `src/work_orders.py::can_read` and the unused `UNSET` alias in `work_order_repository.py` (one test line updated). Kept: `src/economics/tariff.py::rate_for_hour` (only a test uses it). No orphaned import was left behind (re-scanned).

## Remaining non-passes and open items (precise)

1. **`docs/api/openapi.json` and `docs/api/README.md` do not exist in this repository copy**, so `tests/test_task9_api_reference.py` (6 tests) fails in any environment until `python scripts/gen_api_reference.py` is run with the dependencies installed and `docs/api/` is committed. The new endpoints (capacity, carbon schedule, fleet, maintenance, economics, whatif sweep and the rest) will appear when it is regenerated. I could not run it.
2. **`npm run verify` (typecheck, `eslint --max-warnings 0`, vitest, build) was not run.** No `.tsx` file written in Tasks 26 to 30 has been parsed or type-checked by a real compiler. Treat the first `npm run verify` as the real test of the frontend.
3. **Full `pytest -q` was not run.** The 76 non-passes under the stand-in, by cause: missing `fastapi` (10 sampled), `gymnasium` (5), `prometheus_client` (2), `bcrypt` (1), `httpx` (2 in the torch-less boot test), `alembic` (3 in `test_facility_migration.py`, which shells out to it), the cleaned weather CSV absent from this ZIP (`data/cleaned/weather_open_meteo.csv`), `pytest.MonkeyPatch` / `mark.skipif` / async fixtures unsupported by the stand-in. **Not confirmed either way** (could be real, could be the stand-in): 26 in `test_artifact_gate.py` and 6 in `test_artifact_integrity.py` (a PPO artifact format is refused here; likely needs the RL stack), 4 in `test_repro_framework.py` (subprocess and git based).
4. **`alembic check` (ORM equals migrations) and the SQLite upgrade/downgrade tests** (`test_alembic_chain.py`, `test_task28_migration.py`, `test_facility_migration.py`) were not run: Alembic and SQLAlchemy are not installed here.
5. `docs/env/Task1.md`, `Task5.md`, `Task7.md`, `Task9.md` are referenced but missing (see item 6 above).
