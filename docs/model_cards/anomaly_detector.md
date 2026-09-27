# Model Card: Anomaly Detector (Autoencoder)

## Intended use
Flags anomalous sequences of 5 sensor features (`water_flow_lpm`,
`water_pressure_bar`, `server_outlet_temp_C`, `it_power_kw`,
`humidity_pct`) via reconstruction error. Backs `/api/anomaly_score` and
the live dashboard's alert stream.

## Training data
`data/raw/sensor_data.csv` (see forecaster card) — trained on the
**normal-only** rows (`anomaly == 0`) of the chronological first 80%.

## Evaluation methodology
**As of this fix (Phase 2), evaluated on a held-out chronological 20% the
model never saw during training** — `notebooks/train_all.py` splits
`df_anomaly` before calling `detector.train()`, then calibrates the
alert threshold (best of an 80th–99.99th percentile search) and reports
F1/precision/recall on the test split only.

Before this fix, both training and the reported F1/precision/recall used
the *same* full dataset — the previously-reported F1=0.9256 reflected
memorization of the training set, not generalization to unseen data. If
you have an older `models/registry.json` entry or a number from before
this change, it is **not comparable** to the current one.

## Base rate
True anomalies are ~0.2% of rows in the synthetic dataset — precision is
inherently capped low relative to a balanced-class problem; F1 is the
more informative single number here, but check precision/recall
separately for what an alert actually costs in false positives.

## Known limitations
- Synthetic training data (see `docs/model_cards/LIMITATIONS.md`).
- Explainability: `src/anomaly_explain.py` (added in this pass) reports
  per-feature reconstruction-error contribution for a given alert — which
  of the 5 features drove the score — but this is not SHAP; it's a
  cheaper, dependency-free proxy specific to autoencoders. See that
  module's docstring for the exact method and its limits.
