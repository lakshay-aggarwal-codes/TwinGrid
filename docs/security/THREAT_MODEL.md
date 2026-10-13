# Threat model (Task 6 scope)

| Threat | Control | Where | Residual |
|---|---|---|---|
| Access token captured from a WebSocket URL in proxy/server logs | Single-use 30 s ticket via `POST /auth/ws-ticket`; URL carries only the ticket; log filter redacts `token=`/`ticket=` | `src/ws_tickets`, `api/routes/websocket_routes.py` | `?token=` fallback stays on until `WS_ALLOW_QUERY_TOKEN=false` |
| Ticket replay | One redeem (Redis MULTI GET+DEL); only the SHA-256 is stored; TTL | `src/ws_tickets` | Per-process memory store is dev only; production refuses it |
| Clickjacking / MIME sniffing / referrer leaks (API) | nosniff, `X-Frame-Options: DENY`, CSP `frame-ancestors 'none'`, Referrer-Policy, Permissions-Policy; HSTS only over HTTPS | `api/middleware/security_headers.py` | API CSP is `frame-ancestors` only: a full policy would break `/docs` |
| XSS / injection / framing (frontend) | CSP in `netlify.toml`, `connect-src` = documented API origin | `netlify.toml` | Applies on Netlify only. `style-src 'unsafe-inline'` is needed for React inline styles. Allowances inferred from source, not verified in a browser. If the API origin changes, edit `netlify.toml` |
| Password guessing | 10/min per IP (existing) + (IP, username) lockout with doubling backoff, 429 + `Retry-After`; unknown usernames lock identically; usernames never stored in clear | `src/login_lockout.py` | Process-local counters; distributed guessing across many IPs is limited only by the per-IP limit |
| Metrics / probe information leakage | `/metrics` closed in production without a token; probe bodies carry statuses only, no exception text | `api/routes/*` (tests added) | none found |

## Frontend headers (CSP)
`script-src 'self'` (no inline script in `index.html`); `style-src` adds `'unsafe-inline'` and `fonts.googleapis.com` (Google Fonts `@import` in `index.css`); `font-src` `fonts.gstatic.com`; `img-src` adds `data:` and `blob:`; `worker-src` adds `blob:`. If `VITE_ERROR_REPORT_URL` is set, its origin must be added to `connect-src`.
