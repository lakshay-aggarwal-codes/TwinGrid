# T0b report — claims and security stop-gap

Task: T0b (roadmap section 7). Static copy and one error-body change only. No physics, numeric output, DB, registry or service change.

## 1. Changed files (relative to the T0 snapshot)

Production:
- `api/routes/health_routes.py` — `/healthz` 503 body is now `{"detail": "Service unavailable"}`; the exception is logged server-side (`logger.exception`).
- `models/optimizer/config.json` — `patent_objective` text no longer says "real grid carbon"; it states the flat 475 gCO2/kWh fallback.
- Frontend copy only (`twin-stream-insight-main/src/`): `components/shell/TwinHeader.tsx` and `components/DashboardHeader.tsx` (temporary "SIMULATED — no measured telemetry" banner, `data-testid="simulated-banner"`); `components/shell/OperationsConsole.tsx` ("Experimental — simulator-only" badge and text); `components/DashboardSidebar.tsx` and `components/WhatIfTab.tsx` ("AI optimizer" wording); `components/SustainabilityTab.tsx` (carbon title depends on `carbon_data_is_real`); `reports/reports.ts` (section title).

Tests:
- New: `tests/test_truth_copy.py`, `components/SustainabilityTab.test.tsx`, `components/shell/TwinHeader.test.tsx`, `components/shell/OperationsConsole.test.tsx`.
- Updated: `tests/api/test_routes_health_metrics.py` (503 body assertions); `tests/characterization/test_route_contracts_and_targets.py` (healthz legacy test removed, strict xfail promoted to a normal test).

## 2. Corrections made when completing T0b

1. The optimization label had been written to a stray `OperationsConsole copy.tsx`; the real `OperationsConsole.tsx` was unchanged. The edit now lives in the real file and the copy is deleted.
2. T0 healthz tests flipped as the contract requires: `test_healthz_today_echoes_the_raw_exception_text` (legacy) deleted; `test_healthz_503_body_contains_no_raw_exception_text` no longer xfail.
3. Out-of-scope changes reverted to the original snapshot: `Dockerfile`, `netlify.toml`, `nixpacks.toml`, `.github/workflows/ci.yml`, `requirements.txt`, `requirements.lock`, `twin-stream-insight-main/package.json` and `package-lock.json` (Node `engines` field), `detailed_dataset_report.txt`, `generate_dataset_report.py`; removed `.nvmrc` and `twin-stream-insight-main/T0b.diff`.

## 3. Acceptance criteria

| Criterion | Status |
|---|---|
| healthz xfail flips to pass | Met by construction (xfail removed; handler returns generic body). **Not executed** |
| Test fails if "real grid carbon" is served/rendered while fallback | Test present (`tests/test_truth_copy.py`). **Not executed** |
| Frontend tests assert banner and experimental label | Present (TwinHeader, OperationsConsole, SustainabilityTab). **Not executed** |
| Goldens unchanged | No file under `src/` or `api/services/` changed; golden source SHA-256 values still match. Golden tests **not executed** |

## 4. Not run (sandbox has no network; pytest, fastapi, node_modules unavailable)

Run locally and compare:
```
python -m pytest tests/characterization -q
python -m pytest -q
cd twin-stream-insight-main; npm ci; npm test; npm run typecheck; npm run lint
```
Expected for the characterization suite: previous 37 passed / 4 xfailed becomes 37 passed / 3 xfailed (legacy healthz test removed: -1 passed; healthz xfail promoted: +1 passed, -1 xfailed) (T2, T3, T1a targets remain). This is derived, not measured.

Static checks done: `py_compile` of all changed Python files; `config.json` parses; tests' component props match the real component interfaces.

## 5. Tree hash (python -m tests.characterization.tools.tree_hash)

Post-T0b: `c471b5795436323b224772f569a1780d08f6cbcb191bb67675ee6f66da035b56`. It differs from the T0 hash by design (health_routes.py, optimizer config.json, frontend copy).

## 6. Findings, not fixed (out of T0b scope)

- `src/optimizer.py:572` writes "C = real grid carbon emissions" into `config.json` whenever a model is saved; retraining would reintroduce the claim. `test_truth_copy.py` scans only the config and frontend, so it would not catch the source. Address in the task that owns `optimizer.py` (T6/T7).
- `detailed_dataset_report_v2.py` is an untracked addition present in the codex ZIP, not part of T0b; kept untouched, owner to decide.
- No `.git` directory, so no commit hash.

## 7. Rollback

Revert the files in section 1. No data, schema or config involved.
