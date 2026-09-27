# TwinGrid

A data-centre digital twin: FastAPI backend simulating IT/cooling power,
water use, and carbon impact, with an LSTM thermal forecaster, an
autoencoder anomaly detector, and a PPO reinforcement-learning cooling
optimizer. Postgres via SQLAlchemy/Alembic. React+Vite+Three.js dashboard
(under active development — see that directory's own state, not covered by
this document).

> **This file replaces the previous `README.md`, `ARCHITECTURE.md`,
> `FINAL_REVIEW.md`, and `DOCUMENTATION_SUMMARY.md`.** Those described a
> different, more complete 20-phase build (real Electricity Maps carbon
> data, a `src/digital_twin_documented.py` module, etc.) that doesn't match
> what's actually in this repository — `data/cleaned/carbon_intensity.csv`
> doesn't exist, `digital_twin_documented.py` doesn't exist, and the code
> falls back to a flat 475 gCO2/kWh carbon figure at runtime. Whether that
> older doc set described a different branch, a planned-but-unbuilt state,
> or something else isn't known — what's below is grounded in the actual
> code, verified by reading it and running what could be run. If you find
> a specific claim below that's wrong, that's a bug in this document; open
> an issue against it the same as you would against code.

## What's actually true right now

**Physics** (`src/digital_twin.py`): chiller COP depends on the
chilled-water setpoint for `CLOSED_LOOP`/`HYBRID` modes; airflow scales
with IT load (`effective_air_flow_m3_s`). Both `DigitalTwin.step()` (live)
and `src/data_generator.py` (historical dataset) call the same physics
methods — keeping these in sync matters; see `docs/architecture/system.md`.

**ML models** (`models/`): forecaster (LSTM), anomaly detector
(autoencoder, evaluated on a held-out chronological split, not the
training set), PPO cooling optimizer (trained across 3 seeds, reports
mean ± 95% CI PUE improvement vs. the rule-based baseline). Retrain with
`python notebooks/train_all.py`; it should also write
`models/registry.json` with lineage/metrics for each run — if that file
is missing after a run, something didn't complete, check the console
output. See `docs/model_cards/` for intended use, training data, and
known limitations of each model — in particular, **all three are trained
on synthetic data from this repo's own simulator, not real facility
data**, so their metrics measure fit to the simulator, not real-world
generalization.

**Carbon intensity**: flat 475 gCO2/kWh fallback everywhere. Real
Electricity Maps ingestion exists as code (`src/ingestion/carbon_electricity_maps.py`,
`scripts/run_ingestion.py`) but hasn't been run to produce
`data/cleaned/carbon_intensity.csv` in this repo state — until it has,
treat carbon figures anywhere in the product (including the ESG report)
as illustrative.

**API** (`api/`): FastAPI, JWT auth with short-lived access tokens +
rotating refresh tokens (`api/auth.py`, `api/secrets.py` for
file-based-secret support), audit logging on sensitive actions
(`api/services/audit_service.py`), rate limiting, Prometheus `/metrics`.
Swagger UI at `/docs`, ReDoc at `/redoc`. Endpoints span live state,
simulation, optimization (sync + async via RQ/Redis), anomaly scoring +
webhooks, shadow-mode PPO-vs-baseline logging, an ESG PDF report, and
PUE industry benchmarking. See `docs/architecture/data_flow.md` for the
live-request sequence and `docs/adr/` for why some of these were built
the way they were.

**Deployment**: `docker compose up` locally only (`db`, `redis`, `worker`,
`backend` services). **Never deployed to an actual platform.** Migrations:
5 revisions, chain verified intact (`alembic/versions/`), never run
against a live/managed Postgres.

## Setup

See `CONTRIBUTING.md` for local setup, training the models, and
pre-PR checks.

## Status / what's unverified

This codebase has had a lot of code written and reviewed, but large parts
have not been run end-to-end by anyone yet:

- `pytest tests/ -q` (including `tests/test_security_hardening.py`) —
  needs to actually be run and confirmed green.
- `pip install reportlab` and `/api/esg_report` — untested render.
- `redis`+`rq` + `docker compose up` + confirming a
  `POST /api/optimize/train_async` job actually gets picked up by the
  `worker` service.
- `alembic upgrade head` against a real (not local docker) Postgres.
- Any real deploy.

Don't treat anything in this repo as "done" until one of the above has
actually confirmed it.

## Not built (scope, not bugs)

Real facility integration (BACnet/Modbus/SNMP), multi-tenancy/RBAC, fleet
management, SOC 2 posture, real 3D/CAD facility import, Kubernetes/Helm,
multi-region deployment, cost/FinOps monitoring. Each needs real
infrastructure, hardware, or a product decision this repo's history
didn't have — see the phase-4 handoff notes in `docs/` for reasoning.
