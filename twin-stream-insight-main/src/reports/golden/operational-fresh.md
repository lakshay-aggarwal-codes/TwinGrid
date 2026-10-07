# Operational report

Generated (browser time): 2026-10-06T15:00:00.000Z

## Provenance

Where these values came from. Fields the backend did not provide are stated as such.

| Item | Value | Source |
| --- | --- | --- |
| Origin | Simulated | WS /ws/live → origin |
| Quality | not reported by backend | not provided by the backend |
| Source / context | Report | report endpoint class (frontend-known) |
| Last updated — server time | 2026-10-06 14:03:21 UTC | WS /ws/live → ts_ingest |
| Last updated — simulated clock | 2026-01-01 12:35:00 | WS /ws/live → sim_time (simulated clock, not event time) |
| Last received — browser receipt age | 0 s ago | browser receipt age (monotonic clock; not data time) |
| Freshness | Live | feed store state at generation |
| Scenario id | not available from backend | not provided by the backend |
| Run id | not available from backend | not provided by the backend |
| Physics version | not reported by backend | WS /ws/live → physics_version |
| Model version | v3 | WS /ws/live → anomaly_status.model_version |
| Detector | ae-1 | WS /ws/live → anomaly_status.detector_id |
| Trained on | synthetic | WS /ws/live → anomaly_status.trained_on |
| Dataset | not reported by backend | not provided by the backend |
| Weather / plant | weather/plant source not reported by backend | not provided by the backend |
| Evaluation status | not reported by backend | not provided by the backend |
| Calibration | not reported by backend | not provided by the backend |
| Fallback inputs | carbon | carbon_data_is_real from the data shown |
| Scope | Simulator-only — values come from the physics simulator, not measured telemetry. | origin (as reported) |
| Generated (browser time) | 2026-10-06T15:00:00.000Z | browser clock at generation; not data time |

## Facility state (latest live reading)

Reading timestamp (simulated clock, not event time): 2026-01-01T12:35:00

| Item | Value | Source |
| --- | --- | --- |
| PUE | 1.23 | WS /ws/live → StateResponse.pue |
| WUE (L/kWh) | 0.456 | WS /ws/live → StateResponse.wue |
| Cooling mode | hybrid | WS /ws/live → StateResponse.cooling_mode |
| Server utilisation | 0.5 | WS /ws/live → StateResponse.server_utilisation |
| IT power (kW) | 300 | WS /ws/live → StateResponse.it_power_kw |
| Cooling power (kW) | 60 | WS /ws/live → StateResponse.cooling_power_kw |
| Total power (kW) | 360 | WS /ws/live → StateResponse.total_power_kw |
| Server inlet temp (°C) | 20.0 | WS /ws/live → StateResponse.server_inlet_temp_C |
| Server outlet temp (°C) | 30.0 | WS /ws/live → StateResponse.server_outlet_temp_C |
| Outside temp (°C) | 22.0 | WS /ws/live → StateResponse.outside_temp_C |
| Humidity (%) | 50.0 | WS /ws/live → StateResponse.humidity_pct |
| Water flow (L/min) | 10.0 | WS /ws/live → StateResponse.water_flow_lpm |
| Water pressure (bar) | 3.00 | WS /ws/live → StateResponse.water_pressure_bar |
| Water consumed (L) | 5 | WS /ws/live → StateResponse.water_consumed_L |

## Anomaly detector (server-side)

Reported by the backend's anomaly pipeline; the browser does not score anything.

| Item | Value | Source |
| --- | --- | --- |
| Pipeline status | ok | WS /ws/live → anomaly_status.status |
| Score | 0.0123 | WS /ws/live → anomaly_status.score |
| Detector threshold | 0.0500 | WS /ws/live → anomaly_status.threshold |
| Type | none | WS /ws/live → anomaly_status.type |
| Window filled | 30 of 30 | WS /ws/live → anomaly_status.window_filled / window_size |
| Most recent anomaly episode this session | None received | WS /ws/live → anomaly_status (type, message; first frame of each episode) |

## Caveats

- All values are facility-wide. The backend has no per-rack or per-zone measurements, so nothing in this report is specific to an individual rack.
- Carbon figures use a flat 475 gCO₂/kWh fallback, not real grid-intensity data (no carbon-intensity dataset is loaded on the backend).
