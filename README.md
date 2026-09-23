# Data Centre Digital Twin

A physics-informed digital twin for data-centre energy and water optimization, combining a coupled thermo-hydraulic simulation with a multi-objective reinforcement-learning agent, real-world calibration data, and a predictive-maintenance module.

## Problem statement

Data centres worldwide consume significant water and electricity, and most systems optimize energy and water as separate problems — a decision that helps one commonly hurts the other. This project implements a joint objective `J = α·WUE + β·PUE + γ·Carbon`, optimized by a single PPO reinforcement-learning agent, with weights adjustable in real time.

## What's real, and what's honestly labeled

Every claim in this repo is either (a) real and verified, or (b) explicitly labeled as a proxy/simplification. In particular:
- The predictive-maintenance model is trained on **NASA C-MAPSS**, a proxy dataset (aircraft engines) — never presented as real data-centre hardware data. See `ML_DOCUMENTATION.md`.
- The anomaly detector's real-world validation uses **NAB**, on a separate matching-architecture model — not the production model itself, since NAB's feature space doesn't match. See `ML_DOCUMENTATION.md`.
- Carbon intensity is a real Electricity-Maps-derived **diurnal average**, not a live real-time feed. See `src/carbon_provider.py`.

## Architecture

See `ARCHITECTURE.md` for the full diagram and layer-by-layer breakdown.


## Technology stack

- **Backend:** FastAPI, SQLAlchemy (async), Postgres, Alembic
- **ML:** TensorFlow/Keras (LSTMs), Stable-Baselines3 (PPO), scikit-learn
- **Frontend:** React, Vite, TypeScript, shadcn/ui
- **Real-world data:** Open-Meteo, Electricity Maps, WRI Aqueduct, SPECpower, ASHRAE RP-1043, NASA C-MAPSS, NAB — see `DATA_DICTIONARY.md`
- **Infra:** Railway (Nixpacks, production), Docker/docker-compose (local dev, CI), GitHub Actions, Prometheus metrics

## Data sources

See `data/external/*/provenance.json` for a fingerprinted manifest of every real-world dataset used, including source, license, and checksum. See `DATA_DICTIONARY.md` for the full column reference.

## ML models

See `ML_DOCUMENTATION.md` for problem/input/output/baseline/evaluation for every model.

## Local setup

```bash
git clone <repo>
cd DigitalTwin-main
cp .env.example .env   # fill in JWT_SECRET_KEY at minimum
pip install -r requirements.txt
python -m src.data_generator --days 90
python notebooks/train_all.py
uvicorn api.main:app --reload
```

## Docker setup

```bash
docker compose up --build
```
Note: this is for local development. Production (Railway) builds via Nixpacks, not this Dockerfile — see `DEPLOYMENT.md`.

## Deployment

See `DEPLOYMENT.md`.

## Testing

```bash
pip install -r tests/test_requirements.txt
pytest tests/ -v
```

## CI/CD

GitHub Actions runs lint (ruff), the full test suite, and a Docker build-verification step on every push. See `.github/workflows/ci.yml`.

## Future improvements

- Real-time (not diurnal-average) carbon intensity feed
- Real cluster-trace-driven server utilisation (Alibaba/Google trace ingestion not yet built)
- Backfill carbon/water-stress columns into the training dataset (see `DATA_DICTIONARY.md`'s "Known Gap")
- External monitoring actually scraping `/metrics` (currently exposed but unscraped — see `DEPLOYMENT.md`)