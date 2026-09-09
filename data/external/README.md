# data/external/ — Third-Party Data Provenance

This folder contains **provenance manifests only** — no bulk data files.

## Why this exists, and why it's not `data/raw/`

`data/raw/` already has an established meaning in this repository: it's
where `src/data_generator.py` writes its synthetic `sensor_data.csv`
output. Real-world, third-party downloads (weather, cluster traces,
chiller fault data, carbon intensity, etc.) live in `realData/` at the
repository root, and are **not duplicated here or into git** — some of
those sources are several hundred MB, and copying them would double disk
usage for no benefit.

Instead, `data/external/<source>/provenance.json` records, for each
top-level entry in `realData/`:
- what it is, where it came from, and its license/citation
- what it's used for in this project
- a full file listing with SHA-256 checksums (files under 50MB) or
  size+mtime (larger files)

This means git tracks *only* the small manifest files, while the actual
data stays local to each developer's machine (or is re-downloaded via the
download scripts already present under `realData/electricity_maps/` and
`realData/open_meteo/`).

## Regenerating manifests

```bash
python scripts/provenance.py
```

Re-run after adding, removing, or updating any source in `realData/`. If a
source isn't recognized (no entry in `scripts/provenance.py`'s
`KNOWN_SOURCES` table), the script will still scan it but flag it as
needing manual metadata — check the console output for a warning list.

## Pipeline stages (see also `data/cleaned/`, `data/features/`, `data/predictions/`)

```
realData/  (untouched third-party downloads, not in git)
    │
    ▼  scripts/provenance.py  (fingerprint + document)
data/external/*/provenance.json  (tracked in git)
    │
    ▼  Phase 4 calibration scripts (not yet implemented)
data/cleaned/  (validated, unit-normalized — not in git, regenerate via scripts)
    │
    ▼  Phase 4/6 feature engineering (not yet implemented)
data/features/  (model-ready, windowed/scaled — not in git)
    │
    ▼  Phase 5/6 trained models
data/predictions/  (model output logs, for drift monitoring — not in git)
```