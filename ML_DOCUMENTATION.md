# ML Documentation

## Thermal forecaster (LSTM)

- **Problem:** predict server outlet temp 30 min ahead
- **Input:** 12 timesteps × 10 features
- **Baseline:** not established in this codebase — a documented follow-up (persistence forecast)
- **Trained on:** `data/raw/sensor_data.csv` (see `DATA_DICTIONARY.md`'s known gap re: carbon/drought fields not present)

## Anomaly detector (LSTM autoencoder)

- **Problem:** detect water leaks / thermal spikes, trained on normal data only
- **Public-data check (not a validation of this model):** `src/anomaly_detector_nab_validation.py` trains a **separate**, matching-architecture, 1-feature model on public NAB data and scores it against the NAB labels. It checks the *method* only; it says nothing about the shipped 5-feature model, since NAB's feature space doesn't match. See that file's module docstring for the full reasoning.
- **Threshold:** the registered model's threshold is the 99.5th percentile of held-out reconstruction errors, chosen by an F1 search on those same rows (see `docs/model_cards/anomaly_detector.md`); the code default is the 95th percentile of training errors. Exposed via `AnomalyDetector.threshold` so the frontend gauge normalizes against a model-derived value rather than an arbitrary scale.

## PPO optimizer (`src/optimizer.py`)

- **Status:** research module. Scored once under the physics-1 protocol: outcome C, claim allowed: none (a fixed setting scored higher than every PPO seed). See `docs/model_cards/ppo_optimizer.md`. The one legacy policy is quarantined; no policy is promoted.
- **Scope:** simulator only, on an uncalibrated lumped model with assumed carbon.
- **Objective:** `J = α·WUE + β·(PUE-1) + γ·Carbon`
- **Carbon term:** the flat 475 gCO2/kWh fallback, because `data/cleaned/carbon_intensity.csv` does not exist in this repository (`src/carbon_provider.py`, `is_fallback`). The term is present; the signal is an assumption, not Electricity Maps data. It previously used raw cooling power as an undocumented proxy; that was replaced.
- **Water-stress handling:** `water_stress` is in the observation space (9 dims, was 8) and the environment enforces an automatic drought-mode override above `DROUGHT_THRESHOLD = 0.7`, matching `DigitalTwin.select_cooling_mode`'s identical rule. Previously a dead parameter — fixed in Phase 8.
- **Retraining requirement:** any change to reward composition or observation shape requires retraining `models/optimizer/ppo_model.zip` — a stale checkpoint will either error (shape mismatch) or silently optimize against an outdated objective.

## Predictive maintenance / RUL (`src/predictive_maintenance/`)

- **Dataset:** NASA C-MAPSS FD001 — **a run-to-failure degradation PROXY dataset (aircraft turbofan engines), used because no public data-centre-hardware failure dataset exists.** Never described as, or treated as, real data-centre equipment data anywhere in this codebase.
- **Baseline:** naive median-RUL prediction, always computed and reported alongside the LSTM's metrics (`src/predictive_maintenance/train.py`) — if the LSTM doesn't beat it, the script prints a warning rather than hiding the result.
- **RUL cap:** 125 cycles (standard piecewise-linear convention in the C-MAPSS literature)
- **Feature selection:** data-driven (training-set standard deviation threshold), not a hardcoded sensor-index list from a paper that couldn't be verified against this exact file.
- **API exposure:** `/api/equipment/health` returns the model's own methodology metrics (baseline vs. LSTM MAE/RMSE/R², improvement %, `dataset_caveat` field) — not live per-rack predictions, since there's no valid way to feed live twin telemetry into a model trained on aircraft-engine sensor features.
