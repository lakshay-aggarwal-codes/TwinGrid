# Providing a real carbon-intensity series

TwinGrid ships **no** carbon data. Without `data/cleaned/carbon_intensity.csv` every carbon number is the flat
475 gCO2/kWh **assumption** (`is_fallback=True`, `carbon_data_is_real=false`). To use your own series:

1. Prepare a CSV: `timestamp_utc` (ISO-8601 with `Z` or an offset; strictly increasing per zone),
   `carbon_intensity_gco2_per_kwh` (0..2000), `zone` (every row).
2. Prepare `meta.json`: `semantic` (`average` | `marginal`), `unit` (`gCO2/kWh`), `source`, `license_ref`,
   `retrieved_at` (ISO-8601 with offset); optional `source_version`, `resolution_s`.
3. `python -m src.carbon_ingest validate --csv my.csv --meta meta.json` (writes nothing), then
   `python -m src.carbon_ingest install --csv my.csv --meta meta.json` (`--overwrite` to replace).

Refused: naive timestamps, duplicates/disorder, gaps > 3x the resolution, out-of-range or non-numeric values, a wrong
unit, missing provenance, and any of the 24 site-local hours without data (the loader would fill them with the flat
assumption and mark the whole signal a fallback; `--allow-partial-hours` installs it anyway, still flagged fallback).

The sidecar records what YOU declared plus the CSV's SHA-256. TwinGrid does not verify the numbers, the licence, or the
average-vs-marginal claim. Any consumer still uses an hour-of-day mean of the series, not a dated time series.
"Carbon-aware optimisation demonstrated" additionally needs the roadmap §13.6 ablation; this does not provide it.
