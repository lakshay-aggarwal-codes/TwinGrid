# R3 Task 12 report: failure triage

Status: **Done on pasted evidence** (no code change, so no patch zip).

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

## Optional follow-up (not required to close Task 12)

Run the 75 Postgres-gated tests once against a throwaway Postgres by setting the three variables above, and record the result, or write an explicit waiver that they are CI-only.
