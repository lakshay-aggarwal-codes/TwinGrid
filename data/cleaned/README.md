# data/cleaned/

Validated, unit-normalized data — the output of cleaning scripts that read
from `realData/` (via the manifests in `data/external/`) and from
`data/raw/sensor_data.csv`.

**Not yet populated.** This folder is created in Phase 1 as a placeholder;
it will be populated by the calibration/ingestion scripts introduced in
Phase 4 (Digital Twin core extension) and Phase 6 (forecasting).

Contract for anything written here:
- Timestamps normalized to UTC ISO-8601.
- Units standardized (°C not °F, litres not gallons, kW not W).
- No raw source file is ever modified in place — this folder holds
  *derived* copies only.
- Not committed to git (see repository `.gitignore`) — regenerate by
  re-running the relevant script.