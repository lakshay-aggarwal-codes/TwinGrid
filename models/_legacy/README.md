# models/_legacy

Pickle-based files (`*.joblib`, `*.pkl`) moved here by `scripts/convert_scalers.py` (T19).
Nothing in the project loads files from this directory and the API process cannot load them at
all (contract 10.2: formats are limited to json, npz and keras). They are kept only so the
conversion can be rolled back. Do not load them; delete them once the rollback window has passed.
