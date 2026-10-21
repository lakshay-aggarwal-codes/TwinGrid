# Task 19 — ML-004 Forecaster vs baselines          Status: PARTIAL
Base: the uploaded TwinGrid-main.zip (no git history).   Date: 2026-10-21
Environment: Linux, Python 3.12.3, NumPy, pandas, scikit-learn 1.8.0, pytest 9.1.1, ruff. **No TensorFlow.** `sensor_data.csv` is not in the repo.

## Summary
Added `src/forecast_eval.py`: chronological row split with no train/test window overlap, five baselines (persistence, moving average,
seasonal-naive, seasonal-delta, ridge on the same window), a multi-seed LSTM path, horizon 1/3/6 RMSE and MAE with block-bootstrap
intervals, regime breakdown, three leakage checks and a pre-declared verdict rule. Everything that does not need TensorFlow is built and tested.
The LSTM comparison has NOT been run, so the verdict is `unevaluated` and no claim of "better than baseline" is made.

## Acceptance checklist
- No single-run, unbaselined RMSE in headline copy: **partly met**. Card and C-06 row now label 0.523 as a single unbaselined run. README line 74 still states it as a claim (not mine to edit; see cross-task changes).
- Chronological split + hashes: met (`split.hashes` in results.json).
- >= 5 seeds for the learned model: implemented and enforced (`ForecastEvalError` below 5); **not run**.
- Baselines, horizon MAE/RMSE with intervals, regimes, leakage checks: met (run on a generated series, see below).
- Dataset/simulator version, params, seeds recorded: met in results.json.
- Model-worse/inconclusive handling: rule in PROTOCOL.md; card text covers it.

## Changed files
- `src/forecast_eval.py` — new. `reports/forecast_eval/PROTOCOL.md` — new. `tests/test_forecast_eval.py` — new (16 tests).
- `docs/model_cards/forecaster.md` — evaluation section, caveat. `docs/CLAIMS.md` — C-06 row only.
- `docs/roadmap/task-reports/TASK_19_PLAN.md`, `TASK_19_REPORT.md`.

## Commands run (my environment)
- `pytest tests/test_forecast_eval.py tests/test_task31_model_cards.py tests/test_task33_claims.py tests/test_task18_explain_passport.py` -> 47 passed, 1 failed. The failure is `test_task18_explain_passport.py::test_severity_rule_matches_the_pipeline_rule`: `ModuleNotFoundError: prometheus_client` (my environment lacks the backend lockfile; unrelated to this task). The 16 new tests pass.
- `ruff check` / `ruff format --check` on the two Python files -> clean.
- Smoke run `python -m src.forecast_eval --baselines-only --generate --allow-synthetic-weather --allow-synthetic-water-stress` on a 90-day series generated with SYNTHETIC weather: all leakage checks passed. These numbers are not committed and are not your data.

## Pre-existing failures observed
None in the suites I ran. The full backend suite was not run.

## Not run / blocked
- LSTM seeds: needs TensorFlow + the training CSV. Command in the reply.
- Full `pytest tests`, `pyrefly`: not run.

## Decisions and defaults used
Comparator = strongest baseline by test RMSE (strict). LSTM evaluated at horizon 6 only (its registered horizon). No outlier row removal (documented deviation).
Early stopping still uses Keras `validation_split` through `ThermalForecaster.train` (documented limit).

## Requested cross-task changes
- Task 32 / README owner: README line 74 and line 86 still headline the 0.523 figure; reword after the result exists.
- `models/registry.json` forecaster entry (Task 6 owns): set `evaluation_ref` once `results.json` exists.
- Model Passport reads the card; refresh after the real run.

## New limitations or risks
One simulated series; ridge may beat the LSTM (it did on my synthetic-weather series, which says nothing about yours). That outcome would be reported as is.

## Next tasks unblocked
None strictly; Task 17/18 are independent.
