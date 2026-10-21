# Frontend status (FE-00 … FE-21)

Last updated 2026-10-21 (playbook Task 32); older rows below are as of 2026-10-17. **TwinGrid is simulator-only.** "Done" below means code and tests exist; it does **not** mean a scientific claim is validated.

> **IG-00 note (2026-10-11):** FE-17 and FE-18 are confirmed present in the tree at commit `0c5b98a`. The rest of this file was written from an earlier snapshot and has not been re-audited except where stated.

## Tasks

| Task | Scope | State | Evidence |
|---|---|---|---|
| FE-00 | Baseline and reconciliation | Done (historical; it recorded failures that later tasks fixed) | [BASELINE.md](baseline/BASELINE.md), [BACKEND_RECONCILIATION.md](baseline/BACKEND_RECONCILIATION.md) |
| FE-01…FE-14 | Contract layer, transport, provenance, telemetry store, stale propagation, anomaly and analytics honesty, simulation/optimisation panels, auth/config, report provenance, real-backend E2E and drift CI, alerts, facility topology | Code and tests present in the repository | tests under `src/**`, `e2e/**`; per-task sign-off records are not kept in-repo |
| FE-15 | Scenario library | Done, committed | G-SCN real-backend run: [G-SCN.real-run.md](../../../docs/frontend/contracts/G-SCN.real-run.md) |
| FE-16 | Run workflow | Done, committed; G-RUN passed on the real backend at `db92487705ba6ffe554b4c819b8006187966a446` | `G-RUN.real-run.md` (owner record) |
| FE-17 | Evaluation + E2E-2 | Built against G-EVAL with owner-approved decisions (BE-G2 as specified; definitions and metrics verbatim from `PREREGISTRATION.json`; `ci_level` 0.95; T30 runs not served; static origin `simulated`; `NOT_EVALUATED` shows "definition not provided"). Applied and committed: `src/pages/Evaluation.tsx` is built into `dist/assets/Evaluation-*.js` and its tests ran in the IG-00 run; `git status --short` at `0c5b98a` lists no frontend changes. A real-backend capture of `/api/evaluations` is not recorded. | [G-EVAL.md](../../../docs/frontend/contracts/G-EVAL.md) |
| FE-18 | Telemetry history | Delivered as a delta that imports FE-17 files, so it needs FE-17 first. Real-stack runbook in [G-HIST.md](../../../docs/frontend/contracts/G-HIST.md) still pending; and the producer exists in source (`_store_live_sample` writes the five feature sensors each tick, default on), so the history page is empty only until `seed_facility.py --seed-sensors` has run; not yet run on a real stack (see [RT-001](../../../docs/roadmap/RT-001.md)). Applied: `TelemetryHistory` is built and its tests ran in the IG-00 run (commit `0c5b98a`). | tests under `src/telemetry/history/`, `src/pages/TelemetryHistory.test.tsx` |
| FE-19 | Accessibility sweep | **Not signed.** Fixes and tests written; none executed (no browser/backend where authored). Contrast, 200 % zoom/320 px reflow and screen-reader notes are pending. | [a11y/FE-19.md](a11y/FE-19.md) |
| FE-20 | Performance measurement | **Not measured.** Harness only; every budget is unmeasured, not met. No breach list, so FE-20b has not started and no optimisation is allowed. | [perf/FE-20.md](perf/FE-20.md) |
| FE-21 | Documentation closure | This change: README, RELEASE, docs set | docs diff |

## Roadmap tasks (T1 to T24, T30), as the repository stands on 2026-10-17

Each row is code and tests that exist, taken from the task's own report in [`docs/tasks/`](../../../docs/tasks/). "Done" means code
and tests exist; none of it has been run in a browser by the author, and none of it is a scientific claim.

| Task | Scope | Report |
|---|---|---|
| T1 | Extension points: backend plugins, frontend feature modules, shared command registry | [Task1](../../../docs/tasks/Task1_REPORT.md) |
| T2, T3 | Frontend green; dependency security | [Task2](../../../docs/tasks/Task2_REPORT.md), [Task3](../../../docs/tasks/Task3_REPORT.md) |
| T4, T9 | One truthful architecture; API reference generator | [Task4](../../../docs/tasks/Task4_REPORT.md), [Task9](../../../docs/tasks/Task9_REPORT.md) |
| T5 | One-command demo with seeded simulated data | [Task5](../../../docs/tasks/Task5_REPORT.md) |
| T6, T7 | Security headers, WebSocket tickets, lockout; observability | [Task6](../../../docs/tasks/Task6_REPORT.md), [Task7](../../../docs/tasks/Task7_REPORT.md) |
| T8, T10 | Release pipeline (never run on a real tag); supply-chain scanning configured | [Task8](../../../docs/tasks/Task8_REPORT.md), [Task10](../../../docs/tasks/Task10_REPORT.md) |
| T11 | Data-truth labelling | [Task11](../../../docs/tasks/Task11_REPORT.md) |
| T12 to T19 | Command palette, 3D inspector, replay, what-if lab, executive dashboard, alerts centre, Model Passport, optimizer approvals | [Task12](../../../docs/tasks/Task12_REPORT.md) to [Task19](../../../docs/tasks/Task19_REPORT.md) |
| T20 | Story Mode tour, status bar, standard empty/loading/error states | [Task20](../../../docs/tasks/Task20_REPORT.md) |
| T21 | Design polish and accessibility fixes in code (not signed off, not claimed WCAG-compliant) | [Task21](../../../docs/tasks/Task21_REPORT.md) |
| T22, T23 | Reports and export; realtime resilience | [Task22](../../../docs/tasks/Task22_REPORT.md), [Task23](../../../docs/tasks/Task23_REPORT.md) |
| T24 | Backend performance (micro-benchmarks only) | [Task24](../../../docs/tasks/Task24_REPORT.md) |
| T30 | Fleet view of five simulated sites | [Task30](../../../docs/tasks/Task30_REPORT.md) |
| T31 | ML honesty pass: model cards and limitations | [Task31](../../../docs/tasks/Task31_REPORT.md) |
| T33 | README, claims ledger, judges pack | [Task33](../../../docs/tasks/Task33_REPORT.md) |

Tasks 25 to 29 were not present in the snapshot this table was written from; add them when they are merged.

## Playbook v3.1 tasks present in this tree (2026-10-21)

From `docs/roadmap/task-reports/`; each is PARTIAL (frontend gates not run) unless stated. Not present: Tasks 11, 19, 21 to 22, 24 to 28, 30, 31.

| Task | Frontend-relevant result |
|---|---|
| 4 | What-if set-point range derived from the server's physics |
| 8, 23 | History/backfill reality check; backfilled samples merged into the history chart (11 pure tests ran under a stand-in runner) |
| 12 | Admin access-request queue (`features/admin-console`) |
| 15 | Assistant drawer and "Explain this" (`features/assistant`), gates not run |
| 16 | One signal/alert state policy |
| 29 | Performance tooling only; **still not measured** |

## Open items

1. **FE-19 evidence run:** `npm run verify`, then `e2e/a11y.spec.ts` with a real backend; zero serious/critical axe findings; record screen-reader notes. Sweep `/evaluation` and `/telemetry` (not swept at FE-19).
2. **FE-20 numbers:** run the three commands in [perf/FE-20.md](perf/FE-20.md), fill Measured/Verdict, list or waive breaches. S4 needs ≥ 5,000 stored samples (not fabricated).
3. *(Resolved in source 2026-10-20: `src/components/FloorHeatmap.tsx` is absent from the tree. `components/analyticsGate.test.ts` was not run.)*
4. `index.css` keyframes `.pulse-dot` / `.scan-line` have no reduced-motion guard (unused; add a guard or delete).
5. Analytics bar chart encodes cooling mode by colour; the summary and data table carry it in text. A pattern/legend is a design decision.
6. `src/contract/fixtures/` held only a README in the snapshot: commit a real capture set before making `frontend-contract` blocking.
7. CI `frontend-e2e` and `frontend-contract` are advisory until one recorded green run each.
8. Roadmap open questions: UQ-1 to UQ-4 are settled by [ADR 004 to 007](../../../docs/adr/); the owner decision on two-halves rack rendering in thermal mode is still not recorded (the code renders two halves, both facility-wide values; see [RT-001](../../../docs/roadmap/RT-001.md)).

## MR §25 status (paste-ready)

The MR itself is not in this repository; copy this block into §25.

| Item | Status |
|---|---|
| Truthfulness fixes D-1…D-7 (FE-01…FE-13) | Implemented in code; per-defect sign-off lives with the owner's MR |
| Real-backend E2E and drift CI (FE-11) | Present; advisory in CI until one recorded green run |
| G-SCN / FE-15 | Closed (real-backend run recorded) |
| G-RUN / FE-16 | Closed (real-backend run recorded) |
| G-EVAL / FE-17 | Built and applied at `0c5b98a` (IG-00); real-backend capture not recorded |
| G-HIST / FE-18 | Delivered; producer present in source, real-stack runbook not yet run |
| FE-19 accessibility | Written, **not signed** |
| FE-20 performance | Harness only, **not measured** |
| FE-21 docs | Done |
| Accepted risks | R-1 / D-6 and the others in [RISKS.md](RISKS.md) |
