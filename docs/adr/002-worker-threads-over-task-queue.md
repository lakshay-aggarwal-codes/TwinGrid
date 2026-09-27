# ADR 002: worker threads over a task queue (initially)

## Status
Accepted, with an explicit expiry condition (see Consequences).

## Context
`/api/optimize`'s fallback PPO training and PDF simulation/report
generation are CPU-bound and would block FastAPI's async event loop if
run inline. The original bug this fixed: `/api/simulate/{hours}` and
`/api/optimize` blocking `/healthz` during a request.

## Decision
Use `run_in_threadpool`/`asyncio.to_thread` to move CPU-bound work off
the event loop, within the same process. Verified live: `/healthz`
responded in 17ms *during* an `/api/optimize` call (event loop not
blocked).

A real task queue (Celery/RQ/Arq) was considered and deliberately
deferred — see Phase 4 of the roadmap.

## Consequences
- Simple: no new infrastructure (broker, worker processes) to run,
  deploy, or monitor.
- **Does not survive a process restart** mid-training, and **does not
  scale across multiple API instances** — the shared live twin singleton
  (`get_twin()`) and the training lock (`_train_lock` in
  `optimization_service.py`) both assume a single process. Running more
  than one API instance today would silently break this (see
  `docs/architecture/deployment.md`).
- **Expiry condition**: this decision should be revisited the moment
  either (a) a real multi-instance deploy is needed, or (b) training
  needs to survive a restart / be retried / be observable as a queued
  job. At that point, move to a real task queue (Phase 4) rather than
  extending the worker-thread pattern further.
