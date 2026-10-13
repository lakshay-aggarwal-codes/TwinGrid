# Stale live feed

Signals: UI shows Stale/Disconnected; `LiveFeedStale`; `/readyz` `checks.broadcast` is `stale`, `gave_up` or `not_running`;
`broadcast_heartbeat_age_s` large.

1. `curl.exe -s http://localhost:8000/readyz` and read `broadcast_restarts` and `broadcast_heartbeat_age_s`.
2. `docker compose logs backend --tail 200`: look for the loop's error lines (one JSON object per line) just before the stall.
3. `gave_up` means the supervisor hit its restart cap (default 10 per 600 s) and stopped the loop: fix the cause, then
   `docker compose restart backend`. A plain restart is the only reset.
4. Heartbeat fresh but clients stale: check `ws_dropped_messages_total` (slow clients) and that the browser can reach `/ws/live`
   (proxy WebSocket support, `WS_ALLOWED_ORIGINS`). The frontend reconnects with a ticket, falling back to the token.
