# Task 23 environment variables

Task 23 adds **no new environment variables**. The fan-out limits it tests already exist (read per call in `api/config.py`):

| Variable | Used by | Meaning |
|---|---|---|
| `BROADCAST_MODE` | `live_broadcast_service` | `sequential`/`serial` = rollback to the awaited one-by-one send. Anything else = per-client queues (default). Both modes share one pre-serialised frame. |
| `WS_SEND_TIMEOUT_S` | same | A send that does not finish in this time closes that client with 1013. |
| `WS_CLIENT_QUEUE_MAX` | same | Per-client queue depth; when full the oldest frame is dropped (newest state wins). |
| `WS_MAX_CONSECUTIVE_DROPS` | same | This many dropped frames without one completed send closes the client with 1013. |
| `WS_MAX_CONNECTIONS_PER_USER`, `WS_MAX_CONNECTIONS_GLOBAL` | `websocket_routes` | Connection caps; the extra socket is closed with 4003. |

Frontend constants (not env): backfill window cap 1 h (`MAX_BACKFILL_WINDOW_MS`), one page of 5000 samples per measurand (five requests per gap), reconnect jitter +-25% (`JITTER_SPREAD`).
