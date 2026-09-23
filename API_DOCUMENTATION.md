# API Documentation

Base URL: `https://function-bun-production-6ce5.up.railway.app` (production)

All `/api/*` endpoints and `/ws/live` require a JWT bearer token (`Authorization: Bearer <token>`), obtained via `/auth/login`. See `SECURITY.md` for token lifecycle.

## Auth

| Endpoint | Method | Auth | Rate limit | Notes |
|---|---|---|---|---|
| `/auth/register` | POST | none | 5/hour/IP | role: `viewer` (default) or `operator` |
| `/auth/login` | POST | none | 10/minute/IP | returns `{access_token, role}` |

## Digital Twin

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/state` | GET | any valid user | Query: `utilisation`, `outside_temp`, `water_stress`, `mode` (`auto` or explicit) |
| `/api/simulate/{hours}` | GET | any valid user | 1–168 hours, hourly snapshots |
| `/ws/live` | WebSocket | `?token=` query param | Broadcasts every 3s from one shared loop (Phase 11) |

## Optimization

| Endpoint | Method | Auth | Rate limit |
|---|---|---|---|
| `/api/optimize` | POST | `operator` role only | 10/minute/IP |

Body: `{alpha, beta, gamma, water_stress, hours}` — minimizes `J = alpha*WUE + beta*(PUE-1) + gamma*Carbon`.

## Anomaly / Alerts

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/anomaly_score` | GET | any valid user | Query: `recent_data` (JSON array, shape 12×5) |
| `/api/alerts` | GET | any valid user | Query: `limit` (default 50) |

## Equipment Health

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/equipment/health` | GET | any valid user | Returns predictive-maintenance model's validated methodology metrics — **not live per-rack RUL**, see `ML_DOCUMENTATION.md` |

## Health / Observability

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/healthz` | GET | none | Infrastructure liveness check, 503 if DB unreachable |
| `/api/health` | GET | any valid user | Authenticated reachability check |
| `/metrics` | GET | none | Prometheus format; not currently scraped by anything (see `DEPLOYMENT.md`) |