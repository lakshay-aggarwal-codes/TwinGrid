# Task 15 environment variables

| Variable | Default | Read by | Meaning |
|---|---|---|---|
| `RATE_LIMIT_WHATIF_SWEEP` | `6/minute` | `api/plugins/whatif.py` | Rate limit of the what-if sweep route (read on every request). One call runs up to `src.whatif_sweep.MAX_SWEEP_RUNS` isolated what-if computations as one unit under the shared compute bound and timeout. |

Recreated in the Task 32 sweep from the code: the plugin's docstring pointed at this file, which was missing from the repository.
