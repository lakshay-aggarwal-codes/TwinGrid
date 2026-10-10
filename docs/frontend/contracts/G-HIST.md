# G-HIST: Contract Confirmation Record (BC-12 telemetry read API)

**STATUS: CODE-READ AND CAPTURED IN A SANDBOX. NOT YET CAPTURED ON THE REAL STACK. FE-18 IS CONDITIONALLY UNBLOCKED (see "Gate decision").**
The route, the validation rules and the error shapes below were captured from the real `api.routes.telemetry_routes` router mounted in the real
`api.main` app (in-memory SQLite, the repo's own `tests/api` fixtures, `httpx.ASGITransport`). Not exercised: Postgres, docker, a running worker or
simulator, a real JWT login, rate limiting (disabled by the fixture). Repeat the runbook at the end on your stack before FE-18 merges.

## Gate decision (read this first)

| Question | Answer |
|---|---|
| Does a telemetry read API exist? | **Yes** (T17): two endpoints, tested (`tests/api/test_telemetry_routes.py`, 32 tests pass in the sandbox). |
| Is it the API the FE roadmap named for BC-12? | **No.** BC-12 / FE-18 assumed `/api/telemetry` and `/api/sensors/{id}/latest`. Neither exists. The real paths are below. FE-18 must use the real paths. |
| Is there anything to chart on the running stack? | **Not from the live simulator, in this snapshot.** `api/services/live_broadcast_service.py` writes only the legacy `sensor_readings` row each tick; no code path in `api/` calls `ingest_samples()`. Only the MQTT path (`src/sensor_ingestion.py`) writes `telemetry_sample`. With the simulator alone the endpoints return `items: []`. See "Producer gap" and backend prompt BE-G1. |
| Per-rack history? | **No.** No per-rack sensors exist (`scripts/seed_facility.py`: "per-rack telemetry does not exist"). Only five facility-level sensors, and only after `seed_facility.py --seed-sensors`. |

**FE-18 may start** when (a) the real-stack runbook below is clean and (b) either BE-G1 is merged or the owner accepts that FE-18 ships against an
MQTT-fed or seeded store and shows the empty state ("No stored telemetry for this window") on a simulator-only stack. FE-18 must never fill the gap
from the live WebSocket feed.

## Contract (backend)

Two endpoints, JWT, any role (viewer included), rate class `telemetry_read` = **60 requests/minute** (`RATE_LIMIT_TELEMETRY_READ`) plus the general limit.

### `GET /api/telemetry/sensors/{external_id}/samples`
| query | required | rule |
|---|---|---|
| `from` | yes | RFC 3339 **with offset** (`Z` or `+hh:mm`). Naive -> 422. Inclusive. |
| `to` | yes | same format. Exclusive (`from <= ts_event < to`). Must be after `from`. `to - from` <= `TELEMETRY_MAX_SPAN_H` (168 h) else 422. |
| `stream` | no, default `live` | exact match. `live` never returns replayed/imported data. Others look like `replay:<uuid>`. |
| `quality` | no, default `ok` | `ok` \| `invalid` \| `any`. |
| `limit` | no, default 1000 | 1..5000 (else 422). |
| `cursor` | no | opaque; use the previous `next_cursor`. Bad cursor -> 422. |

**Response** (`G-HIST.capture-samples-*.json`): `external_id, unit, sampling_interval_s, stream, quality, items[], next_cursor`.
Item keys, always all seven: `ts_event, ts_ingest, value, origin, stream_id, quality, invalid_reason`.

- Order is the server keyset `(ts_event, id)`, ascending. **FE must not re-sort.** Out-of-order *arrival* is already resolved by the server.
- Timestamps are UTC with a `Z` suffix. `ts_event` = event (data) time; `ts_ingest` = server ingest time. Neither is browser time.
- `value` is a number, **never null**. A missing point is an absence, not a null.
- `next_cursor` is `null` on the last page. Pages are stable under concurrent inserts.
- Empty window = HTTP 200 with `items: []` (`G-HIST.capture-samples-empty-window.json`), not 404.

### `GET /api/telemetry/sensors/{external_id}/gaps`
Query: `from`, `to` (same rules), `stream` (default `live`). Response (`G-HIST.capture-gaps.json`):
`external_id, stream, sampling_interval_s, threshold_s, gaps[{start,end,duration_s}], truncated`.
A gap is the difference between two **consecutive valid (`quality=ok`) samples** greater than `1.5 x sampling_interval_s`; `start` is the last valid
sample before it, `end` the first valid sample after it. Computed at read time, at most 1000 gaps (`truncated: true` beyond that).
There is no `stale` field anywhere in this API: "stale" and "gap" are never stored and "stale" is never returned.

## Vocabulary (backend-authoritative; unknown values stay unknown)
| field | values | source |
|---|---|---|
| `origin` | `simulated`, `measured`, `replay` | `src/telemetry/validation.py` `ORIGINS` |
| `quality` | `ok`, `invalid` | stored values; the `quality` *query* additionally accepts `any` |
| `invalid_reason` | `null` when ok; observed `range`; `future` exists in code (`INVALID_FUTURE`). Treat any other string as an unrecognised reason, show it verbatim | `validation.py` |
| `stream` / `stream_id` | `live`; `replay:<uuid>` and other `kind:<id>` strings (max 64 chars) | `validate_stream_id` |
| error body | RFC 7807 `application/problem+json`: `type` (`urn:twingrid:error:<code>`), `title`, `status`, `detail`, `instance`, `request_id`, optional `errors[]` | captures `err-*` |

Observed errors: 401 no token, 404 `Unknown sensor`, 422 naive `from`, 422 span > 168 h, 422 bad cursor, 422 `limit` > 5000. Rejected samples (unknown sensor, unit mismatch,
non-finite value, bad time) are never stored, so they can never appear here. Invalid samples (out of range, future) are stored and flagged.

## Differences from what the frontend roadmap assumed (FE-18 must follow this record, not the roadmap)
| # | Roadmap / FE-18 prompt said | Backend actually does | Consequence |
|---|---|---|---|
| 1 | `/api/telemetry`, `/api/sensors/{id}/latest` | `/api/telemetry/sensors/{external_id}/samples` and `/gaps`; **no `latest` endpoint** | No "latest value" call. The live card keeps using the WebSocket feed (FE-04); history never claims to be latest. |
| 2 | points carry backend `stale` | no `stale` field; gaps via `/gaps` | FE-18 draws no stale flag. Gaps come only from `/gaps`. |
| 3 | `Series.points[].v \| null` | `value` never null | `v: null` is produced by FE-18 **only** at the boundaries of a `/gaps` entry, to break the line. It is not a data value. |
| 4 | origin `measured\|simulated\|replayed` | `measured\|simulated\|replay` | `src/provenance` recognises `replayed`, so `replay` would fall to "Unverified source". FE-18 adds one explicit, tested alias `replay -> replayed` in `src/telemetry/history/origin.ts` only; it does not edit `src/provenance/**`. Any other string stays unknown. |
| 5 | per-sensor discovery implied | no list/discovery endpoint | Sensor ids are `fac<TELEMETRY_FACILITY_ID>.<measurand>` by default (e.g. `fac1.it_power_kw`) and can be overridden by `TELEMETRY_FEATURE_SENSORS`. FE-18 gets the facility id from `GET /api/facility` (`id`) and the measurand list from a constant; a 404 `Unknown sensor` renders as "Sensor not registered on this backend", never as an empty chart. Open decision 2 asks for a discovery endpoint. |
| 6 | "5,000-point history window" (FE-20 S4) | max 5000 per page, max 168 h; density depends on the producer (see below) | S4 measures a window that returns >= 5000 points on the real backend, or is reported NOT MEASURED. Paging is by `next_cursor`. |
| 7 | polling for history | 60 req/min cap | Fetch on window/sensor change and explicit refresh. No interval polling. |

The five measurands (units from the backend response, not from the FE table): `water_flow_lpm` (L/min), `water_pressure_bar` (bar), `server_outlet_temp_C` (degC),
`it_power_kw` (kW), `humidity_pct` (%). `sampling_interval_s` is per sensor and must be read from the response (300 s in the fixtures).

## Sample density depends on the producer (affects FE-18 windows and FE-20 S4)
`sampling_interval_s` is the sensor's **declared** interval (300 s in the fixtures). It does not guarantee spacing. The roadmap rule is that a simulated sample's `ts_event` is the wall-clock UTC of the tick (`be` pack, section 9.3 rule 6); the simulator ticks every `BROADCAST_INTERVAL_SECONDS = 3`, so a producer that writes every tick yields about 1200 points per hour per sensor, 28,800 per day, and one 5000-point page covers about 4.2 hours. A 168 h window can hold far more than one page. FE-18 therefore (a) never assumes 300 s spacing, (b) follows `next_cursor` up to a stated cap and says so when more data exists, and (c) never downsamples. Gap detection uses the declared interval (> 450 s), so a 3 s producer shows a gap only after an outage longer than 450 s. Owner decision D1 in BE-G1 (write every tick vs once per declared interval) decides which of the two densities FE-18 will see.

## Producer gap (blocks real data, not the contract)
- Simulator: `live_broadcast_service.py` lines ~313-320 persist `SensorReading` only. No `ingest_samples` call exists under `api/`. The module docstring of `src/sensor_ingestion.py` says the store is "the same path the live simulator uses"; the code does not do that.
- MQTT: `src/sensor_ingestion.py` writes the store through `ingest_samples()` when `TELEMETRY_STORE_ENABLED` is true (default).
- Also affects the anomaly window: with `TELEMETRY_WINDOW_SOURCE=store` (default) and no producer, the window can never become scorable. Verify on the real stack that anomaly status is not stuck in `warming_up`. This is a backend defect or an unfinished T17 half, not a frontend task.
- Remedy: backend prompt **BE-G1** (in `TwinGrid_Backend_Gate_Closing_Prompts_PostFE16.docx`).

## CAPTURE 1: backend content hash (sandbox copy of the supplied snapshot)
| file | sha256 |
|---|---|
| `api/routes/telemetry_routes.py` | `0d2a3393ca16e097f8528e3421a026a150916732507f2f8deec0fae1394fc343` |
| `api/services/telemetry_window.py` | `94a4c8f00351317e767d0f6a6af933e830011e718f5ba67a2205171fb989a039` |
| `src/telemetry/validation.py` | `f572e00edeacb76a2e77acd8fbcd8db21a540420c0b3c2cef6927c52f7947266` |
| `src/telemetry/ingest.py` | `8031fe8d63e9178b31ba305d21a5bffa2d2130313aa36ee783aaf1d65464c7e7` |
| `tests/api/test_telemetry_routes.py` | `ac5e2de5fe7dba10fe90cecff3bd0342be67c573c6f55234111f57b571094aad` |

On your checkout: `Get-FileHash api\routes\telemetry_routes.py, api\services\telemetry_window.py, src\telemetry\validation.py, src\telemetry\ingest.py -Algorithm SHA256`. A different hash means the contract may have moved: re-read the route docstring before trusting this record.

## CAPTURE 2: response bodies
Seeded with the repo's `tests/telemetry_support.py` helpers: sensor `fac1.it_power_kw`, 300 s interval, samples at 12:00-12:25, a 25-minute hole, 12:50-13:05, one out-of-range value (999999) at 13:10, plus one `replay`-origin sample on a replay stream. Values are synthetic test values (`300.0`), **not** simulator output; use these files for **shape and vocabulary only**.
| file | request | HTTP |
|---|---|---|
| `G-HIST.capture-samples-ok.json` | default quality | 200 |
| `G-HIST.capture-samples-any-with-invalid.json` | `quality=any` (last item `quality: invalid`, `invalid_reason: range`) | 200 |
| `G-HIST.capture-samples-page1-limit4.json` / `-page2-cursor.json` | `limit=4`, then `cursor=` | 200 |
| `G-HIST.capture-samples-replay-stream.json` | `stream=replay:<uuid>`, `origin: replay` | 200 |
| `G-HIST.capture-samples-empty-window.json` | window with no data | 200 |
| `G-HIST.capture-gaps.json` | one gap, 1500 s | 200 |
| `G-HIST.capture-err-*.json` | naive from / span too long / unknown sensor / bad cursor / limit 5001 / no token | 422 / 422 / 404 / 422 / 422 / 401 (`request_id` replaced by `<uuid>`) |

## CAPTURE 3: enum set observed
`origin` observed: `simulated`, `replay` (`measured` exists in code, not observed). `quality` observed: `ok`, `invalid`. `invalid_reason` observed: `range`, `null`. Not observed: `future`.

## To capture on the real stack (PowerShell, backend checkout root, stack up, user logged in)
```powershell
$base = "http://localhost:8000"
$pw = Read-Host "check-user password"
$t = (Invoke-RestMethod -Method Post -Uri "$base/auth/login" -ContentType "application/json" -Body (@{username="gscn-check";password=$pw} | ConvertTo-Json)).access_token
$h = @{ Authorization = "Bearer $t" }
$fac = (Invoke-RestMethod -Uri "$base/api/facility" -Headers $h)   # record the facility id (expect 1)
$from = (Get-Date).ToUniversalTime().AddHours(-2).ToString("yyyy-MM-ddTHH:mm:ssZ")
$to   = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$sid  = "fac$($fac.id).it_power_kw"
$s = Invoke-RestMethod -Uri "$base/api/telemetry/sensors/$sid/samples?from=$from&to=$to&quality=any&limit=50" -Headers $h
$s.items.Count; $s.unit; $s.sampling_interval_s            # items.Count = 0 on a simulator-only stack: that is the producer gap
$s | ConvertTo-Json -Depth 10 | Out-File -Encoding utf8 real-hist-samples.json
Invoke-RestMethod -Uri "$base/api/telemetry/sensors/$sid/gaps?from=$from&to=$to" -Headers $h | ConvertTo-Json -Depth 10 | Out-File -Encoding utf8 real-hist-gaps.json
$k = { param($f) (Get-Content $f -Raw | ConvertFrom-Json).PSObject.Properties.Name | Sort-Object }
Compare-Object (& $k docs\frontend\contracts\G-HIST.capture-samples-ok.json) (& $k real-hist-samples.json)   # empty = same keys
Compare-Object (& $k docs\frontend\contracts\G-HIST.capture-gaps.json) (& $k real-hist-gaps.json)
# negatives
curl.exe -s -o NUL -w "%{http_code}`n" "$base/api/telemetry/sensors/$sid/samples?from=$from&to=$to"                      # 401
try { Invoke-RestMethod -Uri "$base/api/telemetry/sensors/$sid/samples?from=2026-03-01T12:00:00&to=$to" -Headers $h } catch { $_.Exception.Response.StatusCode.value__ }  # 422
try { Invoke-RestMethod -Uri "$base/api/telemetry/sensors/nope/samples?from=$from&to=$to" -Headers $h } catch { $_.Exception.Response.StatusCode.value__ }          # 404
Remove-Item real-hist-*.json
```
Record: facility id, whether `items.Count` > 0, the `origin` values seen, and whether the anomaly `status` on the live feed is `ok`/scored or stuck in `warming_up`. If the counts are zero, FE-18 proceeds only on the "empty state" basis stated in the gate decision.
To get data without the simulator: `python scripts/seed_facility.py --seed-sensors`, then feed the broker (MQTT) or use the T16/T17 test helpers; seeded values are test values and must never be presented as measured.

## Verification actually run
- `tests/api/test_telemetry_routes.py`: 32 passed (sandbox, SQLite).
- Capture script: temporary test file, deleted after use; no repo file was modified.
- **Not run:** Postgres, docker compose, rate limiting, real login, MQTT end to end, the full suite.

## Open decisions for you
1. **Producer (blocks real data):** approve BE-G1 (simulator writes `ingest_samples`, origin `simulated`, stream `live`), or accept an MQTT-only history for now.
2. **Sensor discovery:** frontend derives `fac<id>.<measurand>`. If you prefer, add `GET /api/telemetry/sensors` (list: external_id, measurand, unit, sampling_interval_s). Not required; FE-18 works without it using the convention and handles the 404.
3. **`origin` alias:** `replay` (telemetry store) vs `replayed` (rest of the stack). FE-18 aliases at the edge. If you would rather change the backend value, say so before FE-18.
4. **Per-rack history:** out of scope (no sensors). FE-18 stays facility-wide (MR Stage C gate).
