# Frontend status (FE-00 … FE-21)

Last updated 2026-10-11. **TwinGrid is simulator-only.** "Done" below means code and tests exist; it does **not** mean a scientific claim is validated.

> **Before merging this file:** it was written from the repository snapshot at FE-16 plus the FE-18, FE-19 and FE-20 deltas. FE-17's files were not in that snapshot, so FE-17 rows are marked **confirm**. Check every **confirm** against your tree and delete this note.

## Tasks

| Task | Scope | State | Evidence |
|---|---|---|---|
| FE-00 | Baseline and reconciliation | Done (historical; it recorded failures that later tasks fixed) | [BASELINE.md](baseline/BASELINE.md), [BACKEND_RECONCILIATION.md](baseline/BACKEND_RECONCILIATION.md) |
| FE-01…FE-14 | Contract layer, transport, provenance, telemetry store, stale propagation, anomaly and analytics honesty, simulation/optimisation panels, auth/config, report provenance, real-backend E2E and drift CI, alerts, facility topology | Code and tests present in the repository | tests under `src/**`, `e2e/**`; per-task sign-off records are not kept in-repo |
| FE-15 | Scenario library | Done, committed | G-SCN real-backend run: [G-SCN.real-run.md](../../../docs/frontend/contracts/G-SCN.real-run.md) |
| FE-16 | Run workflow | Done, committed; G-RUN passed on the real backend at `db92487705ba6ffe554b4c819b8006187966a446` | `G-RUN.real-run.md` (owner record) |
| FE-17 | Evaluation + E2E-2 | Built against G-EVAL with owner-approved decisions (BE-G2 as specified; definitions and metrics verbatim from `PREREGISTRATION.json`; `ci_level` 0.95; T30 runs not served; static origin `simulated`; `NOT_EVALUATED` shows "definition not provided"). **Confirm** it is applied and committed. | [G-EVAL.md](../../../docs/frontend/contracts/G-EVAL.md) |
| FE-18 | Telemetry history | Delivered as a delta that imports FE-17 files, so it needs FE-17 first. Real-stack runbook in [G-HIST.md](../../../docs/frontend/contracts/G-HIST.md) still pending; the simulator alone writes no stored telemetry (producer gap, backend BE-G1), so a simulator-only stack shows the empty state. **Confirm** applied. | tests under `src/telemetry/history/`, `src/pages/TelemetryHistory.test.tsx` |
| FE-19 | Accessibility sweep | **Not signed.** Fixes and tests written; none executed (no browser/backend where authored). Contrast, 200 % zoom/320 px reflow and screen-reader notes are pending. | [a11y/FE-19.md](a11y/FE-19.md) |
| FE-20 | Performance measurement | **Not measured.** Harness only; every budget is unmeasured, not met. No breach list, so FE-20b has not started and no optimisation is allowed. | [perf/FE-20.md](perf/FE-20.md) |
| FE-21 | Documentation closure | This change: README, RELEASE, docs set | docs diff |

## Open items

1. **FE-19 evidence run:** `npm run verify`, then `e2e/a11y.spec.ts` with a real backend; zero serious/critical axe findings; record screen-reader notes. Sweep `/evaluation` and `/telemetry` (not swept at FE-19).
2. **FE-20 numbers:** run the three commands in [perf/FE-20.md](perf/FE-20.md), fill Measured/Verdict, list or waive breaches. S4 needs ≥ 5,000 stored samples (not fabricated).
3. **`src/components/FloorHeatmap.tsx` still exists** in the snapshot and contains a `useFrame` loop; `components/analyticsGate.test.ts` ("FloorHeatmap is deleted") should therefore fail. Deleting it is a code change outside FE-21; also needs `src/three/visualizationModes.ts` checked for the reference.
4. `index.css` keyframes `.pulse-dot` / `.scan-line` have no reduced-motion guard (unused; add a guard or delete).
5. Analytics bar chart encodes cooling mode by colour; the summary and data table carry it in text. A pattern/legend is a design decision.
6. `src/contract/fixtures/` held only a README in the snapshot: commit a real capture set before making `frontend-contract` blocking.
7. CI `frontend-e2e` and `frontend-contract` are advisory until one recorded green run each.
8. Roadmap open questions still unrecorded as resolved: UQ-1 `server_utilisation` unit; UQ-2 rack `external_id` ↔ `rackId` parity; UQ-3 canonical alert-write path; UQ-4 `/api/simulate` persistence; owner decision on two-halves rack rendering in thermal mode.

## MR §25 status (paste-ready)

The MR itself is not in this repository; copy this block into §25.

| Item | Status |
|---|---|
| Truthfulness fixes D-1…D-7 (FE-01…FE-13) | Implemented in code; per-defect sign-off lives with the owner's MR |
| Real-backend E2E and drift CI (FE-11) | Present; advisory in CI until one recorded green run |
| G-SCN / FE-15 | Closed (real-backend run recorded) |
| G-RUN / FE-16 | Closed (real-backend run recorded) |
| G-EVAL / FE-17 | Built; confirm applied |
| G-HIST / FE-18 | Delivered; real-stack runbook and producer (BE-G1) pending |
| FE-19 accessibility | Written, **not signed** |
| FE-20 performance | Harness only, **not measured** |
| FE-21 docs | Done |
| Accepted risks | R-1 / D-6 and the others in [RISKS.md](RISKS.md) |
