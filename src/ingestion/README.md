# Phase 2: Data Ingestion Layer

The Data Ingestion Layer normalizes heterogeneous source datasets into clean, validated, and consistently formatted CSV files under `data/cleaned/`.

These cleaned datasets power the Digital Twin thermal simulation, PPO joint optimization ($\alpha \cdot W + \beta \cdot E + \gamma \cdot C$), water stress cooling-mode arbitration (patent Claim 8), and forecasting.

---

## Ingestion Modules

| Module | Source | Input Location | Cleaned Output |
| :--- | :--- | :--- | :--- |
| `weather_open_meteo.py` | Open-Meteo Weather Archive | `realData/open_meteo/*_weather_2025_hourly.csv` (25 cities) | `data/cleaned/weather_open_meteo.csv` |
| `carbon_electricity_maps.py` | Electricity Maps Grid Coverage | `realData/2026-09-06-electricity-maps-coverage-data.csv` | `data/cleaned/carbon_electricity_maps.csv` |
| `water_stress_aqueduct.py` | WRI Aqueduct 4.0 Water Risk Atlas | `realData/aqueduct-4-0-water-risk-data/.../Aqueduct40_baseline_annual_y2023m07d05.csv` | `data/cleaned/water_stress_aqueduct.csv` |
| `solar_nsrdb.py` | NREL NSRDB PSM v3 Service | NREL Developer API (REST PSM3 download endpoint) | `data/cleaned/solar_nsrdb.csv` |

---

## Running the Ingestion Pipeline

### 1. Run All Ingestion Pipelines
```bash
python -m src.ingestion.run_ingestion --all
```

### 2. Run Individual Ingestion Sources
```bash
# Ingest 25 Indian city weather archives (219,000 rows)
python -m src.ingestion.run_ingestion --source weather

# Ingest Electricity Maps carbon and grid coverage dataset (2,520 rows)
python -m src.ingestion.run_ingestion --source carbon

# Ingest WRI Aqueduct 4.0 baseline water stress table (68,506 rows)
python -m src.ingestion.run_ingestion --source water

# Fetch and ingest NREL NSRDB solar irradiance data via API
python -m src.ingestion.run_ingestion --source solar
```

---

## NREL NSRDB Solar API Configuration

NSRDB data is **not stored locally as raw data**; it is fetched directly from the NREL API.

### Required Environment Variables
Set the following in your `.env` file:
```bash
NSRDB_API_KEY=your_nrel_nsrdb_api_key_here
NSRDB_EMAIL=your_registered_email@example.com
NSRDB_LATITUDE=28.6139
NSRDB_LONGITUDE=77.2090
NSRDB_YEAR=2020
```

> **API Key Registration**: You can get a free API key at [https://developer.nrel.gov/signup/](https://developer.nrel.gov/signup/).
> If the API key is not configured, the solar ingestion module will exit with a clear error without corrupting or modifying other datasets.

---

## Testing

Run unit and integration tests with mocked API endpoints:
```bash
python -m unittest tests/test_ingestion.py
```
