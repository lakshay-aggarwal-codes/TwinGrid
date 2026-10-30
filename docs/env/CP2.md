# CP-2 environment: Copilot failover router

| Variable | Default | Meaning |
|---|---|---|
| `COPILOT_LLM_BUDGET_S` | `12` | Time budget for the whole provider chain per question, 0.5-120 s. A bad value gives 12. Each attempt gets `min(provider timeout, time left)`; below 0.25 s left no new attempt starts. |

Everything else (the provider list and per-provider settings) is CP-1: see `docs/env/CP1.md`.

## Behaviour (fixed in code, not configurable)

| Failure | What the router does |
|---|---|
| HTTP 429 | Cooldown 60 s, doubling on each consecutive failure (cap 900 s). A numeric `Retry-After` is respected if longer (cap 3600 s). |
| 5xx, timeout, network, bad envelope, bad JSON, oversized reply, other 4xx | Same, with a 30 s base. |
| HTTP 401 / 403 | Provider disabled until the process restarts. One log line, once. |
| Answer rejected by the rule checks | No cooldown. One more provider is tried, then rule-based with `llm_rejected`. |
| Everything failed or skipped | Rule-based answer plus `llm_unavailable`. |

A success resets that provider's failure count. With exactly one usable provider no state is kept (Task 24 behaviour).
State is in-process and per worker: with several workers each learns about a dead provider on its own.

Log lines: the per-attempt line from CP-1, plus
`llm_chain outcome=<ok|rejected|unavailable> attempts=<name>:<outcome>,... total_ms=<n>`.
Provider names and our own outcome words only.
