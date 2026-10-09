# G-SCN real backend run

**Git HEAD:** `ccfd58c24ebc90ff1ea725f1b9c5fbec6cf0415a`
**Branch:** `wip/bc09-scenario-registry` (clean working tree)

## Step results

| Step | Check | Result | Observed |
|------|--------|--------|----------|
| 1 | `git status -sb` | PASS | `## wip/bc09-scenario-registry...origin/wip/bc09-scenario-registry` |
| 1 | Three contract files present | PASS | `api/services/scenario_registry.py`, `api/routes/scenario_routes.py`, `api/routes/digital_twin_routes.py` |
| 1 | SHA256 vs G-SCN.md Capture 1 | PASS | `scenario_registry.py` = `132742b9930286e84ac054be45ed87b54a39255bdff5a7ffb26d9743a51ee82f`; `digital_twin_routes.py` = `ee173723e5a141cdbd03b62566aa96dad2efac97fdab2170aca7ee9f4f54df4b`; `scenario_routes.py` = `8f010b71129a5dd802a4ad68398092a1a978964a9cc46a39f66d443b0dc6f0c2` |
| 2 | `.env` present | PASS | Already present (not copied from `.env.example`) |
| 2 | `ENVIRONMENT=development` | PASS | Set |
| 2 | Random hex secrets configured | PASS | `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `JWT_SECRET_KEY`, `METRICS_TOKEN` set (values not recorded) |
| 2 | `.env` gitignored | PASS | Listed in `.gitignore` |
| 3 | `docker compose down -v` | PASS | Completed |
| 3 | `docker compose build` | PASS | Exit code 0 |
| 3 | `docker compose up -d` | PASS | Backend, worker, db, redis started |
| 3 | `GET /healthz` within 120s | PASS | `200` — `{"status":"ok","database":"ok",...}` |
| 4 | Register `gscn-check` | PASS | `POST /auth/register` → `200` (new user) |
| 4 | Login JSON + token in session only | PASS | Login succeeded; access token not written to disk or this doc |
| 5 | `GET /api/scenarios` capture | PASS | HTTP `200`; saved via `curl.exe -o real-scenarios.json` |
| 5 | Parsed JSON vs `G-SCN.capture-scenarios.json` | PASS | Deep equality (`r == c`) after UTF-8 curl capture |
| 5 | `GET /api/whatif?scenario_id=whatif-heat-wave` capture | PASS | HTTP `200`; saved via `curl.exe -o real-whatif.json` |
| 5 | Top-level keys vs `G-SCN.capture-whatif-heat-wave.json` | PASS | Same set: `basis`, `carbon_data_is_real`, `drought_override_active`, `final_cooling_mode`, `hours`, `inputs`, `max_outlet_temp_C`, `mean_pue`, `scenario_id`, `total_co2_kg`, `total_energy_kwh`, `total_water_L`, `wue` |
| 6 | No token → `/api/scenarios` | PASS | `401` |
| 6 | No token → `/api/whatif` | PASS | `401` |
| 6 | `scenario_id=nope` | PASS | `404` |
| 6 | `whatif-heat-wave&outside_temp=99` | PASS | `422` |
| 6 | `whatif-heat-wave&outside_temp=30` | PASS | `200`; `inputs.outside_temp_C` = `30.0` |
| 7 | Targeted pytest files | FAIL | `894 passed`, `2 failed` — `test_metrics_exposes_prometheus_text` (401 vs 200 on `/metrics`); `test_orm_matches_migrations_no_autogenerate_diff` (alembic check drift) |
| 7 | `pytest -q` (full suite) | FAIL | Collection error: `1` — `tests/test_provenance_m1.py` — `ImportError: cannot import name 'ORIGIN_SIMULATED' from 'src.versions'`; suite did not finish |

## Deviations from the original backend

This checkout was already repaired before this run (no source edits during G-SCN capture):

1. **Reconstructed physics-v2 functions in `src/versions.py`** — lineage/version helpers restored so imports and physics tests can run; not identical to a pristine upstream snapshot (e.g. missing symbols such as `ORIGIN_SIMULATED` still break some tests).
2. **Regenerated `requirements.lock`** — lockfile rebuilt without `pip-compile` hash workflow used upstream.
3. **Renumbered Alembic revisions** — migration chain adjusted; ORM vs migration drift still reported by `alembic check` in tests.

## Capture artifacts

`real-scenarios.json` and `real-whatif.json` were removed from the repo root after comparison (per runbook).
