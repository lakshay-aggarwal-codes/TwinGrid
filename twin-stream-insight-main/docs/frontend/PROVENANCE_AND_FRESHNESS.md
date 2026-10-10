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
