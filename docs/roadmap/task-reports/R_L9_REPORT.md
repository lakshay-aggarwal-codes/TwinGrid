# R_L9: readiness verdict

**Verdict: PARTIALLY READY.** Written 2026-10-28 from the reports and pasted run output listed below. Nothing here was re-run.

What the verdict means. TwinGrid can be shown as a **simulation-only** data-centre digital-twin project, on the owner's machine with the local stack, with the claims in `docs/CLAIMS.md`. It is **not** ready to be presented as verified end to end in CI, as deployed, or as having a signed accessibility review. This is an assessment from existing evidence. It is not the playbook's release-candidate gate (Task 31, never run), so `RC_REPORT.md` and `evidence/status.json` are still not created.

Rule used: a line is in the "evidenced" table only if a named report or pasted output backs it. Anything else is a gap. Evidence dates differ, and CI was last observed at commit `cee2af9` (PR #87); later commits (a ceiling change to 944 and documentation) were not observed in CI.

## Evidenced (what is true today)

| # | Claim | Evidence (report) | Kind |
| --- | --- | --- | --- |
| E1 | Backend suite: 5741 passed, 78 skipped, 1 deselected, 0 failed | `R3_TASK_12_REPORT.md` | Owner's run, Windows, 2026-10-26 |
| E2 | Frontend suite: 185 files, 2401 tests passed, 0 failed; what-if lab 68 passed | `R3_TASK_3_REPORT.md` | Owner's run, 2026-10-26 |
| E3 | CI blocking jobs green on PR #87 at `cee2af9`: `lint`, `types` (ceiling then 1125, now 944), `test`, `test-postgres`, `audit`, `frontend`, `docker`, `gate`, plus gitleaks and CodeQL; `frontend-contract` green but advisory | `R3_TASK_11_CI_EVIDENCE.md` (update section) | CI run |
| E4 | What-if lab and API agree: the server accepts the active physics version's chilled-water range, and responses carry `physics_version` and `provenance` | `R3_TASK_1_REPORT.md`, `R3_TASK_2_REPORT.md`, `R3_TASK_3_REPORT.md` | Owner's test runs |
| E5 | Authorization matrix enforced: 183 passed | `R3_TASKS_5_TO_10_EVIDENCE.md` | Owner's run |
| E6 | Demo session may ask the assistant; copilot signal lookup, alert-id handling and future-dated samples fixed in code; 47 targeted tests passed | `R3_TASKS_5_TO_10_EVIDENCE.md` | Owner's run plus code reading (three test names not displayed) |
| E7 | Stored ML comparison `baselines-v6`, recorded on a clean tree on the current lock and configs; verify prints one expected `code_revision` FAIL after later commits | `R3_TASK_4_REPORT.md` | Owner's `repro verify` output |
| E8 | ML claims are held to the registered outcome: PPO outcome `C`, claim allowed none; no energy-saving claim | `docs/CLAIMS.md` C-06 to C-08, `docs/roadmap/EVIDENCE_MATRIX.md` | Ledger, checked by `tests/test_task33_claims.py` (passed, `R3_TASK_14_REPORT.md`) |
| E9 | Browser drills passed on the owner's machine: sequence restart, token expiry, unknown data, refresh mid-approval, dead links, db-down 6/6, redis-down 5/5, mail-failure 3/3, history-gap 9/9, large-data 12/12; viewer-workflow 6 of 6; stale-surfaces 1; real-backend 1 | `R_L7_REPORT.md` | Owner's runs, 2026-10-24 to 26 |
| E10 | Automated accessibility: 48 passed, zero serious or critical axe findings across the listed routes, light and dark, plus focus, reduced-motion and 320 px reflow checks | `R3_TASK_13_REPORT.md` | Owner's run, 2026-10-26 |
| E11 | One measured demo start: `demo.ps1` after a reset with cached layers, 28.7 s; `repro verify baselines-v6` 6.44 s | `R3_TASK_13_REPORT.md` | Single runs, one machine |
| E12 | Dependency risk is recorded, not hidden: two pip-audit and one npm advisory waived with owner and expiry; no patched release exists for them | `docs/security/waivers.md`, `docs/frontend/waivers/npm_audit.md`, `R3_TASK_11_CI_EVIDENCE.md` | Waiver files |
| E13 | Claims and docs are consistent for the files checked: 37 document tests passed | `R3_TASK_14_REPORT.md` | Owner's run |
| E14 | Carbon is labelled honestly: flat assumed 475, or an Ember India level that is flat across the day and says so | `R_CARBON_REPORT.md` (verdict PARTIAL) | Tests per report; owner's install open |

## Gaps (what is not true, or not shown)

| # | Gap | Why it matters | Source |
| --- | --- | --- | --- |
| G1 | `frontend-e2e` is red in CI and advisory: the job does not set `E2E_ADMIN_*`, `E2E_SMTP_PORT` or the trust-proxy variables. The same specs pass locally | The browser journeys have no CI evidence | `R3_TASK_11_CI_EVIDENCE.md`, `R_L7_REPORT.md` |
| G2 | Netlify deploy preview and three Netlify checks fail; the deploy log was never read | If the public site is the face of the project, its state is unknown | `R3_TASK_11_CI_EVIDENCE.md` |
| G3 | Assistant drill AI-D-3 ("Explain this" on `/alerts`) failed when L7 was reported; whether it was fixed or waived was not confirmed, and `L7_real_stack_gates.md` was not read for this verdict | A visible dead button in a demo path | `R_L7_REPORT.md`, `R3_TASKS_5_TO_10_EVIDENCE.md` |
| G4 | Task 13 is Open: the nine-step demo script has never been run against a stopwatch; `scripts/rehearsal.ps1` does not exist; the manual accessibility pass (screen reader, 200% zoom, keyboard-only) is not done; FE-19 is NOT SIGNED | No timing or accessibility claim can be made beyond the automated run | `R3_TASK_13_REPORT.md` |
| G5 | No clean-clone install or rehearsal has ever been recorded; `drill_clean_install.sh` was deliberately not run | The first-run experience is unknown | `R_L7_REPORT.md`, `README.md` Status, `docs/CLAIMS.md` C-34 |
| G6 | No real mailbox has been tried (J3 blocked) | Owner-approves-on-a-phone is only shown over a local SMTP path | `docs/roadmap/EVIDENCE_MATRIX.md` |
| G7 | The 75 Postgres-gated backend tests have not run on the owner's machine; they ran only in CI's `test-postgres` | Local and CI evidence differ | `R3_TASK_12_REPORT.md`, `R3_TASK_11_CI_EVIDENCE.md` |
| G8 | Not confirmed by any run: the PDF report render, an asynchronous optimize job through the worker, migrations on a managed PostgreSQL, any real deployment | Features exist in code only | `docs/CLAIMS.md` C-34 |
| G9 | Time-of-day carbon is not available (the level is flat); the demo container did not see the installed file when last reported | Carbon-aware conclusions reduce to energy ranking | `R_CARBON_REPORT.md`, issue register TG-A-11 |
| G10 | ML evidence is limited: the forecaster's earlier figure is unbaselined, the anomaly threshold was tuned on the rows it was scored on, PPO is outcome `C` | Nothing here supports an ML-benefit claim | `docs/CLAIMS.md` C-06 to C-08 |
| G11 | The release pipeline has never run on a tag; branch protection is documented but not applied; PR #86 was merged with red checks and `main`'s own runs were red | Process controls are written, not exercised | `docs/CLAIMS.md` C-27, `R3_TASK_11_CI_EVIDENCE.md` |
| G12 | Performance budgets and SLO targets are unmeasured | No performance claim is allowed | `docs/CLAIMS.md` C-25, C-31 |
| G13 | Documents not read for this verdict: `docs/JUDGES.md`, model cards, `SECURITY.md`, ADRs, `docs/architecture/*` | Consistency is shown only for the files in `R3_TASK_14_REPORT.md` | `R3_TASK_14_REPORT.md` |
| G14 | Waivers expire: `ecdsa` and `python-jose` 2027-01-21, `zod` and the Tailwind chain 2027-01-13 | An expired waiver is a failed review | `docs/security/waivers.md`, `docs/frontend/waivers/npm_audit.md` |

## What would move it to READY, in order

1. **G1**: set the missing `E2E_*` variables in the `frontend-e2e` job, record one green run in `reports/postT9/T11_ci_run.md`, then remove `continue-on-error` there and, once it is green, on `frontend-contract` (which has already been green once) and add both to `gate`.
2. **G2**: read the Netlify deploy log and fix or record the cause.
3. **G3**: read `docs/frontend/waivers/L7_real_stack_gates.md`; fix AI-D-3 or state the waiver in this report.
4. **G4**: run the nine-step script twice with a stopwatch, do the four manual checks, then decide whether `rehearsal.ps1` is written or dropped from the checklist.
5. **G5, G7**: one clean-clone run, and one local run of the Postgres-gated tests against a throwaway database.
6. G6, G8 to G14 stay as written limits unless the project's purpose needs them.

## Not verified here

- CI after commit `cee2af9`.
- Whether any R_L4, R_L5 or R_L8 report exists beyond the ones cited; none were supplied for this verdict.
- The L7 waiver file itself.

## Update 2026-10-28: Task 13 closed with named gaps

One stopwatch run exists (`R3_TASK_13_REPORT.md`, update section; `reports/task13/demo_timing_20261028-0045.csv`). It does not change the verdict. G4 narrows but is not closed: no demo duration is claimed, because four of the nine steps took under 1.5 s and were most likely pressed through; the manual accessibility checks were not reported, so they stay not done and FE-19 stays NOT SIGNED. G3 (AI-D-3) is unchanged: the run did not say whether "Explain this" worked.

Addendum: G3 narrows. A screenshot taken after the stopwatch run shows the assistant answering for Alert 3 from the Live Twin page (`R3_TASK_13_REPORT.md`, addendum). The `/alerts` route, where AI-D-3 failed, was not tried, so G3 stays open for that route.

Addendum: G3 (AI-D-3) is narrowed to one open check. The owner reports that "Explain this" opens the drawer on `/alerts`, where it was dead when L7 was reported; this is a single manual observation. G3 closes when the AI-D-3 drill is re-run and passes, or when the L7 waiver is read and stands.
