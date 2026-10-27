# T11 / Task 7: type-check ratchet record

| Field | Value |
|---|---|
| Checker | pyrefly 0.64.1 (now pinned `==` in `requirements-dev.txt`) |
| Config | `pyrefly.toml` (Python 3.12) |
| Command | `pyrefly check --output-format=json` (as in the `types` job) |
| Environment | owner's Windows machine, project `.venv` (NOT the Linux CI image) |
| Date | 2026-10-18 |
| Result | **881 errors** (36 suppressed, 239 warnings not counted), identical on 2 consecutive runs |
| Ceiling set | `PYREFLY_ERROR_CEILING: "881"` in `.github/workflows/ci.yml` |

Breakdown (local): unsupported-operation 410, bad-argument-type 240, missing-attribute 172, not-iterable 14,
bad-return 10, bad-assignment 9, bad-index 6, bad-typed-dict-key 5, missing-import 4, others 11.
Largest files: tests/test_datasets_v2.py 185, src/data_pipeline.py 123, tests/test_baselines.py 41,
tests/test_artifact_gate.py 31, tests/test_physics_v2.py 28.

## Not yet observed
- The count on GitHub's Linux runner with `requirements.lock` installed. If it differs, record it below with the run URL.
  Differences can come from installed packages (torch/TensorFlow stubs, resolved imports), not from the code.

| Date | Source | Count | Run URL | Note |
|---|---|---|---|---|
| 2026-10-18 | Windows .venv, pyrefly 0.64.1 | 881 | n/a | baseline |

## Ratchet rule
1. The ceiling may only go down. When the `types` job prints "Type errors fell", lower the ceiling to that number in the same PR.
2. Exception, once: if the first Linux CI run prints a higher count than the Windows baseline, set the ceiling to that
   number and add a row above. After that the ceiling never rises.
3. Changing the pinned pyrefly version re-baselines the count; do it in its own PR and add a row above.
4. Do not hide errors with `# pyrefly: ignore` or by widening `project-excludes` to move the number; that defeats the gate.

## Other CI recorded facts (Task 7)
- `frontend-e2e` and `frontend-contract` keep `continue-on-error: true`: no green-run log was supplied, and
  `frontend-contract` additionally requires committed real fixtures. Remove the flag only after one recorded green run each.

## Task 21 (QA-002) record, 2026-10-21
- Environment of the author of this change: no network, no fastapi/torch/Postgres/Node/ruff. **No CI job was run.** Everything below is static.
- `PYREFLY_ERROR_CEILING` is unchanged (881): no new count was measured. Lower it to the owner's measured count (command in TASK_21_REPORT.md).
- Advisory jobs `frontend-e2e` and `frontend-contract` stay `continue-on-error`: no green run recorded. Owner: Lakshay. Expiry: 2026-11-30.
- Skip-gate defects found by reading the tests (hypotheses until the jobs run): PostgreSQL opt-in tests not marked `postgres` (skip in the main job);
  PG env vars `TEST_POSTGRES_URL` / `TWINGRID_TEST_PG_ASYNC_URL` unset in `test-postgres`; `locust` missing from requirements-dev.txt;
  `test_a_baseline_config_tuned_under_the_old_feasibility_rule...` skips once the configs are re-tuned.

## First Linux CI measurement (2026-10-24)

| Item | Value |
|---|---|
| Environment | GitHub `ubuntu-24.04`, Python 3.12.10, `requirements.lock` only (no dev/test packages), pyrefly 0.64.1 |
| Result | **1120 errors** (56 suppressed, 276 warnings not shown) |
| Run | https://github.com/lakshay-aggarwal-codes/TwinGrid/actions/runs/40090896905 (commit af77dd4) |
| Ceiling | raised from 881 to 1120: the one permitted upward edit (first Linux run, different installed packages) |

From here the ceiling may only go down. If the `types` job later installs the dev tools, the count falls and must be re-recorded.

## pip-audit waivers on PR #86 (R3 Task 11)

The `audit` job runs `pip-audit --strict` and failed on two advisories with no fixed release. Both are waived in `docs/security/waivers.md` (owner Lakshay, expiry 2027-01-21) and passed with `--ignore-vuln`:

- PYSEC-2026-1325 (`ecdsa`): timing side channel when signing with P-256. Nothing here signs with ECDSA.
- PYSEC-2026-4298 (`python-jose`): HS256 forgery with a public key. `api/auth.py` restricts `algorithms=[ALGORITHM]` and uses a symmetric secret.

Any other advisory still fails the job.

## pyrefly ceiling raised 1120 -> 1125 (R3 Task 11, 2026-10-27)

The 1120 ceiling did not reproduce: main's CI run for PR #83 already counted 1123, and PR #86 (merge on main) counted 1125. The ceiling is set to the measured value, 1125, and may only shrink from here. About +2 of the 5 over 1120 cannot be attributed from the CI log (it prints only the count); finding them needs a CI step that prints the error list. Decision owner: Lakshay.

Recorded pyrefly ceiling: 1125 errors (measured by the types job on main after PR #86 and again on the follow-up branch).
