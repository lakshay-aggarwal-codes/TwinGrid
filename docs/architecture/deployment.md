# Deployment Topology

## Current state (as of this doc): local Docker Compose only

```mermaid
graph TB
    subgraph "Windows dev machine (docker compose)"
        API[api container<br/>python:3.12-slim, uvicorn]
        DB[(postgres:15-alpine<br/>port 5432)]
        API <-->|asyncpg| DB
    end

    Dev[Browser<br/>localhost] --> API
```

**Never deployed to an actual platform yet** (Railway/Render were the
original targets) — this is an open item carried since the original
handoff, not resolved by any phase so far. Everything in this repo has
only been verified via `docker compose up` locally.

## What a real deploy would add (not yet built)

```mermaid
graph TB
    subgraph "Hypothetical: Railway/Render or similar"
        LB[Load balancer / TLS termination]
        API1[api instance 1]
        API2[api instance 2 -- N/A until<br/>Phase 4 task queue exists,<br/>see below]
        DB[(Managed Postgres)]
        Secrets[Secrets manager<br/>JWT_SECRET_KEY,<br/>OPERATOR_REGISTRATION_KEY<br/>-- currently ad hoc<br/>PowerShell env vars]
    end
    LB --> API1
    LB -.->|not yet meaningful:<br/>in-process worker threads<br/>don't share state across<br/>instances| API2
    API1 --> DB
    API1 --> Secrets
```

Running more than one API instance today would break the in-process
worker-thread pattern used for `/api/optimize`'s fallback training and
the shared live-broadcast twin singleton (`get_twin()`), both of which
assume a single process. A real multi-instance deploy needs Phase 4's
task queue + a way to share the live twin's state (or accept that only
one instance runs the broadcast loop) before this diagram's `API2` box
means anything.
