# Task 6 environment variables

All are optional and read per call by the module named. Defaults keep today's behaviour (the live feed cannot break).

| Variable | Default | Read by | Meaning |
|---|---|---|---|
| `WS_TICKET_TTL_SECONDS` | `30` | `src/ws_tickets` | Lifetime of a WebSocket ticket. Malformed or <= 0 -> 30; capped at 300. |
| `WS_ALLOW_QUERY_TOKEN` | `true` | `src/ws_tickets` | `false` closes `/ws/live?token=` (4001); only tickets work. Unrecognised value -> `true` (logged). Production with `false` requires `REDIS_URL` (startup rule R13). |
| `REDIS_URL` | unset | `src/ws_tickets` | Ticket store. Without it, tickets use per-process memory in development/test only; production answers 503 on `POST /auth/ws-ticket` and the frontend falls back to the token. |
| `LOGIN_LOCKOUT_ENABLED` | `auto` | `src/login_lockout` | `auto` = follows the shared rate-limit switch; `true` always on; `false` off. |
| `LOGIN_LOCKOUT_THRESHOLD` | `5` | same | Consecutive failures per (IP, username) before the first lock. |
| `LOGIN_LOCKOUT_BASE_SECONDS` | `30` | same | First lock; doubles per further failure. |
| `LOGIN_LOCKOUT_MAX_SECONDS` | `900` | same | Cap on one lock. |
| `LOGIN_LOCKOUT_RESET_SECONDS` | `900` | same | Failures forgotten after this long without one. |

Task 32 should append these to `.env.example` (this task did not touch it).
