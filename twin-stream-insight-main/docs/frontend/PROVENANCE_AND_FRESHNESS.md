# Provenance, freshness and session rules

Single places in code: `src/provenance/model.ts` (pure view-model), `src/provenance/labels.ts` (every user-facing string), `src/telemetry/freshness.ts` and `src/hooks/liveness.ts` (state machine), `api/wsTransport.ts` and `src/authClient.ts` (transport and session). Backend free text never reaches the DOM through provenance; only the fixed copy in `labels.ts` does.

## Origin (what the values are)

| Shown as | When |
|---|---|
| **Measured** | only for the exact backend value `measured` |
| **Simulated** | backend value `simulated` (physics simulator; never styled like measured) |
| **Replayed (not live)** | backend value `replay` / replayed stream |
| **Unverified source** | origin absent, unknown or differently cased. This is the safe default. |

The endpoint kind (`live-feed`, `preview`, `run-result`, `evaluation`, `topology`, `alert`, `report`) only ever *adds* a label such as **Preview**; it never raises trust. Derived origin is the backend's: the client does not compute a "lowest-evidence" origin.

Quality is `good`, `suspect`, `invalid` or `unrecognised` (unknown backend values stay unrecognised and are shown, not hidden). Further caveat labels: **Simulator-only**, **Uncalibrated**, **Fallback carbon (flat constant)**, **Fallback input**. Missing fields appear as an explicit `not reported` row, never `0` or blank. Every state has its own icon shape plus text, so colour is never the only cue.

## Three different times

| Row | Meaning |
|---|---|
| Last updated, **server time** | the backend's data/ingest timestamp |
| Last updated, **simulated clock** | the simulator's clock |
| Last received, **browser receipt age** | monotonic age since the browser received the last valid frame |

Browser time is never data time, and a server timestamp is never compared with the browser clock.

## Freshness states

`connecting → live → stale → disconnected → reconnecting → live`, plus `unavailable` when `/healthz` says the backend is down.

- **Live requires an open socket and a fresh, valid frame received on that socket.** An `open` event alone never yields live. After a reconnect the state stays `reconnecting` until a valid frame arrives on the new connection.
- **Stale window** = `max(5 s, 3 × the feed interval)` (`MIN_STALE_AFTER_MS`, `STALE_INTERVAL_MULTIPLIER`).
- Age is measured on a monotonic clock from the moment of receipt. While not live, the last known value keeps showing with its age; it never reads as current.
- Live regions announce state *transitions*, not every feed tick.

## Authentication and sockets

- **Access token** lives in memory only. **Refresh token** lives in `sessionStorage` (this tab only; accepted risk, see [RISKS.md](RISKS.md)). Refresh is single-flight (refresh tokens are single-use on the server), proactive with a 60 s margin, and once on a 401.
- Sign-out clears the query cache and closes the socket. A failed refresh signs out with the notice "Session ended".
- WebSocket token goes in the query string (`/ws/live?token=…`; accepted risk). The error reporter redacts `token=`.

| Close code | Meaning | Client behaviour |
|---|---|---|
| 4002 | access token expired mid-session | refresh once, reconnect immediately (never loops without a valid frame between) |
| 4001 | invalid/missing token | refresh once and retry; a second 4001 → sign-in screen |
| 4004 | Origin not allowed | stop; persistent configuration error, not retried |
| 4003 / 4005 | connection cap / rate limit | exponential backoff, with a "Too many connections/messages" message |

- **Authorisation is UX only.** Operator-only controls (optimise, acknowledge) are disabled for viewers with the text "Requires operator role"; a server 403 is still handled and is final.
- Errors shown to users use `safeMessage` copy; the reporter sends codes and paths, never payloads or tokens.

## Evaluation and recommendation views (Task 14)

| Item | Where it is shown | Rule |
|---|---|---|
| **Physics executed** | evaluation identity strip + provenance detail | The backend's `physics_version_executed`. Absent (reports written before it existed) reads "not reported", never the registered label. When label and executed differ both are shown, e.g. `legacy-0 (registered as "legacy-0 (implicit)")`. |
| **Carbon signal** | evaluation identity strip + the strip's `Fallback carbon (flat constant)` flag + a caveat under every carbon column | Only `carbon.is_real === true` reads Measured. `false` reads Assumed. Missing reads "not reported", never real. |
| **Hard constraints** | a panel BEFORE the metrics table (`HardConstraintPanel`) | Four limits (outlet, inlet-over, inlet-under, PUE). Mean violating steps per test episode: `0` means none, `>0` means at least one episode violated. A limit the report did not count is **not measured**, never zero, and can never produce a "clean" status. Words + a distinct icon shape per state; no success styling. Separate from reward. |
| **Comparator caveat** | same panel | Shown only when `selection.best_constant_envelope_feasible === false`. |
| **Run id / time** | strip (`Run <evaluation_id>`) + identity rows | Server time only. |
| **Validation status** | outcome banner | `NOT_EVALUATED` and unknown outcomes use the same neutral banner as A/B/C. |
| **Recommendation** | `ProvenanceStrip` (origin Simulated, physics, fallback carbon) + fixed evidence note | The stored validation reward is a simulated validation-set score: not a test-set result and not measured. |
| **Set-point range** | recommendation form | The accepted range is the union of the legacy 5..15 C and the evaluated actuator range from `predicted.setpoint_check` (physics 1: 5..25 C), mirroring the server, which still decides. Outside the evaluated range, a words-only notice is shown. |

Schema: `schema_version` 1 and 2 are accepted (2 = amendment A2, counted PUE limit); anything else is a contract violation.
