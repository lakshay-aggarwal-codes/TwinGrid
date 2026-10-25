# R_CARBON: real carbon level for the demo (Ember India, Maharashtra)

**Verdict: PARTIAL** (code and tests written; the owner's pytest run and the install on the owner's machine are open).

## Decision (owner, 2026-10-25)
Use Ember's India monthly state data (Maharashtra, Mumbai site) as a real carbon LEVEL, and say plainly that it has no time-of-day shape.
Electricity Maps hourly (IN-WE) was not obtainable (free API: latest + 24 h only; the free dataset download did not work), so it is not used.

## What the data is
- Ember "India Electricity Data", monthly, long format, state Maharashtra, series `Power sector emissions / CO2 intensity` (gCO2/kWh).
  Owner's check: 83 months, 2019-01 to 2025-11, no empty cells. Licence stated on Ember's page: CC-BY-4.0 (attribution: Ember).
- Generation-based, CO2 only, imports not counted. Labelled `average`, never marginal.
- One value per month. The provider needs hourly rows, so each month is repeated for every hour. Result: a real level, **flat across the day**.

## Changes
- `scripts/make_carbon_from_ember_india.py` (new): reads the raw file, writes a staging CSV + provenance JSON under `data/raw/carbon_staging/`; installs nothing.
- `src/carbon_provider.py` (patch): `time_varying_signal` is now false when the hour-of-day curve is flat; the statement adds "Every hour of the day has the same value, so it carries no time-of-day shape." Without this, the label would have claimed a time-varying signal for a flat curve.
- `tests/test_carbon_ember_india.py` (new): 9 tests.
- Unchanged: `src/carbon_ingest.py` (validates and installs), `src/carbon_schedule/windows.py` (already reports "no variation" for a flat curve).

## Checked here (no pytest in the sandbox; a small stand-in runner was used)
- New tests: 9 pass with the fix. Against the original provider, exactly one fails (the flat-curve label test), for the stated reason: it claimed time-varying.
- NOT run here: the existing carbon test files (`test_carbon_signal_task8.py`, `test_t23_carbon_aqueduct_contracts.py`, `test_task27_carbon_schedule.py`, `test_carbon_label_guard.py`, `test_carbon_is_real_flag.py`). Their varying-series data still gives `time_varying_signal` true, so I expect no change, but that is unverified.

## Open
- Owner runs the tests, the converter on the real file, and `src.carbon_ingest install` (commands in the chat).
- The demo container does not see `data/cleaned/` (`.dockerignore`); until a read-only mount is added, the demo still shows the flat 475 assumption.
- Wording for docs and UI: "Maharashtra 2025 monthly average (Ember), repeated for every hour; no time-of-day shape". Do not write "hourly" or "time-varying".
