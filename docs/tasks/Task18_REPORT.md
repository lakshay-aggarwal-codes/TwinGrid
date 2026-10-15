# Task 18 report: explainability and the Model Passport

## What changed
- **Backend (read-only plugin `api/plugins/explainability.py`).**
  - `GET /api/models/passport`: one passport per artifact in `models/registry.json` (version, status, whether the API may load it,
    data origin, headline metrics, limitations, claim boundary). PPO entries carry the **stored** evaluation decision
    (for example `NOT_EVALUATED`, claim allowed `none`) with its source; nothing is implied. Rules: `src/model_passport.py`.
  - `GET /api/alerts/{id}/explanation`: score against the detector threshold, and a deterministic per-signal range deviation
    of the sensor reading linked to the alert. Rules: `src/alert_explain.py`.
- **Frontend (`src/features/explainability/`).** A "Model passport" drawer (one global instance, opened by header button, command
  "Open the Model Passport", and a button on the anomaly gauge, the optimizer card, the alert detail and a dashboard card).
  "Why did this fire?" disclosure in the alert detail. The anomaly gauge shows the detector's own per-signal breakdown while it is flagging.
  The drawer and every metric say "synthetic-data result".

## What the detector exposes, and what is computed
- While an episode is live, the detector exposes per-feature **reconstruction-error shares** (`anomaly_status.explanation`,
  `src/anomaly_explain.py`). These are shown as received (gauge, and alert detail when `episode.alert_id` matches).
- The shares need the whole 12-step window and are **not stored with an alert**. For a stored alert the page therefore shows a
  different, deterministic quantity and says so: where each of the five detector inputs of the linked reading sits inside the
  range the detector's scaler saw in training (`centre_distance`, `outside_range_by`), plus stored score / threshold.
  It is not the model's reconstruction error.

## Assumptions
- Every model is labelled `data_origin: synthetic`, from `docs/model_cards/LIMITATIONS.md` (all models trained on simulator data).
  Limitation and boundary wording is quoted from the model cards; a test pins each phrase to its card.
- The threshold used for a stored alert is the currently configured detector's (`models/anomaly/config.json`); the response says so.
- Alerts persisted without a linked reading, or readings missing an input, return `features: null` with a stated reason.
- `loadable` means the registry status is `promoted`; it does not claim the integrity check passed.
- No new env var, migration or rate-limit class (reuses `general`). No new dependency.
- Edited existing files (small additive changes, each a button or panel): `components/AnomalyGauge.tsx`,
  `components/optimization/OptimizationCard.tsx`, `features/alerts-centre/AlertDetail.tsx`.
- The "Equipment health (proxy model)" card is not given a passport button: that model is not in the registry, so a passport would misattribute it.
- The drawer uses the existing Sheet component (its slide animation is the library default).

## Test results (run here)
- `pytest tests/test_task18_explain_passport.py tests/api/test_task18_explainability.py`: 27 passed. `ruff check` and `ruff format --check` on the new Python: clean.
- Wider backend run (`pytest tests`, stopped by me at ~87% because one slow test hung): failures exist in this sandbox (for example 14 across `tests/characterization/test_route_contracts_and_targets.py`, `tests/api/test_provenance_writers.py`, `test_routes_health_metrics.py`, `test_physics_v1_api.py`); I re-ran those files with and without `api/plugins/explainability.py` and got the identical 14 failures, so they are not caused by Task 18. The rest of the run was not finished.
- `vitest src/features/explainability src/features/alerts-centre src/components/optimization src/components/AnomalyGauge`: 130 passed (incl. 42 new).
- `eslint` and `tsc` report nothing for the new/edited frontend files.

## Not verified / environment notes
- `tests/api/test_error_contract.py`: 14 tests fail in this sandbox with and without Task 18 code (empty route table with the installed FastAPI/Starlette). Not run against my routes; both new routes use `http_limit("general")`.
- The supplied repo zip has no `src/runs/` (BC-10 files), so `tsc` and many vitest files fail to import `../runs/schema`. I used a temporary stub, not shipped, to run the suites. With it, 6 tests in registry, TwinHeader, command-palette, facility-inspector and what-if-lab fail identically **without** Task 18 code (stale fixed-list assertions from earlier tasks); not touched.
- `vite build` could not load its config here; not verified.
- Not verified in a browser (no visual check at 360 px, dark/light, or with a real screen reader). The explanation table scrolls horizontally inside its own container; sheet focus handling is Radix's.
- The explanation endpoint against a real database with a real linked reading was tested only on in-memory SQLite.
