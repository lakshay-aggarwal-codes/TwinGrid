# Forecaster evaluation protocol (`forecast-eval/1`)

Written before any result was produced. `results.json` records this file's SHA-256 so a later edit is visible.
Scope: simulator data only. Nothing here says anything about real hardware.

## Question
Does the registered LSTM forecaster (`server_outlet_temp_C`, 12-step input window of 10 features, 5-minute cadence)
predict better than simple forecasters that need no training or only a linear fit?

## Data and split
- One gap-free 300 s series (`data/raw/sensor_data.csv`, or one generated with `src.data_generator`). Missing values are
  forward-filled only. No rows are removed (the legacy pipeline removed rows with whole-file statistics).
- Chronological split by ROWS: first 80 % train, last 20 % test. The last 20 % of the train rows is the validation block
  used only to choose baseline hyper-parameters, then everything is refit on all train rows.
- A window is in a split only if its input rows and its target row are all inside that split's rows.
- The test rows are scored once per model, after all choices are fixed.

## Models
Baselines (use only rows at or before the origin): `persistence`, `moving_average` (window from {3, 6, 12}, chosen on
validation), `seasonal_naive` (same time 24 h earlier), `seasonal_delta` (persistence plus the change the series made
24 h earlier over the same horizon), `ridge_window` (ridge regression on the same 12 x 10 window, alpha from a fixed grid
chosen on validation, scaler fitted on train rows). Learned: the registered LSTM recipe, at least 5 seeds, scaler
fitted on train rows, one model per learned horizon.

## Metrics
- Horizons 1, 3 and 6 steps for baselines; the LSTM only at horizon 6 (the horizon it is registered for).
- RMSE and MAE in °C. 95 % intervals by moving-block bootstrap (block 72 rows, 2000 resamples, fixed seed) because
  consecutive errors are correlated. LSTM: mean, sd, min, max over seeds.
- Regimes (thresholds from train rows only): utilisation tertiles and ramping vs steady (change in utilisation over the
  last 3 steps against the train 75th percentile).

## Decision rule (primary: RMSE at horizon 6)
Comparator = the baseline with the lowest test RMSE (chosen after the fact, which is the strict choice).
Delta = mean over seeds of the LSTM's RMSE minus the comparator's RMSE, on identical resampled blocks.
- 95 % interval entirely below 0: `model_better`
- entirely above 0: `model_worse`
- otherwise: `inconclusive`
- learned model not run: `unevaluated`

Only `model_better` allows the sentence "the forecaster beats the best simple baseline on simulator data".
Any other verdict is reported as it is and the card says so.

## Leakage checks (all must pass, run on every evaluation)
1. No train window touches a test row.
2. The scaler statistics equal the train-row statistics and differ from the all-row statistics.
3. Scrambling every row after an origin changes no baseline prediction and no input window.

## Known limits
Early stopping uses Keras' `validation_split`, the last 20 % of the train windows, which overlap their neighbours; this can
only affect model selection, never the test rows. One simulated series, one cell of the generator; not real hardware.
