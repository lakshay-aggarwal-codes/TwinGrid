# TwinGrid release-candidate report (Task 31, REL-002)

**Verdict: BLOCKED.** The gate could not be run and the prerequisite tasks are not all delivered. No readiness claim is made.
Base: `TwinGrid-main.zip` + `TASK_11.zip` overlay (no git history; owner's working copy not seen). Date: 2026-10-21.
Environment: Node 22.22, Bun, Python 3.13 without the project's packages. No Docker, PostgreSQL, Redis, browser, PyPI or npm access.
Everything marked NOT RUN below was not run. Expected behaviour comes from the playbook and from reading the code; no observed result exists.

## 1. Prerequisites (card: "needs all P0/P1")
Status read from `docs/roadmap/task-reports/` plus the files the owner supplied. "Report: PARTIAL" means the author could not run its gates either.

| Task | Pri | Evidence found | State |
|---|---|---|---|
| 1, 3, 4, 5, 6, 7, 9, 10, 12, 13, 14, 15, 16, 17, 18 | P0/P1/P2 | report present | PARTIAL / DONE-with-gaps (see each report); none has a full-suite run on this tree |
| 11 | P0 | `TASK_11.zip`, report PARTIAL | not in the base zip; overlaid |
| 22 | P0 | `TASK_22_REPORT.md`, PARTIAL | delivered, but does not follow the playbook's AUTH-F card (different owned files, missing cases: mail-capture SMTP, 375 px approval, outage-then-resend, rate-limit, demo write controls) |
| 28 | P2 | `TASK_28_REPORT.md`, PARTIAL | table rows exist, every result NOT RUN |
| 21 (CI hardening, first green run) | P1 | no report; `.github/workflows` exist from older work, no green run on record | **absent** |
| 25 (grounding / adversarial suite) | P1 | no report, `src/copilot/llm.py` absent | **absent** |
| 26 (Evidence page) | P1 | no report, `src/features/evidence` absent | **absent** |
| 27 (final security review) | P0 | no report | **absent** |
| 30 (integrator) | P0 | no `INTEGRATION_LOG.md` | **absent**: the tasks have not been integrated and gated together |

Conclusion: the card's precondition ("all P0/P1") is not met, so a release-candidate verdict above BLOCKED would not be evidence-based.

## 2. Steps from the card
| # | Step | Result | Command / how |
|---|---|---|---|
| 1a | Clean unzip, lockfile install | NOT RUN | `pip install --require-hashes --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.lock; pip install -r requirements-dev.txt; cd twin-stream-insight-main; npm ci` |
| 1b | Migrations: empty DB, upgrade, check, downgrade base | NOT RUN | `sh scripts/drill_clean_install.sh` (new; also runs `scripts/demo.sh` twice) |
| 2a | Backend gate incl. PG | NOT RUN | `pytest tests -m "not postgres" -rs`, then with `TWINGRID_TEST_PG_URL` set `pytest tests -m postgres -rs`; `ruff check .; ruff format --check .` |
| 2b | Frontend gate | NOT RUN | `cd twin-stream-insight-main; npm run verify` |
| 2c | Playwright on the real stack | NOT RUN | `npx playwright test` (viewer-workflow, a11y, drills, stale-surfaces, real-backend) |
| 2d | Audits | NOT RUN | `pip-audit --requirement requirements.lock --require-hashes --disable-pip --strict`; `npm audit --audit-level=high` |
| 3 | Drills | NOT RUN | section 3 |
| 4 | Demo script twice (4-6 min) | NOT RUN | Task 32 has not drafted it; use playbook section 0 pillars; needs a human |
| 5 | Verdict | BLOCKED | this document |

Known red items inherited from Task 1 (not re-run): 13 failures in the latest recorded run, plus 29 + 6 failures noted by Task 9 on its baseline (`test_error_contract`, `test_provenance_writers`, ...). See `docs/roadmap/failure-ledger.csv`. "No skipped tests" and "required CI jobs green" (programme definition of done) are unverified.

## 3. Drill matrix (card step 3)
Harness written in this task: `scripts/drill_*.sh` and `e2e/drills.spec.ts`. Every row below is **NOT RUN**: Observed is empty by design.

| Drill | Harness | Expected truthful behaviour | Observed | Result |
|---|---|---|---|---|
| Database down | `scripts/drill_db_down.sh` | `/livez` 200; `/readyz` 503 naming the database, no connection text; data routes answer an error, not an empty success; `/readyz` recovers by itself | - | NOT RUN |
| Redis down | `scripts/drill_redis_down.sh` | `/readyz` stays 200 and lists redis under degraded; API answers within 10 s; recovers | - | NOT RUN |
| Mail failure | `scripts/drill_mail_failure.sh` (needs admin creds) | approve still 200; request shows email `failed`, never `sent`; admin can resend | - | NOT RUN |
| LLM timeout / 429 | none | assistant falls back to the rule-based evidence answer, says the phrasing step failed, no invented numbers | - | **not drillable: Task 24 (LLM adapter) and Task 25 are not delivered; `src/copilot/llm.py` absent** |
| WebSocket drop / reconnect | existing `e2e/stale-surfaces.spec.ts` | no current-looking value while dropped; live again only after a fresh valid frame | - | NOT RUN |
| Stale telemetry | same spec (liveness chip, `last-known` readout) | not "live" / "normal"; last-known labelled | - | NOT RUN |
| Sequence restart | none | feed consumer detects `seq` going backwards and resets, no duplicate or lost-looking points | - | **no drill written**: needs a backend restart under a live socket; `RT-001.md` says the consumer uses `seq`/`ts_ingest` but this was never exercised end to end |
| History gap | none | gap markers only above 450 s (RT-001 item 5); UI states the 7.5 min limit | - | **not drillable yet**: RT-001 says Task 23 (backfill consumer) is needed and it is absent |
| Token expiry | `e2e/drills.spec.ts` (demo, `DEMO_SESSION_MINUTES=1`, `E2E_DRILL_DEMO_SHORT=1`) | auto sign-out, notice "Demo session ended", no data left on screen | - | NOT RUN |
| Refresh mid-approval | `e2e/drills.spec.ts` | pending page survives reload, status follows the real decision | - | NOT RUN |
| Dead / replayed activation links | `e2e/drills.spec.ts` (+ backend tests in Tasks 9 and 22) | one generic dead-link page, no half-working form | - | NOT RUN |
| Empty / unknown data | `e2e/drills.spec.ts` (unknown run id) | explicit not-found, no "completed" | - | NOT RUN |
| Large data (>= 5,000 samples) | none | history pages with the cursor, bounded response | - | **no drill written**: belongs with Task 29's measured run |

Rules to check on every run: nothing shows "healthy/normal" on missing data; no unbounded retries or queues; no unrecoverable blocking page.

## 4. Defects and risks found by reading (not by running)
1. `docs/roadmap/INTEGRATION_LOG.md` is missing: the delivered task zips have never been merged and gated as one tree, so file-ownership conflicts (playbook section 6) are unchecked.
2. Task 22 as delivered diverges from the AUTH-F card (see section 1); the J1-J4 proof the verdict needs is therefore incomplete.
3. The existing `e2e/real-backend.spec.ts` and the Task 22 / 28 specs share one 10/minute sign-in limiter and a 5/hour request limiter per IP; a full Playwright run from one IP can fail on limits rather than on defects. Space the runs or raise the limits for the test stack only.
4. `scripts/drill_*.sh` assume the compose demo stack and `.env.demo`; on Windows run them in WSL or Git Bash (the owner's environment is PowerShell).

## 5. Env-blocked items (listed separately, as the card asks)
- Live mailbox delivery: needs real SMTP credentials (Task 10 report: not verified).
- Live LLM: adapter not delivered.
- TensorFlow / PPO compute: not available here; Tasks 17-19 results are whatever their own reports state.
- A real browser, Docker, PostgreSQL and Redis: not available in this run.

## 6. What it takes to move the verdict
1. Deliver or conclude Tasks 21, 25, 26, 27 and realign 22; run Task 30 to integrate; fix the Task 1 red tests.
2. Run section 2 and 3 commands on a machine with Docker and fill the Observed / Result columns.
3. Then the verdict is one of `PORTFOLIO-READY - SIMULATOR-ONLY` (all P0/P1 rows pass, drills pass, demo run twice), `PARTIALLY READY - blockers named`, or stays `BLOCKED`.
