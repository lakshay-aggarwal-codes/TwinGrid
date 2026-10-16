# Task 31 report: ML honesty pass (no training, no registry edits)

## What changed
- Rewrote `docs/model_cards/forecaster.md`, `anomaly_detector.md`, `ppo_optimizer.md` and filled `LIMITATIONS.md`. Each card now opens with its registry status, then results, then a "Negative and unevaluated results" section. Every number is an `EVIDENCE` line naming the file and JSON path it came from.
- `tests/test_task31_model_cards.py` resolves each `EVIDENCE` line in the cited file and compares the value, and fails if the prose holds any decimal or 4+ digit number that is not a rounding of an evidence value (or a recomputed `DERIVED` value). Changing a card number or an evidence value makes it fail.
- The phrases the Model Passport quotes from the cards (`src/model_passport.py`, pinned by `tests/test_task18_explain_passport.py`) are kept verbatim; checked directly.

## What the cards now say plainly (all from existing files)
- **Forecaster:** RMSE 0.523 C / MAE 0.421 C, one run, no seed on file, **no persistence baseline** (`ML_DOCUMENTATION.md` lists it as a follow-up), no evaluation record, still under the `legacy-0` waiver.
- **Anomaly detector:** F1 0.96 / precision 0.923 / recall 1.0 used a threshold chosen by F1 search **on the same held-out rows it is scored on** (`notebooks/train_all.py`), so it is optimistic. The event-level evaluation (`src/anomaly_eval.py`, `configs/anomaly/anomaly_v2.json`, `caps_status` `PROPOSED_UNCONFIRMED`) has no result on file.
- **PPO:** legacy policy is quarantined and **worse than the rule baseline (-2.27%)**; its registry interval uses 1.96 on 3 seeds (t multiplier gives about 0.244, not 0.111). Five newer v2 candidates are trained but not evaluated. The only decision report is baselines-only `NOT_EVALUATED`, claim allowed: none. It also shows a fixed setting beating the rule baseline (reward -57.88 vs -151.28) and **every policy having the inlet below its minimum for all 288 steps**.

## UI / doc strings changed
- `api/schemas/optimization.py`: anomaly `threshold` field description said "95th percentile of training error"; the registered model uses the 99.5th percentile of held-out errors. Now: "reconstruction error at the configured percentile; see threshold_percentile in the Model Passport". (Shows in the OpenAPI docs only.)
- `ML_DOCUMENTATION.md`: the same threshold sentence corrected.
- No frontend string changed: the in-app copy I searched (passport, PPO panel, reports, equipment caveat) already matches the cards.

## Not verified
- `data/raw/sensor_data.csv` is not in the repo copy, so no model number was re-run or re-counted (for example the anomaly positive count). Numbers are what the registry and report files hold.
- `pytest` is not installed here: `tests/test_task31_model_cards.py` ran on a small stand-in runner (`passed 5, failed 0`; mutating a card or evidence value makes it fail). The existing passport tests could not be run in full here; their phrase-pinning check was reproduced directly with no failures.
- I did not edit `models/registry.json` or any model file, as required.
