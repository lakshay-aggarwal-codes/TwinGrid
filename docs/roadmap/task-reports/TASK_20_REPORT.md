# Task 20 — ML-005 Carbon "assumed" label guard          Status: PARTIAL
Base: TwinGrid-main.zip as uploaded (no git history; owner's working copy not checked)     Date: 2026-10-21
Environment: Python 3.12.3, numpy/pandas/reportlab present; NO pytest, ruff, fastapi, gymnasium, node; no network.

## Summary
New `src/carbon_label.py` gives one label with four statuses (`real_fresh`, `real_stale`, `unavailable`, `assumed_fallback`), each with
source, region, timestamp, unit, is_real. "Real" requires a dated, documented (average/marginal), complete series. A phrase guard
(`unsupported_carbon_claims`) blocks claims like "carbon-optimal" / "saves CO2" when the label is not real. ESG report and run export
now follow the label.

## Acceptance checklist
- Four cases covered, each with source/region/timestamp/unit/is_real -> met -> `tests/test_carbon_label_guard.py` (4 case tests + undated/undocumented/future/missing-hours).
- No unsupported carbon claim reachable -> partly met -> guard test over generated report text (ESG section, run export, `format_carbon_reduction`) and a scan of served frontend/API sources found none. NOT met for API payloads: they still carry only the legacy `carbon_data_is_real` boolean (see limitations).
- `docs/CLAIMS.md` carbon rows only -> met -> row C-04 only.

## Changed files
- CREATE `src/carbon_label.py` — label + claim guard (small new module; not in the card's "Owns" list, needed so there is one label).
- CREATE `tests/test_carbon_label_guard.py` — 27 test cases.
- MODIFY `api/services/esg_report_service.py` — `carbon_report_section(state, carbon_label=None)`: label overrides the flag; stale series gets a STALE warning with source/region/date; `generate_report` loads the label when the flag says real.
- MODIFY `src/run_export.py` — "marked REAL by the run" -> states the run record has no source/region/date and makes no carbon-saving statement.
- MODIFY `docs/CLAIMS.md` — C-04 only.
- CREATE `docs/roadmap/task-reports/TASK_20_REPORT.md`.

## Commands run (sandbox, pytest replaced by a tiny local shim — NOT real pytest)
- new tests: 27 passed, 0 failed
- tests/test_task11_data_truth.py 10 passed; tests/test_run_export.py 19 passed; tests/test_truth_copy.py 2 passed; tests/test_task33_claims.py 8 passed (first run failed on the word "optimal" in my CLAIMS wording; reworded).

## Pre-existing failures observed
None observed.

## Not run / blocked
- Real pytest, `ruff check .; ruff format --check .`: not installed here. Commands below.
- tests/test_carbon_is_real_flag.py, tests/test_carbon_signal_task8.py: need fastapi / gymnasium (missing here); I did not change what they cover.
- Frontend checks: no frontend files changed; not run.

## Decisions and defaults used
- Freshness window: `CARBON_SERIES_MAX_AGE_DAYS`, default 90, measured from the sidecar `retrieved_at`. Stale real data stays `is_real=true`, labelled stale.
- Did not add keys to `/api/state`, `/api/whatif` or the WebSocket payload: golden files (`tests/golden/*`) hold those payloads and are not owned by this task.
- Legacy `carbon_data_is_real` unchanged: `tests/test_carbon_is_real_flag.py::test_real_csv_is_reported_as_real` expects True for an undated CSV.

## Requested cross-task changes
Surface `current_carbon_label()` in `/api/state`, `/api/whatif` and the WS tick (and update goldens), then have the frontend show `ui_label`. Owner of the payload/golden files should do it.

## New limitations or risks
An undated/undocumented CSV still gives `carbon_data_is_real=true` in API payloads and the UI ("Grid Carbon Intensity"); only the ESG report and run export apply the stricter rule. No carbon file ships, so this is not reachable today.
The phrase guard is a regex list, not proof against every wording.

## Next tasks unblocked
None.
