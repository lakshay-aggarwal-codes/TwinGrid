# Task 26 environment variables

| Variable | Default | Read by | Meaning |
|---|---|---|---|
| `RATE_LIMIT_CAPACITY` | `12/minute` | `api/plugins/capacity.py` | Rate limit of `GET /api/capacity/headroom` (read on every request). Each call is two 24 h twin runs, executed as one unit under the shared compute bound. |

No other variables. The planning bands (10 % of a limit, 3 °C of thermal margin) and the bounds (0-200 racks, 0.1-60 kW per rack) are constants in `src/capacity/planner.py`.
