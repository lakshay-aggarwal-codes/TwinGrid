# Task 7 (roadmap): CI that can go green honestly (TG-A-08)

(Named `Task7_ci_gates_REPORT.md` because `Task7_REPORT.md` is the earlier observability task.)

## Problem
`ci.yml` had `PYREFLY_ERROR_CEILING: "unset"` (the `types` job fails by design), `pyrefly>=0.30,<1` unpinned, no dedicated audit-regression step, and two advisory frontend jobs.

## Evidence (owner's Windows machine, pass 1 output)
- pyrefly 0.64.1, `pyrefly check --output-format=json`: **881 errors** (36 suppressed, 239 warnings not counted), identical on two runs.
- Breakdown and largest files are in `reports/postT9/T11_ci_run.md`.

## Decisions and trade-offs
1. **Ceiling = 881**, the measured number. Trade-off: it was measured on Windows, not on the Linux runner with `requirements.lock`. The count can differ there. Rule recorded: the first Linux run may raise it once (record run URL); afterwards it only goes down.
2. **Pinned `pyrefly==0.64.1`.** With `>=0.30,<1` any new pyrefly release changes the count with no code change, so a ratchet on it is meaningless. Cost: upgrades are now a deliberate PR that re-baselines.
3. **Added step** `pytest tests/test_audit_regressions.py` in the `test` job, before the full run.
4. **`frontend-e2e` / `frontend-contract` stay `continue-on-error: true`.** No green-run logs were supplied, and the contract job also needs committed real fixtures. Removing the flag would be a guess. Flag removal procedure is in the evidence file.
5. Docs updated: `SECURITY.md`, `docs/governance/BRANCH_PROTECTION.md` (`types` becomes required only after one confirmed green CI run), Issue Register TG-A-08 now PARTIALLY FIXED.
6. 881 is not a quality statement: 410 are `unsupported-operation`, 185 errors sit in one test file and 123 in `src/data_pipeline.py`. Burning those down is the real work; the ceiling only stops it getting worse.

## Files
MODIFY `.github/workflows/ci.yml`, `requirements-dev.txt`, `SECURITY.md`, `docs/governance/BRANCH_PROTECTION.md`, `docs/audit/TwinGrid_Issue_Register.md`. CREATE `reports/postT9/T11_ci_run.md`, `tests/test_ci_gates.py`, this report.

## Tests run
- New `tests/test_ci_gates.py` (5 guards): all 5 pass (sandbox, executed by calling the functions directly because pytest could not be installed there). `ruff check` and `ruff format --check` clean on it (sandbox ruff 0.16.8, CI pins 0.6.9). `ci.yml` parses as YAML.
- NOT run: the full backend suite. Pass 1's `t7_tests_*.txt` / `t7_6_skips.txt` were not uploaded, so I have no evidence about backend failures or real skips on your machine, and `test` job greenness is unverified.
- NOT run: any GitHub Actions job; the Linux pyrefly count; frontend jobs.

## Remaining risks
- First `types` run on GitHub may exceed 881 (see rule 2) and fail once.
- `test` job still fails if any test is skipped or red; unknown until test logs are provided.
- `docker`, `frontend-e2e`, `frontend-contract` unverified in CI.
