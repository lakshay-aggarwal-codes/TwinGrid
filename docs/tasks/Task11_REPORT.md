# Task 11 - Data-truth labelling

## What changed
- **ESG report** (`api/services/esg_report_service.py`): every PDF now opens with "SIMULATED DATA ... None of it is a measurement from a real facility". The carbon row no longer says "Real"/"Flat fallback"; it says `ASSUMPTION` with the 475 gCO2/kWh world-average note, plus a bold "CARBON FIGURES ARE ASSUMED, NOT MEASURED" paragraph. Removed the wrong "regional-average" wording and the pointer to an Electricity Maps integration. New pure helper `carbon_report_section()` (unit-testable). I rendered a PDF in the sandbox and read it back with `pdftotext`: layout fits.
- **Frontend copy (5 files, 6 strings):**
  - `SustainabilityTab.tsx`: fallback line now "ASSUMPTION: a flat N gCO2/kWh world-average figure ... Not real grid data: no carbon-intensity dataset is loaded"; step-emission line adds "(modelled from the assumed intensity)"; the real-series line no longer claims "Real ... from Electricity Maps data".
  - `shell/ModeLegend.tsx`: "flat fallback figure (an assumption), not live or measured grid data".
  - `scenario/ScenarioLibrary.tsx`, `scenario/PreviewResults.tsx`: "CO2 is modelled from a flat assumed carbon intensity ... illustrative".
  - `reports/reports.ts`: omitted-carbon caveat says "assumption ... not measured grid data"; section title "Carbon (real grid data)" -> "Carbon (loaded intensity series)" (test expectations in `reports.test.ts` updated to the new title, same assertions).
  - The golden-bound caveat string in `reports.ts` is unchanged (it is baked into `src/reports/golden/*.md`).
- **Docs:** new `docs/model_cards/DATA_TRUTH.md` (real vs fallback vs synthetic, input by input, each row cites a file); `docs/DATA_LICENSES.md` (pointer + summary); `DATA_DICTIONARY.md` (`carbon_intensity.csv` was listed as an Electricity Maps product; nothing here produces it; solar marked dormant).
- `tests/test_task11_data_truth.py` (10 tests). `src/versions.py` untouched.

## Assumptions
- **NSRDB code was NOT deleted.** `solar_nsrdb.py` is dead for the product but is wired into `run_ingestion.py`, `scripts/run_ingestion.py`, `REGISTER.json` (15 entries, asserted by `test_external_register.py`) and `tests/test_ingestion.py`, and `.env.example` (Task 32 only). Removing it means editing the register and its tests, which I cannot run here. It is marked DORMANT in its docstring and in the docs, and a test proves nothing in `api/`, `src/` (outside ingestion) or `models/` reads it. Deleting it is a clean follow-up.
- API payload shapes were not changed (contract fixtures and goldens stay valid); the label travels as `carbon_data_is_real` plus the existing live-feed `carbon_signal`.
- `carbon_data_is_real: true` is treated as "loaded series", never as "live" or "real grid".

## Test results (real output)
- `tests/test_task11_data_truth.py` run with a small runner (pytest not installed): `10 passed, 0 failed`, including a real PDF build.
- Python syntax of edited files checked.

## Not verified
- `pytest`/`ruff` proper, and every existing test (`test_carbon_is_real_flag`, `test_t23_*`, `test_truth_copy`, ESG route tests); I read them and the edits do not touch what they assert.
- Frontend: `npm ci`, typecheck, lint, vitest, build (no `node_modules`, no network). I checked by reading that no existing test asserts the old strings I changed (`/not real grid data/i`, `/flat fallback figure/` still match).
