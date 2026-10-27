# R3 Task 11: CI result for PR #87

Status: **Done: the CI run is recorded, with the failures named.** Two real test failures are open and are not fixed here. Their causes are not yet read.

PR: https://github.com/lakshay-aggarwal-codes/TwinGrid/pull/87 (`wip/bc10-run-contract` into `main`, branch head `c04d895` at the time of the run). CI run id `40384681510`; the log is `r3_t11_failed_log.txt` (1.4 MB, kept out of Git).

`gh pr checks`: **11 successful, 7 failing, 1 skipped, 0 pending, 0 cancelled.**

## Passing

`lint`, `types`, `audit`, `docker`, `frontend`, `frontend-contract`, `test-postgres`, CodeQL (Python, JavaScript/TypeScript), gitleaks.

## Failing, with the cause as far as the log shows

| Check | Cause | Kind |
| --- | --- | --- |
| `test` (18 min) | Exactly two tests failed: `tests/test_ci_gates.py::test_ceiling_is_recorded_in_the_evidence_file` and `tests/test_task10_governance.py::test_gitleaks_config_parses_and_allowlist_is_only_documented_placeholders`. Both pass in your local runs on Windows. | Real, cause not read yet |
| `gate` (2 s) | `results: success success failure success success success success` then `a blocking job did not succeed (failure)`. It fails because a blocking job, `test`, failed. It is not a separate defect. | Consequence |
| `frontend-e2e` (12 min) | The specs stopped for lack of settings the workflow does not provide: `E2E_ADMIN_USERNAME` and `E2E_ADMIN_PASSWORD`, `E2E_SMTP_PORT`, and `TRUST_PROXY_HEADERS=true` with `E2E_TRUST_PROXY=1`. The workflow sets only `E2E_VIEWER_*` and `E2E_OPERATOR_*`. The remaining "element(s) not found" errors followed. The backend did come up: the step text "backend did not become healthy" is the script source printed in the log, not a failure, and the tests ran for 10 minutes after it. The job is advisory (`continue-on-error`, a test asserts only `frontend-e2e` and `frontend-contract` are advisory) and is not in the gate's `needs`. | CI configuration gap |
| Netlify: Header rules, Pages changed, Redirect rules, deploy preview | One deploy, `6adfa628e9b33ccb00f8faa3`, "Deploy Preview failed". **Cause not seen.** The Netlify log was not read. | Not diagnosed |

`CI/bootstrap`: skipped.

## What this means

- The only blocking failure is `test`, so the PR cannot go green until those two tests are explained. Whether to merge before that is your decision; the gate is red now.
- The two failing tests are not related to Tasks 1 to 10 on their face (a ceiling number in an evidence file, and a gitleaks allowlist pattern), but the causes are not read, so that is not confirmed.
- Your local full run (5741 passed) and CI differ. A pull-request run tests the merge of the branch with `main`, not the branch alone, which could explain a local pass and a CI failure. This is a possibility only.

## Not verified

The tracebacks of the two failing tests; the Netlify deploy log; whether `main` carries commits the branch lacks.

## Update 2026-10-28 (R3 Task 14): this report was written before the follow-up PR; read this section first

PR #86 was merged to `main` while its checks were red. The fixes are in follow-up PR #87 (same branch).

- The two failing `test` tests have now been read. Both were caused by edits made during this task, not by Tasks 1 to 10:
  `test_ceiling_is_recorded_in_the_evidence_file` needed the exact text `<ceiling> errors` in `reports/postT9/T11_ci_run.md`;
  `test_gitleaks_config_parses_and_allowlist_is_only_documented_placeholders` rejected an allowlist entry
  (`e2e-pepper-...`) that did not read as a placeholder. Both were fixed in `cee2af9` (the pepper is now `e2e-test-pepper-...`).
- Other fixes: the npm audit step now uses `scripts/npm-audit-gate.mjs` with a recorded `zod` waiver; the two pip-audit
  advisories are waived with an owner and expiry; a non-ASCII request-id test no longer skips; the contract fixtures were
  re-captured; the gitleaks allowlist names the e2e placeholder; the pyrefly ceiling is 944 on Linux.
- `gh pr checks 87` at `cee2af9`: `lint`, `types`, `test`, `test-postgres`, `audit`, `frontend`, `frontend-contract`, `docker`,
  `gate`, gitleaks and CodeQL green. Red: `frontend-e2e` (advisory) and the four Netlify checks (cause not read).
- Still not read: the Netlify deploy log; whether the one e2e failure group beyond the missing `E2E_*` settings has another cause.
