# Task 12 (roadmap): anomaly detector, validation-only thresholds and event-level metrics: PASS 1

(Named `Task12_anomaly_eval_REPORT.md`: `Task12_REPORT.md` is the earlier command-palette task.)

## Finding: the code half of this task already exists in the uploaded tree
Verified by reading the code, not assumed:

| Roadmap question | Verdict | Evidence |
|---|---|---|
| Is the served threshold chosen on validation only? | **Code: yes. Shipped artifact: NO.** `notebooks/train_all.py` now splits 60/20/20, picks the threshold with `ae.select_row_threshold(..., split_id="validation")` and scores held-out rows once. `scripts/train_anomaly.py` does the same at event level with `OneShotEvaluator` (test read once). But `models/anomaly/config.json` (threshold 0.01222879, percentile 99.5) has **no `fit_split_id`** and predates the fix; per the model card its percentile was searched on the held-out rows it was scored on. It has not been retrained. | `notebooks/train_all.py` L136-196, `scripts/train_anomaly.py` L10-11, `models/anomaly/config.json` |
| Does the threshold rule refuse non-validation data? | Yes: `LeakageError` for any split id other than `validation`; a test asserts it and that the choice is independent of held-out scores. | `src/anomaly_eval.py::select_row_threshold/select_threshold`, `tests/test_anomaly_threshold_discipline.py` |
| Event-level metrics (delay, false alarms/day)? | Exist and are exact on hand-made series: event recall with Wilson 95% CI, detection delay (median/IQR, minutes), false-alarm episodes per simulated day, event precision, row-level kept but labelled "diagnostic only"; MIN_EVENTS=30 stop condition. | `src/anomaly_eval.py`, `tests/test_anomaly_eval.py` |
| Circularity (same generator injects and evaluates)? | **CONFIRMED as a scope limit, not leakage**: detector trains on normal rows only, but only two injected types (`leak`, `thermal`) with fixed signatures in every split. Already stated in the model card's claim audit. | `docs/model_cards/anomaly_detector.md`, `src/data_generator.py::inject_anomalies` |
| Has the event-level evaluation ever been run on a model? | **No.** No `reports/anomaly_candidates/` exists; `configs/anomaly/anomaly_v2.json` has `caps_status: PROPOSED_UNCONFIRMED`, and `train_anomaly.py` refuses to read the test split until it is `preregistered`. | file listing, `require_preregistered` |
| Does the API/UI say how the served threshold was chosen? | No: nothing outside the detector reads `fit_split_id`; a legacy artifact reports no fit split. Not changed here (it would alter an API contract); listed as a risk. | grep `fit_split` over `api/`, `src/` |

## Why no code change this round
Every roadmap code item is present and tested. Adding more would duplicate or loosen existing gates. The remaining work needs your machine and one decision from you, so it is a human gate.

## What stands between you and a real result
1. **TensorFlow environment** (the detector). Not available in the sandbox.
2. **Dataset v2 does not exist yet.** `data/datasets/` is absent and `data/cleaned/` holds only a README (no `weather_open_meteo.csv`, no `water_stress_aqueduct.csv`). `scripts/make_datasets.py` refuses missing inputs unless `--allow-synthetic-weather` / `--allow-synthetic-water-stress`, which are then recorded in the manifest as `synthetic_inputs`, and `train_anomaly.py` then also needs `--allow-synthetic-inputs`. The result is still "synthetic anomalies in simulator output" either way, and the report will say which inputs were synthetic.
3. **Pre-registering the caps.** Proposed values: K=3 rows (15 min), false-alarm cap 2 episodes/simulated day, alert-row cap 5% of rows (about 14 rows/day at 5-minute cadence), 6-row (30 min) detection tolerance. My view: acceptable as simulator-only caps, but 2 false alarms/day would be too many for a real operator, so any real-site claim needs tighter caps and real data. Set `caps_status` to `preregistered` **before** the run, once, after reading the numbers; changing them after seeing the result invalidates it.
4. `make_datasets.py --plan-only` must show at least 30 events in validation and in test, else `InsufficientEventsError` stops the run (raise injections, never loosen the minimum).

## Tests run
Sandbox (Linux, numpy only, no pytest/TensorFlow, run with a small pytest-shim runner): `tests/test_anomaly_threshold_discipline.py` 6/6 passed; `tests/test_anomaly_eval.py` 87 passed (shim). NOT run: `tests/test_anomaly_detector.py`, `tests/test_train_anomaly.py` (TensorFlow), anything on your machine, any training.

## Remaining risks
- The served detector's F1 0.96 / precision 0.923 / recall 1.0 remains the optimistic figure; do not quote it.
- No event-level result exists for any model.
- The shipped model is still under the `legacy-0-physics-until-T26` compatibility waiver.
- Synthetic anomalies only, two fixed fault types.
