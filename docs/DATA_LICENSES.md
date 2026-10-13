# External data: sources, licences and claim boundaries

The authoritative record is `data/external/REGISTER.json` (schema in roadmap 14.1), checked by `python scripts/check_register.py` in CI. This page summarises it for readers and states what may and may not be claimed.

## Licence policy

- Every entry is `license_status: unverified` and `redistribution: not_permitted` until a person records `terms_url`, `terms_retrieved_at` and `terms_sha256` (roadmap A-4). No tool or script sets `verified`.
- Unknown redistribution is treated as `not_permitted`.
- No entry has any licence evidence recorded yet, so **this repository makes no licence, reuse or redistribution statement about any dataset below.** Licence wordings in earlier manifests (for example "CC BY 4.0", "open data", AGPL-3.0, "free for research/education use") are unverified claims and are not repeated here.
- `retrieved_at` in the register is the earliest file modification time in the manifest scan, not a recorded download time.
- Frontier / HPC data has no entry by design; `check_register.py` fails if code references it.

## Datasets used by code

| Register id | Used for | Boundary |
|---|---|---|
| `open-meteo-hourly-2025` | Hourly 2025 weather, normalised to `data/cleaned/weather_open_meteo.csv`; outside temperature and humidity for generated data | Not weather for other places or years; not measured facility weather |
| `wri-aqueduct-4-0-water-risk-data` | Static min-max-normalised country baseline (`bws_score`) under generated data, with a synthetic seasonal and drought overlay | Not a driver of cooling-mode arbitration; not facility or basin level; not monthly or future tables |
| `nasa-cmapss` | Proxy run-to-failure trajectories for the RUL model | A structural analogue only; not data-centre failure rates or RUL; keep the proxy caveat wherever it is mentioned |
| `numenta-nab` | Offline sanity check of a univariate autoencoder (`src/anomaly_detector_nab_validation.py`) | Not training data; no performance statement for the production detector |
| `electricity-maps-coverage-2026-09-06` | Zone and signal catalogue read into `data/cleaned/carbon_electricity_maps.csv` | Has no intensity column; not the source of the carbon term |
| `nrel-nsrdb-psm3` | Optional on-demand API fetch to `data/cleaned/solar_nsrdb.csv` (dormant code) | Nothing downstream reads it; no raw copy exists; no solar feature or figure |

## Datasets held for reference only

No code reads these. They must not be cited as calibration or validation.

| Register id | Notes |
|---|---|
| `ashrae-rp-1043` | Source unidentified ("public research-data mirror"). Not calibration of per-mode cooling COP; no validation of anomaly fault signatures; a person must identify the source before any use. |
| `ashrae-tc-9-9-power-white-paper-2016` | Reading material. |
| `ashrae-gepiii-kaggle` | Kaggle competition rules apply and are unverified. |
| `specpower-ssj2008-results-20260906` | Not calibration of the IT-power curve; not measured at this facility. |
| `alibaba-clusterdata` | Not a real `server_utilisation` driver; utilisation is a synthetic sinusoid. |
| `cluster-trace-docs-source-unconfirmed` | Not attributable to Alibaba; source unconfirmed. |
| `electricity-maps-download-scripts` | Records that local scripts exist; they are not run by this repository. |
| `wri-aqueduct-4-0-country-rankings`, `wri-aqueduct-water-stress-country-rankings-xlsx` | Country ranking workbooks. |

## What is real, fallback or synthetic

See `docs/model_cards/DATA_TRUTH.md`. In short: carbon intensity is a flat assumed 475 gCO2/kWh (no carbon-intensity file exists), `server_utilisation` is synthetic, and the Electricity Maps entry is a catalogue with no intensity column.

## Claims

Allowed: "Every external dataset has a recorded source, version, permitted-use status and claim boundary."
Not allowed: any licence statement not backed by recorded evidence; RP-1043 as calibration; any Frontier statement.

## Closing a licence gap

For one dataset: open the dataset's terms page, then record `terms_url`, `terms_retrieved_at` and the SHA-256 of the saved terms text in its register entry. Set `license_status` to `verified` only if the terms support the permitted use, and set `redistribution` from the terms. Then run `python scripts/check_register.py`.
