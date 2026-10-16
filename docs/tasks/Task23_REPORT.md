# Task 23 — Realtime resilience

**Claim:** reconnect jitter, gap backfill from the history API, hidden-tab render pause, backfill status line, and a serialise-once fan-out. Simulated data stays labelled simulated; nothing here is "production-ready".

## What changed
- **Already present, reused (not rewritten):** the connection state machine (`telemetry/freshness.ts`: connecting, live, stale, reconnecting, disconnected/unavailable = offline), stale detection, exponential backoff, the status chip with last-update age (Task 20 `StatusBar`), drop-oldest slow-client queues, 1013/1011 eviction, per-user/global caps, the Task 6 ticket flow. Untouched.
- Backend `api/services/live_broadcast_service.py`: `broadcast` encodes the payload to JSON **once** (`_Frame`, a `dict` subclass carrying `.text`) and every client writer sends that text; sockets without `send_text`, or a payload that cannot be encoded (NaN), fall back to `send_json`. Both broadcast modes use it. Queued payloads are still plain dicts, so existing tests are unaffected.
- `api/wsTransport.ts`: `jitteredDelay` (+-25% of the backoff base) via optional `{ random }`; default is exact (no jitter), so existing timing tests are unchanged. `telemetry/feedStore.ts` passes `Math.random` (override via `random`).
- `features/realtime-resilience/`: `backfill.ts` (gap from server `seq` + `ts_ingest`, capped at 1 h, five requests per gap, one at a time, newer gap supersedes), `BackfillHost` (settings slot), `backfillState.ts`, `backfillText.ts`. `StatusBar.tsx` shows one extra line only after a gap ("Backfilled 2 of 3 missed updates (the rest were not stored)", "stored history unavailable").
- `three/TwinScene.tsx` + `three/frameloop.ts`: `frameloop="never"` while the tab is hidden, one invalidate on return.
- `features/registry.test.ts`: list gained `realtime-resilience`.

## Assumptions
- Backfill reads the five default measurand sensors (`fac<id>.<measurand>`) like the history screen; a custom `TELEMETRY_FEATURE_SENSORS` mapping would show "stored history unavailable", not wrong data.
- No restart (seq backwards) or missing `seq`/`ts_ingest` backfill: the window is unknown. Backfilled samples are held in the backfiller state for consumers; no chart consumes them yet.
- No new env vars (`docs/env/Task23.md` lists the existing fan-out ones).

## Test results
- Run for real (Node 22, real source sliced out): gap window, caps, restart/missing cases, status text, jitter bounds: `passed 13, failed 0`. Syntax parse of every changed `.ts` and `.py` file: 0 errors (one TS test uses a parameter property, which strip-only mode rejects and `tsc` accepts, as in the existing transport test).
- Written, NOT executed: `tests/test_task23_fanout.py`, `wsTransport.jitter.test.ts`, `backfill.test.ts`, `BackfillHost.test.tsx`, `frameloop.test.ts`; `pytest`, `ruff`, `npm ci`, `typecheck`, `lint:ci`, `vitest`, `build`.

## Not verified
- Sandbox has no network, FastAPI, pytest, ruff or `node_modules`, so no suite or build was run.
- Real browser tab-hide behaviour of the canvas; real WebSocket byte-identity of `send_text` vs `send_json` (both use compact JSON with `ensure_ascii=False`).
