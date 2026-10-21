# R_TASK_7_REPORT: CI hardening and API reference

## Summary
Static work only (no network, no FastAPI, Docker, Node or pyrefly in my sandbox). Findings from reading `TwinGrid-main.zip`:
- `docs/api/` (`openapi.json`, `README.md`) and `scripts/gen_api_reference.py` already exist, so the roadmap's "missing" is wrong for this zip. The `test_task9_api_reference` failures are most likely STALENESS: routes added by later tasks (e.g. `/api/access-requests*`, `/api/copilot/ask`) after the last generation. Hypothesis until you run the check.
- `src/contract/fixtures/` holds only a README: real fixtures need a running backend.
- Ceiling is 881 (Windows `.venv`, pyrefly 0.64.1); no Linux count recorded.
- Required jobs `lint`, `types`, `test`, `test-postgres`, `audit`, `frontend`, `docker` already have no `continue-on-error`. Only `frontend-e2e` and `frontend-contract` are advisory, and their written exit rule (one recorded green run each; contract also needs committed fixtures) is not yet met, so I did NOT flip them.

Done in `ci.yml`: a `gate` job (`needs` the 7 blocking jobs, `if: always()`, fails on failure, cancel or skip) to use as the single required check in branch protection; `timeout-minutes` on every job.

## Acceptance checklist
- `pytest tests/test_task9_api_reference.py -q` passes: NOT MET (not run; regenerate, command below).
- Fixtures committed: NOT MET (BLOCKED: needs Docker backend).
- Ceiling matches the measured number: NOT MET (needs the first Linux `types` run; ratchet rule in `reports/postT9/T11_ci_run.md`).
- Required jobs blocking: MET for the 7 above, plus `gate`; the 2 advisory jobs stay advisory with evidence-based reason.
- CI run link: NOT MET (you push and paste the URL).

## Changed files
- MODIFY `.github/workflows/ci.yml`
- CREATE `docs/roadmap/task-reports/R_TASK_7_REPORT.md`

## Commands run
`yaml.safe_load` of `ci.yml`: parses; 11 jobs, 7 `gate` dependencies, advisory set is exactly `frontend-e2e` + `frontend-contract` (same regex as `tests/test_ci_gates.py::test_only_the_two_docker_stack_jobs_are_advisory`).

## Not run
pytest, ruff, `gen_api_reference.py`, pyrefly, capture script, any CI job.

## Decisions used
Did not hand-write `docs/api/` (rule: generated). Did not lower or raise the ceiling without a measurement. Did not remove `continue-on-error` without a recorded green run.

## Requested cross-task changes
- `tests/test_ci_gates.py` (Task 8 or 5 owner): add a test that `gate.needs` equals every job without `continue-on-error` (except `bootstrap`/`gate`).
- `reports/postT9/T11_ci_run.md`: add the Linux count and run URL row after the first push.
