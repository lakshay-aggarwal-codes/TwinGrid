# Claims ledger

| ID | Claim | Status | Evidence | Boundary |
|---|---|---|---|---|
| C-07 | The anomaly detector scored F1 0.96 on held-out simulator rows. | result | `docs/model_cards/anomaly_detector.md` | The threshold was tuned on the same rows. |
| C-08 | The PPO optimizer is quarantined. | result | `models/registry.json` | Simulator only. |
