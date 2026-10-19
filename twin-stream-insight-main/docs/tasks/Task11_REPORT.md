# Task 11 — Forecasting baseline and leakage audit

**Result in one paragraph.** The forecaster's data pipeline does **not** leak the scaler or use random splits, but its train/test
boundary overlaps by 17 rows, its outlier filter is computed on the whole file, and it silently breaks the 30-minute horizon for
about 3% of windows. A persistence / seasonal-naive baseline now exists on the forecaster's own split and metric
(`scripts/forecast_baselines.py`), but **whether the registered LSTM beats it is NOT VERIFIED**: the file the model was scored on
is not in the repo, the current data generator does not reproduce it, and TensorFlow is not in the sandbox. The model card keeps
saying there is no baseline result.

Environments: **[SB]** = Claude's sandbox (Python 3.12.3, numpy 2.4.4, pandas 3.0.2, scikit-learn 1.8.0, no TensorFlow, no pytest,
no FastAPI); **[repo]** = read from the files in the uploaded zip. Nothing below was run on the owner's machine.

## 1. Problem
`docs/model_cards/forecaster.md` reports RMSE 0.523 °C / MAE 0.421 °C and admits "no baseline". The roadmap asks whether a
persistence / seasonal-naive baseline exists on the same split and metric, and whether there is future-information leakage.

## 2. Evidence: each claim

| # | Claim | Status | Evidence |
|---|---|---|---|
| 1 | A persistence / seasonal-naive baseline exists on the same split and metric | **CONFIRMED absent** (before this task) | [repo] `grep` for persistence / seasonal in `src`, `scripts`, `notebooks`, `api` finds only unrelated uses (DB persistence); `ML_DOCUMENTATION.md` line 7 called it a follow-up |
| 2 | Scaler is fitted on all data | **REFUTED** | [repo] `DataPipeline.prepare` fits `MinMaxScaler` on `X_train` only; test `test_scaler_is_fit_on_train_windows_only` plants a spike far into the test period and checks it never reaches `scaler.data_max_` |
| 3 | Random split of a time series | **REFUTED** | [repo] split is by position (`split_idx = int(n * train_ratio)`); `test_no_random_split_of_the_time_series_in_the_forecaster_path` scans `src/lstm_model.py` and `notebooks/train_all.py` for `train_test_split`, `shuffle=True`, `KFold`, `ShuffleSplit`. Keras `validation_split` takes the last fraction of the time-ordered training arrays (code-evident, not run: needs TensorFlow) |
| 4 | Rolling / derived-from-future features | **REFUTED** | [repo] the 10 features are raw columns; no rolling, ewm, shift or diff anywhere in `src/lstm_model.py` |
| 5 | Backward fill leaks the future | **REFUTED** (one benign exception) | `load_csv` does `ffill().bfill()`: after ffill the only NaN left is a leading one, so a gap in the middle takes the PREVIOUS value. `test_forward_fill_never_uses_a_later_value_in_the_middle_of_the_series`. Only the first rows of the series can take a later value |
| 6 | Timestamp ordering | **CONFIRMED with one gap** | `load_csv` sorts by time when `timestamp` exists (`test_unsorted_input_is_ordered_by_time_before_windowing`). **Defect TG-T11-2:** duplicate timestamps are accepted (strict xfail `test_duplicate_timestamps_are_rejected_at_load`) |
| 7 | Split boundaries strictly ordered | **REFUTED: defect TG-T11-1** | Windows are built over the whole frame, then split by position, so the first `seq_len + horizon - 1` = **17** test windows read rows the last train windows also read. [SB] measured 17 shared rows on regenerated data; `test_legacy_split_overlaps_by_seq_len_plus_horizon_minus_one` pins it for four (seq_len, horizon) pairs; strict xfail `test_default_split_boundaries_are_strictly_ordered`. Effect on persistence RMSE [SB]: 0.8859 → 0.8855 with the gap removed (negligible; **effect on the LSTM not measured**) |
| 8 | Duplicate windows across splits | **REFUTED on regenerated data [SB]; NOT VERIFIED on the registered file** | 0 identical input windows in both splits; 0 duplicate timestamps. `test_no_identical_windows_in_both_splits_and_the_check_can_fail` proves the detector can fail |
| 9 | Outlier filter uses only train information | **REFUTED: defect TG-T11-3** | `load_csv` computes mean/std over the whole file, so a train row's keep/drop decision depends on later rows. Strict xfail `test_outlier_decisions_for_train_rows_do_not_depend_on_test_rows` (same row dropped alone, kept with test rows: verified). [SB] on regenerated data: 302 rows decided differently (25 of them train rows); test rows dropped: 27 with whole-file thresholds vs 304 with train-only thresholds. Direction of any bias on the score: not determined |
| 10 | Windows are 30 minutes ahead | **REFUTED: defect TG-T11-4** | The outlier filter drops rows before windowing, so some windows span a time gap and their target is later than the documented horizon. [SB]: 746 of 25,819 windows (2.9%): 346 train, 400 test. Strict xfail `test_windows_are_time_contiguous_after_outlier_removal` |
| 11 | The evaluation includes the anomalies | **REFUTED** (mechanism CONFIRMED) | The same filter removes extreme rows. [SB]: 84 rows dropped, 41 of the 57 labelled anomaly rows (72%) |
| 12 | The target is also an input | **CONFIRMED** | [repo] `DEFAULT_FEATURE_COLUMNS` contains `server_outlet_temp_C` = `TARGET_COLUMN`, so "same as now" is a strong baseline |
| 13 | Registered model beats persistence | **NOT VERIFIED** | See section 6 (BLOCKED) |
| 14 | Registered RMSE 0.523 / MAE 0.421 reproduce | **NOT VERIFIED** | Same |
| 15 | The training data is available | **REFUTED** | `data/raw/sensor_data.csv` is not in the zip. The regenerated file [SB] does not hash to the registry's `dataset_sha256` (11f3d473…), with LF or CRLF line endings. The registry records physics `legacy-0`; the generator now defaults to physics 1 |
| 16 | The training script can regenerate it | **REFUTED** | [repo] `notebooks/train_all.py:83` calls `generate_sensor_data(days=90, seed=42)`; [SB] that call raises `MissingInputError` (needs the cleaned weather file or `allow_synthetic_weather`). Not fixed here (out of scope), flagged below |

**Baseline numbers [SB], on regenerated synthetic data that is NOT the registered model's data (legacy split, 5,164 test windows):**

| Method | RMSE °C | MAE °C | n |
|---|---|---|---|
| persistence | 0.8859 | 0.6534 | 5,164 |
| seasonal-naive (24 h, by timestamp) | 1.1655 | 0.8305 | 5,141 (coverage 99.6%) |
| train-mean | 2.6533 | 2.3024 | 5,164 |

On the 5,141 windows where seasonal-naive exists, persistence is 0.8866 / 0.6536. **Do not read 0.523 against 0.8859 as "the model
beats persistence":** different data (different physics, different generator), a one-off run, and nothing here scores the model.

## 3. Decision and trade-off
- **`DataPipeline.purge_gap` (opt-in, default 0)** plus `split_windows()` returning a `WindowSplit` that records which frame rows
  each split reads. `prepare()` now scales `split_windows()`; its output is **bit-identical** to the old implementation at three
  parameter sets (checked [SB] against the original `src/lstm_model.py`). The default stays legacy because the registered model
  was trained and scored that way (`split_id` `chronological:train_ratio=0.8`), and 24 existing tests encode the no-gap counts.
  A purged split is labelled `chronological:train_ratio=0.8;purge_gap=17`. **Recommendation:** make `purge_gap=17` the default
  at the next retrain, together with the registry label.
- **Defects TG-T11-1…4 are strict xfails, not fixes.** TG-T11-1 has a fix (the option above); 2, 3, 4 are data-loading changes
  that would change which rows every model sees, so they need a decision and a retrain, not a silent edit. If one is fixed the
  strict xfail fails and says to remove the marker.
- **Model card** (`docs/model_cards/forecaster.md`): "No baseline" now says a script exists but has not been run on the model's own
  file, and a new bullet lists the protocol problems qualitatively (no new numbers; the card's rule is that numbers come from
  `EVIDENCE` lines). `tests/test_task31_model_cards.py` still passes. `ML_DOCUMENTATION.md` line 7 updated.
- **Not touched:** `notebooks/train_all.py` (claim 16), the frozen reports, the registry, any trained artifact.

## 4. Files
CREATE `scripts/forecast_baselines.py`, `tests/test_task11_forecast_leakage.py`, `tests/test_task11_forecast_baselines.py`,
`docs/tasks/Task11_REPORT.md`. MODIFY `src/lstm_model.py` (adds `WindowSplit`, `purge_gap`, `split_windows`, `split_id`,
`recommended_purge_gap`, `outlier_std`, `target_column`), `docs/model_cards/forecaster.md`, `ML_DOCUMENTATION.md`. DELETE none.

## 5. Tests run [SB]
Runner: a small pytest stand-in (pytest is not installed in the sandbox); same assertions, but it is not real pytest.
- `tests/test_task11_forecast_leakage.py`: 24 passed, 4 xfailed (strict). Each xfail body was run directly and fails on its
  intended assertion, not on an error.
- `tests/test_task11_forecast_baselines.py`: 30 passed (hand-computed metrics, timestamp look-up, gaps, registry matching, the
  TensorFlow branch with a stand-in forecaster, CLI exit codes).
- Existing, before/after: `tests/test_data_pipeline.py` 24 passed; `tests/test_task31_model_cards.py` 5 passed.
- **No-new-failures comparison** (all 93 top-level `tests/test_*.py` run under the same stand-in, unmodified zip vs modified tree):
  before 40 modules ran (1,242 passed, 491 failed, 5 skipped), 53 could not import; after 42 modules (1,296 passed, 4 xfailed,
  491 failed, 5 skipped), 51 could not import. The only differences are the two new modules. The 491 failures are identical in
  both trees and come from the sandbox (no TensorFlow / FastAPI / real pytest features), not from this change.

## 6. NOT run, and BLOCKED
- **The model-vs-baseline verdict** needs the registered model's data file and TensorFlow. Run on the owner's machine:
  `scripts/forecast_baselines.py --csv data\raw\sensor_data.csv --model-dir models\forecaster`. The script compares the file's
  SHA-256 with the registry, re-scores the model on the held-out windows, says whether that reproduces the registry metrics, and
  prints `NOT VERIFIED` instead of a verdict if anything is missing.
- Real `pytest`, `ruff check`, `ruff format --check`, pyrefly, the Keras `validation_split` behaviour: not run. The new Python
  files are not ruff-formatted.
- If the registered file cannot be found: the forecaster cannot be re-scored and, because `train_all.py` fails at the data step
  (claim 16), cannot be retrained either until that is fixed.

## 7. Remaining risks
- The registered 0.523 °C may be optimistic (boundary overlap, filtered anomalies, 3% mis-timed windows) or may not beat
  persistence at all; neither is known.
- The card's "held-out" score excludes most anomaly rows if the registered file behaves like the regenerated one.
- Sandbox numbers come from pandas 3.0.2; the owner's environment may differ.
