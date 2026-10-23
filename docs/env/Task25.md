# Task 25 environment variables

| Variable | Default | Read by | Meaning |
|---|---|---|---|
| `RATE_LIMIT_ECONOMICS` | `12/minute` | `api/plugins/economics.py` | Rate limit of the tariff cost route (read on every request). Each call is two 24 h twin runs executed as one unit under the shared compute bound. |

Recreated in the Task 32 sweep from the code: the plugin's docstring pointed at this file, which was missing from the repository.
