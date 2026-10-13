# High 5xx ratio or slow requests

1. Which route? In Prometheus: `sum by (path) (rate(http_requests_total{status=~"5.."}[5m]))`; latency by route:
   `histogram_quantile(0.95, sum by (le, path) (rate(http_request_duration_seconds_bucket[5m])))`.
2. Take a failing request's `X-Request-ID` (the 5xx body also carries it) and read its log lines (see the index).
   Clients never see tracebacks; the server log has the exception.
3. Common causes: database down ([database-down.md](database-down.md)); a model not loaded ([artifact-load-failure.md](artifact-load-failure.md));
   compute-heavy routes answering 429/504 under load (bounded by design, not a 5xx fault).
4. After a deploy: compare with the previous revision and roll back the image if the ratio started with it.
