# R3 Task 12 report: failure triage

Status: **Done on pasted evidence** (no code change, so no patch zip). Updated with the CI result below.

## Evidence

| Run | Command (repo root, Windows, Python 3.12.10, pytest 8.4.2) | Result |
| --- | --- | --- |
| Full suite | `python -m pytest -q -rf --tb=line -p no:cacheprovider` | **5741 passed, 78 skipped, 1 deselected, 0 failed** in 2:40:34 |
| Skips only | same flags plus `-rs` on the 7 files that skip | 251 passed, 78 skipped, 0 failed in 1:13 |

Outputs kept: `r3_t12_full.txt`, `r3_t12_skips.txt`. `r3_t12_failed.txt` was empty, because no line began with `FAILED` or `ERROR`.

## Failing tests

**Real failures: 0. Sandbox-only failures: 0.** There is nothing to fix or waive.

The roadmap's "~94 pre-existing failures" could not be reproduced. The only older record in the repo is `pytest_full3.txt`. It is cut off at 38% and shows 50 failures in 16 files, with no ids and no causes. The suite selection also differed then (5689 selected, 81 deselected, against 5819 selected, 1 deselected now), so the two runs are not directly comparable. The ~94 figure has no record behind it.

## Skips (78) by cause

| Cause | Count | Where |
| --- | --- | --- |
| Postgres not configured, `TWINGRID_TEST_PG_ASYNC_URL` not set | 70 | `tests/test_telemetry_ingest.py` (37 skip sites) |
| Postgres not configured, `TEST_POSTGRES_URL` not set | 3 | `tests/test_audit_migration.py:156, 173, 195` |
| Postgres not configured, `TWINGRID_TEST_PG_URL` not set | 2 | `tests/test_provenance_m1.py:220`, `tests/test_time_contract.py:461` |
| Platform or client limit (symlinks not available) | 1 | `tests/test_artifact_integrity.py:205` |
| Platform or client limit (Windows keeps a closed localhost port from resetting at once, so the SMTP timeout fires first) | 1 | `tests/test_notify_mail.py:153` |
| Platform or client limit (the test client refuses to send that header) | 1 | `tests/api/test_error_contract.py:226` |
| **Total** | **78** | |

No skip is caused by TensorFlow. All 78 are reported by the tests themselves as an unset Postgres variable or a platform limit.

## Claims, checked or assumed

- **Checked:** 0 failures in the full suite, and the skip reasons above, both from pasted output.
- **Not verified:** the 75 Postgres-gated tests have never run in the evidence I hold. Their behaviour against a real Postgres is unknown, so I make no claim that they pass. This matters for the Task 15 verdict.
- **Assumed:** the 1 deselected test is the `live_llm` one (the marker is defined in `pytest.ini`, and an earlier Task 10 run also showed 1 deselected). Not confirmed by this run.

## CI evidence added later (PR #87, branch head `440098c`, `gh pr checks`)

- `CI/test` (Linux, 14 min): **passed**. `CI/test-postgres` (2 min 23 s): **passed**. The workflow gives that job a real Postgres and sets all three variables the skipped tests wait for (`TWINGRID_TEST_PG_URL`, `TEST_POSTGRES_URL`, `TWINGRID_TEST_PG_ASYNC_URL`).
- This probably covers the 75 Postgres-gated skips above. I read the job's environment from the workflow file, not its log, so I have not confirmed it ran exactly those tests.
- The first CI run (`c04d895`) had two real failures, `test_ci_gates.py::test_ceiling_is_recorded_in_the_evidence_file` and `test_task10_governance.py::test_gitleaks_config_parses_and_allowlist_is_only_documented_placeholders`. They were introduced after the full local run above and fixed by `cee2af9` and `440098c`. They are not pre-existing failures, so they do not change the zero-failure triage result; they are recorded in `R3_TASK_11_CI_EVIDENCE.md`.
- The 5741 count is a snapshot from the earlier commit. It is not the current total. A current local count needs a new full run.

## Remaining skips (3, platform limits, unchanged)

Symlinks not available, SMTP closed-port timing on Windows, and a header the test client refuses to send. These are Windows or client limits, not defects.
