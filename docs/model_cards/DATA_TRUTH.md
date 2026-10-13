# Data truth: what is real, what is a fallback, what is synthetic

TwinGrid is a **simulation-based** digital-twin platform. Every number it serves comes from its own simulator
(`src/digital_twin.py`). This page says, input by input, where the simulator's inputs come from. Sources:
`data/external/REGISTER.json` (checked in CI by `scripts/check_register.py`), `src/carbon_provider.py`,
`src/data_generator.py`, `docs/DATA_LICENSES.md`.

## Carbon intensity: a flat assumption

- The carbon term uses a **flat 475 gCO2/kWh**, the same at every hour and for every place
  (`FALLBACK_FLAT_INTENSITY_GCO2_PER_KWH` in `src/carbon_provider.py`; a commonly cited world average, IEA/Ember).
  It is an assumption, not measured or site-specific grid data.
- It is used because `data/cleaned/carbon_intensity.csv` does not exist (`data/cleaned/` holds only a README in this
  repository) and **no code in this repository produces that file**. The Electricity Maps ingestion
  (`src/ingestion/carbon_electricity_maps.py`) reads a zone and signal *catalogue* with no intensity column
  (register entry `electricity-maps-coverage-2026-09-06`); it is not the source of the carbon term.
- Consequence: `carbon_data_is_real` is `false` in `/api/state`, `/api/whatif`, simulation and run results and on the
  live feed (`carbon_is_fallback: true` with a `carbon_signal` label). Absolute CO2 totals and any change in them
  are illustrative; **no carbon-reduction claim is supported** (`format_carbon_reduction` refuses to print one).
- If a carbon CSV is ever supplied, its `average` or `marginal` meaning comes only from the sidecar
  `carbon_intensity.meta.json`; without it the semantic is `unknown`. A real series is still an hour-of-day mean, not
  a live grid feed.
- Where it is labelled (all say "assumption", "fallback" or "flat constant"): ESG report PDF (table row `ASSUMPTION`
  and a bold paragraph, plus a "SIMULATED DATA" line on every report), Sustainability tab, 3D legend, scenario library
  and preview, what-if, exported reports, evaluation tables, provenance chips.

## Inputs, one by one

| Input | Status | Evidence |
|---|---|---|
| Carbon intensity | **Fallback constant** (above) | `src/carbon_provider.py` |
| `server_utilisation` | **Synthetic** (regimes `low`, `diurnal`, `high`, `burst`); not a real workload trace | `src/data_generator.py` header; register entry `alibaba-clusterdata` is reference-only |
| Outside temperature, humidity | Open-Meteo 2025 hourly files for the cities in the register, normalised into `data/cleaned/weather_open_meteo.csv`. Synthetic curves only with `--allow-synthetic-weather`, recorded as `synthetic_inputs`. No cleaned weather CSV is committed here. | `open-meteo-hourly-2025` |
| Water stress | One static min-max-normalised Aqueduct 4.0 country score as baseline, plus a **synthetic** seasonal and drought overlay. Synthetic default 0.35 only with `--allow-synthetic-water-stress`. | `wri-aqueduct-4-0-water-risk-data` |
| Equipment health (RUL) | Trained on NASA C-MAPSS turbofan data as a **proxy**; not data-centre failure data | `nasa-cmapss` |
| Anomaly detector | Trained on simulator data; NAB used only for an offline sanity check of a univariate autoencoder | `numenta-nab`, `docs/model_cards/` |
| Cooling physics, IT power curve, PUE, WUE | Simulator equations; not calibrated against a real facility | `docs/PHYSICS_V2.md`, `docs/model_cards/LIMITATIONS.md` |
| Anomaly events | Synthetic, injected by the generator | `DATA_DICTIONARY.md` |
| Solar irradiance (NREL NSRDB) | **Not used.** Dormant fetch code only (below). | `nrel-nsrdb-psm3` |

Nothing in this table is a measurement from a real facility. Every stored row carries an `origin`, and the simulator
never writes `measured`.

## NSRDB solar code is dormant

`src/ingestion/solar_nsrdb.py` can fetch NREL NSRDB data on demand into `data/cleaned/solar_nsrdb.csv`. Nothing reads
that file: no twin, reward, API, report or UI uses solar data (guarded by `tests/test_task11_data_truth.py`). It
stays only because it is still wired into `src/ingestion/run_ingestion.py`, `scripts/run_ingestion.py`, the data
register and their tests. Removing it is a separate, register-wide change. No solar or renewable-generation statement
is supported.

## What may be said

Allowed: "The twin is driven by simulated workload and, where available, historical weather; carbon uses a flat
assumed intensity." Not allowed: "real grid carbon", "measured emissions", "carbon-aware optimisation demonstrated",
"calibrated on a real facility".
