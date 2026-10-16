# Model Card: Anomaly Detector (Autoencoder)

**Status in the registry: `promoted`, under a named compatibility waiver, with no evaluation record.** The headline F1 below
was produced with a threshold tuned on the same rows it is scored on, so it is an optimistic figure, not a generalisation
estimate. Machine-checked numbers are the `EVIDENCE` lines at the bottom.

## Intended use
Flags anomalous sequences of 5 sensor features (`water_flow_lpm`, `water_pressure_bar`, `server_outlet_temp_C`, `it_power_kw`,
`humidity_pct`) by reconstruction error. Backs `/api/anomaly_score` and the live dashboard's alert stream.

## Training data and split
`sensor_data.csv` (see the forecaster card), 90 days of simulator-generated data. Trained on the normal-only rows
(`anomaly == 0`) of the first 20736 rows; the last 5184 rows (rows 20736 to 25920) are the held-out part. The file is not
shipped in this repository copy; the registry records its SHA-256.

## Results (held-out rows, simulator data)
- F1 0.96, precision 0.923, recall 1.0, from `notebooks/train_all.py`.
- The alert threshold (the 99.5th percentile of the held-out scores, value 0.0122) was chosen by searching percentiles for the
  best F1 on **those same held-out rows**, and the metrics were then reported on them. The threshold therefore saw the labels
  it is scored against.
- Any score quoted from before the held-out split existed came from scoring the training rows and is not comparable.

## Negative and unevaluated results
- **The newer event-level evaluation has not been run on this model.** `src/anomaly_eval.py` and `configs/anomaly/anomaly_v2.json`
  define event recall with confidence intervals, detection delay and false alarms per day, with the threshold chosen on a
  validation split. The config's `caps_status` is `PROPOSED_UNCONFIRMED`, the registry entry has no `evaluation_ref`, and no
  result report for it exists in `reports/`. The 0.96 above is not that metric.
- **Tiny positive class.** True anomalies are a very small share of the rows, so a high F1 rests on few positive rows; the
  registry stores no count and no confidence interval, and the data file is not shipped here, so this was not re-counted.
- The entry still carries the waiver `legacy-0-physics-until-T26` (trained under physics `legacy-0`, parameters not recorded);
  no re-validation under the current physics is on file in the registry.
- No threshold-sensitivity, no false-alarm-per-day figure, no test on anomaly types the generator does not produce.

## Base rate
True anomalies are a very small share of rows in the synthetic dataset (not re-counted here: the data file is not shipped) —
precision is inherently capped low relative to a balanced-class problem; F1 is the more informative single number here, but check precision/recall separately for what an alert actually costs
in false positives.

## Known limitations
- Synthetic training data (see `docs/model_cards/LIMITATIONS.md`).
- Explainability: `src/anomaly_explain.py` reports per-feature reconstruction-error contribution for a given alert — which of
  the 5 features drove the score — but this is not SHAP; it's a cheaper, dependency-free proxy specific to autoencoders. See
  that module's docstring for the exact method and its limits.

## Evidence
- EVIDENCE f1 = 0.96 | models/registry.json | artifacts[model_id=anomaly_detector-20260927T143100Z].metrics.f1
- EVIDENCE precision = 0.9230769230769231 | models/registry.json | artifacts[model_id=anomaly_detector-20260927T143100Z].metrics.precision
- EVIDENCE recall = 1.0 | models/registry.json | artifacts[model_id=anomaly_detector-20260927T143100Z].metrics.recall
- EVIDENCE threshold_percentile = 99.5 | models/registry.json | artifacts[model_id=anomaly_detector-20260927T143100Z].params.threshold_percentile
- EVIDENCE threshold = 0.01222879160195589 | models/anomaly/config.json | threshold
- EVIDENCE split = chronological:train=rows[0:20736],heldout=rows[20736:25920] | models/registry.json | artifacts[model_id=anomaly_detector-20260927T143100Z].split_id
- EVIDENCE evaluation_ref = null | models/registry.json | artifacts[model_id=anomaly_detector-20260927T143100Z].evaluation_ref
- EVIDENCE waiver = legacy-0-physics-until-T26 | models/registry.json | artifacts[model_id=anomaly_detector-20260927T143100Z].compat_waiver.name
- EVIDENCE caps_status = PROPOSED_UNCONFIRMED | configs/anomaly/anomaly_v2.json | caps_status
- DERIVED heldout_rows = 5184 | 25920 - 20736, the two row bounds in the split above
