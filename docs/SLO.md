# Service level objectives (hypotheses, NOT MEASURED)

No target below has been measured, load-tested or agreed with anyone. They are starting points to be replaced once the
stack has run under a real load and the metrics exist to judge them. Nothing in this repository claims they are met.

| Objective (hypothesis) | Indicator | Target | Status |
|---|---|---|---|
| API availability | `up{job="twingrid-api"}` | 99% of a rolling 7 days | NOT MEASURED |
| Request errors | `http_requests_total` 5xx share | below 1% | NOT MEASURED |
| Request latency | `http_request_duration_seconds` p95 | below 1 s (read routes) | NOT MEASURED |
| Live feed freshness | `time() - background_loop_last_success_timestamp{loop="broadcast"}` | below 15 s | NOT MEASURED |
| Telemetry persistence | `telemetry_persist_failures_total` | 0 failures per day | NOT MEASURED |

Alerts in `deploy/observability/prometheus/alert_rules.yml` use looser thresholds than these targets. They are configured, not
verified. Metrics are process-local counters: they reset on restart and do not add up across replicas.
