# Task 24 environment variables

All optional; read once when the app starts (`setup(app)` in `api/plugins/performance.py`). With none set, ETag and gzip are on and the response cache is off.

| Variable | Default | Meaning |
|---|---|---|
| `PERF_ETAG` | `1` | `0`/`false`/`no`/`off` removes the ETag middleware. |
| `PERF_ETAG_PATHS` | built-in list | Comma-separated paths that get an ETag (default: the plugin's `DEFAULT_PATHS`). |
| `PERF_GZIP` | `1` | `0`/`false`/`no`/`off` removes gzip. |
| `PERF_GZIP_MIN_BYTES` | `1024` | Smallest response body that is compressed. |
| `PERF_CACHE_NAMESPACES` | empty (cache off) | Comma-separated: `state` and/or `scenarios`. The response cache needs this AND `REDIS_URL`; with Redis down or unset every request is computed as before. Only `live=False` previews are cached; the live twin behind the WebSocket is never touched. |
| `PERF_CACHE_STATE_TTL_S` | `2.0` | Lifetime of a cached `state` response, seconds. |
| `PERF_CACHE_SCENARIOS_TTL_S` | `30.0` | Lifetime of a cached `scenarios` response, seconds. |
| `REDIS_URL` | unset | Shared with the WebSocket ticket store (see `Task6.md`). |

Recreated in the Task 32 sweep from `api/plugins/performance.py`: the plugin's docstring pointed at this file, which was missing from the repository.
