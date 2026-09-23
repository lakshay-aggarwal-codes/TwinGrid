# Data Dictionary

## `data/raw/sensor_data.csv` (synthetic, via `src/data_generator.py`)

| Column | Type | Source | Notes |
|---|---|---|---|
| `timestamp` | datetime | generated | 5-min intervals |
| `server_utilisation` | float [0,1] | synthetic diurnal curve | **Not yet real-cluster-trace-driven** — flagged follow-up |
| `outside_temp_C` | float | real (Open-Meteo) if `data/cleaned/weather_open_meteo.csv` present, else synthetic | see `_load_real_weather` |
| `humidity_pct` | float | same as above | |
| `server_inlet_temp_C` | float | derived | |
| `server_outlet_temp_C` | float | `DigitalTwin.compute_outlet_temp` | single source of truth (Phase 4) |
| `it_power_kw` | float | `DigitalTwin.compute_it_power` | idle-power-floor included |
| `cooling_power_kw` | float | `DigitalTwin.compute_cooling_power` | mode-dependent COP |
| `cooling_mode` | categorical | `DigitalTwin.select_cooling_mode` | added Phase 4 — was previously absent entirely |
| `water_stress` | float [0,1] | real Aqueduct baseline + synthetic seasonal/drought overlay | see `_compute_water_stress` |
| `total_power_kw`, `pue` | float | derived | |
| `water_flow_lpm`, `water_consumed_L`, `wue` | float | `DigitalTwin.compute_water_consumption` | |
| `water_pressure_bar` | float | synthetic, ±0.1 bar noise | |
| `anomaly` | int {0,1} | synthetic injected events (5 total) | thin — see `ML_DOCUMENTATION.md`'s NAB validation section |

**Known gap:** `carbon_intensity_gco2_per_kwh`, `carbon_gco2`, `drought_override_active` are **not present** in this file — see `ARCHITECTURE.md`'s "Known architectural gap."

## `data/cleaned/*.csv` (real-world, via `src/ingestion/*.py`)

| File | Columns | Source |
|---|---|---|
| `weather_open_meteo.csv` | `city`, `timestamp_utc`, `outside_temp_C`, `humidity_pct` | Open-Meteo, 24 Indian cities |
| `carbon_intensity.csv` | `timestamp_utc`, `zone`, `carbon_intensity_gco2_per_kwh`, `source_file` | Electricity Maps |
| `water_stress_aqueduct.csv` | `country`, `region`, `water_stress_score`, `water_stress_category` | WRI Aqueduct 4.0 baseline annual |
| `solar_nsrdb.csv` | `timestamp_utc`, `ghi_w_m2`, `dni_w_m2`, `dhi_w_m2`, `air_temperature_c`, `relative_humidity_pct`, `wind_speed_m_s` | NREL NSRDB (fetched, not pre-downloaded) |

## `realData/` external sources — full provenance

See `data/external/<source>/provenance.json` for every source's license, citation, checksum, and `used_for` field. Full source list: Electricity Maps, WRI Aqueduct 4.0, ASHRAE TC 9.9, SPECpower_ssj2008, ASHRAE RP-1043, ASHRAE GEPIII (Kaggle), Alibaba Cluster Trace, NASA C-MAPSS, NAB, Open-Meteo.