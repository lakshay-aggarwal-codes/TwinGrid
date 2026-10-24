# R_TASK_6_REPORT: Authorization matrix actually enforced

Status: **DONE** (2026-10-24). `tests\test_authz_matrix.py` collects and passes (183 tests in the owner's runs: 247 collected in the L3 verify, minus 7 and 57 from the other two files); it also passes in the full run (5676 passed, 3 skipped, 81 deselected (postgres), 9 xfailed, 0 failed).

## Summary
Read `tests/authz_matrix.py`, `tests/test_authz_matrix.py` and the four fragments (`core`, `T9`, `T13`, `T14`).
- The loader already supports the `demo` overlay: a row holding only `method`, `path_template`, `demo` is merged into the
  full row another fragment owns (T13 overlays rows from `core`, `T9`, `T14`). This is confirmed by reading the code, not by a run.
- Gaps against the Task 6 card, now covered by new tests: nothing asserted that every `app.openapi()` route has a matrix row
  (the old openapi test only checked documented routes are served), and the demo token was probed on write routes only.
- No existing test was changed, skipped or relaxed.

## Acceptance checklist
- Collects: NOT VERIFIED (not run). Read-only review found no loader error for any of the four fragments.
- Every fragment loads: test added (`test_every_fragment_loads_and_the_demo_overlay_is_merged`); not run.
- Fails if any `app.openapi()` route lacks a row: MET in code (`test_every_openapi_route_has_a_row_in_the_matrix`); not run.
- Every token type (anonymous, viewer, operator, admin, demo) tested: MET in code. Roles via the existing per-route test;
  demo via the existing write-route test plus `test_a_demo_token_reads_exactly_what_a_viewer_reads` (read routes, expectation = viewer cell).
  `test_every_token_type_is_probed_on_every_route_or_the_gap_is_a_listed_public_write` fails if any other gap appears.
- Counts printed: run `pytest tests/test_authz_matrix.py -q -s -k coverage_counts`; it prints `authz-matrix-coverage: ...`. Counts NOT YET KNOWN.

## Known gap (decision for the owner)
Public write routes have no demo cell: POST `/api/access-requests`, `/api/access-requests/resend-activation`,
`/api/access-requests/activate`. By `api/demo_guard.py`, a demo token on them gets 403 `demo_read_only` (not in `ALLOWED_DEMO_WRITES`),
so a demo visitor cannot submit an access request while holding a demo token. Not asserted, because whether that is intended is a product decision.
Add `demo: 403` rows to `T9.yaml` if intended, or allow-list the paths in the guard if not.

## Changed files
- MODIFY `tests/test_authz_matrix.py` (new section "Task 6: coverage": 5 tests + 1 parametrized)
- MODIFY `tests/authz_matrix.d/T13.yaml` (stale header comment only; no row changed)
- CREATE `docs/roadmap/task-reports/R_TASK_6_REPORT.md`

## Commands run
`python3 -m py_compile tests/test_authz_matrix.py` (ok).

## Not run
`pytest tests/test_authz_matrix.py -q` and the count command above (cloud workspace has no package access). Expected on your machine:
all pass. If a new test fails, the failure message names the route; send me the output.

## Decisions used
Demo expectation on a read route defaults to the viewer cell (a demo token is a viewer token; the guard only blocks writes). Public writes may omit a demo cell.

## Requested cross-task changes
None.

## L4 update (2026-10-24): run evidence
The "NOT RUN" and "NOT VERIFIED" lines above are superseded. `tests\test_authz_matrix.py` shows only passes in `C:\twlogs\pytest_full_final.txt`, so the four fragments load, the demo overlay is merged and every `app.openapi()` route has a matrix row. Caveat: L3 changed the matrix inputs (the three public access-request POSTs are allowed to a demo token, decision D3) and the file still passes afterwards. Not covered here: the two CI jobs that run it (`ci.yml`), see L6.
