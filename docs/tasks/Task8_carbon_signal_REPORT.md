# Task 8 (TwinGrid roadmap) — Carbon signal: load once, label honestly, ingestion hook

> `docs/tasks/Task8_REPORT.md` already exists in the repo (a different task list) and is NOT touched.

## (a) Root cause of the repeated warning — CONFIRMED from code, reproduced in the sandbox
`src/carbon_provider.py::_signal_and_curve` memoised the signal only when the file existed
(`key = _content_key(...) if src.exists() else None`; the comment said "A missing file is never cached"). With no
`data/cleaned/carbon_intensity.csv`, every call went to `_load_carbon_signal_uncached`, which logs
"... not found -- using the flat assumed intensity of 475 ...". Callers that run it per object: `DigitalTwin.__init__`
(`load_diurnal_carbon_intensity`), `DataCentreEnv.__init__` and `optimizer.py` (`load_carbon_signal`), i.e. once per
scenario/episode in a tune or evaluation run. Measured here (Linux sandbox, file absent): **200 `DataCentreEnv`
constructions -> 200 warnings before, 1 after.** I could not read your `retune_*.txt` (not uploaded; also the zip's
copies contain no such lines), so that this is the cause of *your* hundreds is inferred, not observed.

Fix: the fallback is memoised under a `("missing", path, zone, site tz)` key (one `stat` per call); a file that appears
later gets a content key and is read, so nothing goes stale; the warning is emitted once per (path, zone) per process
(`_claim_missing_warning`); `clear_carbon_cache()` resets both. Warnings for zone-not-found, dropped rows, unknown
semantic and missing hours were already once-per-content-key.
Wall time of `tune` before/after: **not measured** (no run here, no data).

## (b) Ingestion path — new `src/carbon_ingest.py`, `docs/CARBON_INGEST.md`
CLI `python -m src.carbon_ingest validate|install`. Schema, checks and refusals are listed in the module docstring and
the doc. Installs `data/cleaned/carbon_intensity.csv` plus the sidecar the loader already reads (semantic, source_version,
retrieved_at, license_ref, resolution_s) with extra audit keys (source, unit, csv_sha256, rows, first/last_utc). `is_real`
is not set by this module: the loader derives `is_fallback=False` only when a file loads with all 24 site-local hours
covered. No carbon data is created or bundled; test data is generated inside the tests. Not checked: correctness of the
values, the licence, the truth of the declared semantic.

## (c) Flag propagation — audit result
Producers of carbon numbers and their label: twin state/what-if (`carbon_data_is_real`), `live_broadcast_service`
(`carbon_is_fallback`), `optimization_service` (`carbon_is_fallback`), `run_service`, `economics`, `fleet`,
`esg_report_service`, `whatif_sweep`, `optimizer_proposals.predicted_effect`, env/optimizer (`carbon_basis`), baselines
and policy-evaluation results (`carbon.is_real`). Every one I found carries a flag; I changed none. I did NOT add
`is_fallback` to `results.json` (`policy_evaluation.py` "carbon" block): that would alter the frozen result schema and
hashes; `is_real` already encodes it. Test: `test_the_fallback_flag_reaches_every_label_that_carries_carbon` plus the
existing `test_carbon_is_real_flag.py`. This is a grep audit plus tests on the env/provider labels, not an exhaustive
runtime check of every endpoint.

## Files
MODIFY `src/carbon_provider.py`, `tests/test_task24_perf.py` (one test).
CREATE `src/carbon_ingest.py`, `tests/test_carbon_signal_task8.py` (35), `docs/CARBON_INGEST.md`, this report.
`test_task24_perf.py::test_missing_file_still_returns_the_labelled_fallback_and_is_not_cached` asserted the exact
behaviour that caused the defect; it is now `..._is_memoised_once` and still asserts the labelled fallback.

## Tests (Linux sandbox, Python 3.12.3; not your machine)
* New file: 35 pass; on the unmodified provider 3 fail (warn-once, load-once, per-zone warn-once), 32 pass (validation
  tests that do not depend on the provider).
* Fixed-seed episode (`DataCentreEnv`, seed 3, 12 steps) identical with the cache cleared each time vs warm cache.
* Full suite (`tests`, ignoring `test_runs.py`, `test_t27_env_v2.py` which need torch, and my new files), comparing the
  unmodified zip with my tree (which also contains Task 3): before 85 failed / 4338 passed / 2 collection errors;
  after the Task 24 test update 85 failed (the one extra failure was the test above, now updated) — identical sorted
  failure list otherwise. The 85 failures + 2 errors are pre-existing and environment/provisional-config related; I did
  not root-cause all of them.

## Not run
Your machine, TensorFlow/torch tests, Postgres, a real tune, any real carbon file, the frontend.

## Remaining risks
* Consumers still reduce the series to a 24-point hour-of-day mean (`aggregation=diurnal_mean`): no dated time series
  reaches the simulator.
* Multi-zone files are averaged unless a zone is requested.
* The memo is per process; multiple workers each warn once.
* Carbon stays the flat 475 assumption until you supply and install a file. Nothing here makes a carbon claim valid.
