# R3 Task 14 report: docs sync

Status: **Written; closes when you paste the test output below.** I could not run pytest here (no pytest in my sandbox), so the
document tests have not been run on these edits.

Scope: bring the five named documents, and the other pages the R3 reports flagged as stale, in line with what tasks 1 to 13 and
the CI run on PR #87 recorded. Every change names its source. Nothing was claimed that no report or pasted output supports.

## What changed

| File | Change | Source |
| --- | --- | --- |
| `CHANGELOG.md` | Added: what-if `physics_version` and `provenance`; `gate` job, npm audit gate, re-captured contract fixtures; Ember India importer; `baselines-v6`. Changed: what-if chilled-water range per physics version; pyrefly ceiling 944. New Fixed and Security sections (copilot, alert id, future-dated sample, authz overlay, request-id test, waivers, gitleaks allowlist) | `R3_TASK_1/2/4_REPORT.md`, `R3_TASKS_5_TO_10_EVIDENCE.md`, `R3_TASK_11_CI_EVIDENCE.md`, `R_CARBON_REPORT.md`, `recent_commits` |
| `API_DOCUMENTATION.md` | New section on the what-if range and the new response fields | `R3_TASK_1_REPORT.md`, `R3_TASK_2_REPORT.md` |
| `docs/CLAIMS.md` | C-04 (importer, flat level), C-12 (range, provenance), C-26 (28.7 s single run), C-28 (Postgres in CI), C-30 (axe run recorded: 48 passed; manual checks still not signed), C-32 (full suites and CI recorded), C-34 (full suite removed from the "not confirmed" list) | `R3_TASK_12/3/13/11` reports, `R_CARBON_REPORT.md` |
| `docs/roadmap/EVIDENCE_MATRIX.md` | New pytest evidence; J1 to J4 and J6 run output from the owner's machine; CI row now Partial; skips; authz row Met; ML row points at `baselines-v6`; carbon row; closing paragraph | `R3_TASK_12`, `R_L7_REPORT.md`, `R3_TASK_4`, `R3_TASK_11_CI_EVIDENCE.md` |
| `docs/audit/TwinGrid_Issue_Register.md` | New dated reconciliation: TG-A-07, 08, 11, 19, 20, N-05, N-06 updated; R3-01 to R3-06 closed; R3-07 to R3-11 open. Earlier sections left as written | as above |
| `README.md` | Four lines that said no green run was seen now state what was recorded (ids `[C-32]`, `[C-34]` kept) | `R3_TASK_12`, `R3_TASK_3`, CI table |
| `twin-stream-insight-main/docs/frontend/STATUS.md` | `frontend-contract` green once but still advisory; `frontend-e2e` advisory and red; a11y 48 of 48 and viewer-workflow 6 of 6 locally | `R3_TASK_13`, `R_L7_REPORT.md`, CI table |
| `docs/DEMO_CHECKLIST.md` | `rehearsal.ps1` flagged as absent; the non-existent `-Fresh` switch replaced with the `down -v` command; `docker ps` check added; the one measured time (28.7 s) recorded | `R3_TASK_13_REPORT.md` |
| `docs/roadmap/ML-002_RUNBOOK.md` | Marked superseded: the run was made as `baselines-v6`, not `baselines-v5` | `R3_TASK_4_REPORT.md` |
| `docs/roadmap/task-reports/R3_TASK_11_CI_EVIDENCE.md` | Dated update at the end: the two failing tests were read and fixed, PR #87 result | CI table at `cee2af9` |

## Not changed, so no claim is made

- Pages I did not read: `docs/JUDGES.md`, `docs/model_cards/*`, `SECURITY.md`, `docs/api/README.md`, the ADRs, `docs/architecture/*` (apart from one carbon line in `system.md`, which is still true when no carbon file is installed). "No doc contradicts the code" is therefore established for the files in the table, not for the whole repository.
- R3 Tasks 5 to 7 stay "closed on code reading plus 47 passes"; three test names were never displayed (R3-09).
- Nothing about Netlify (R3-08) or the `frontend-e2e` settings (R3-07) was fixed; both are recorded as open.
- I did not change `ci.yml`. By its own rule, `frontend-contract` may now drop `continue-on-error` and join `gate`; that is a policy decision for you.

## Evidence to paste

```powershell
Expand-Archive -Force "$HOME\Downloads\R3_TASK_14.zip" -DestinationPath .
python -m pytest tests/test_task33_claims.py tests/test_task20_docs_consistency.py tests/test_task10_governance.py tests/test_task9_api_reference.py tests/test_ci_gates.py -q -p no:cacheprovider
git diff --stat
```
