# Task 22 — Reports and export

**Claim:** printable report page, shared export util, export/share buttons on alerts, telemetry history and what-if results. Runs export NOT done (see Assumptions). Not "production-ready".

## What changed
- `features/reports-export/` (new feature, route `/report`, nav "Report", viewer):
  - `exportTable.ts`: shared `csvCell` (formula-safe), `toCsv`, `toJson` (table, origin, `exported_at_utc`, notes, row count), `utcIso` (always `...Z`; zone-less text read as UTC), `exportFilename` (UTC stamp, path-safe), `downloadExport`.
  - `ExportButtons.tsx` (Export CSV / JSON, disabled + reason when empty, polite status), `ShareLinkButton.tsx` + `shareLink.ts` (copies the address with credential-like query params, user info and `#fragment` removed).
  - `reportModel.ts` + `ReportPage.tsx` + `report-print.css`: executive/ESG summary from the latest live frame, a snapshot refreshed only by "Refresh". Shows the carbon label (ASSUMPTION for the flat fallback), claim-boundary box, provenance block; stale / no-frame banner. Print CSS prints only the sheet, black on white, with a provenance line fixed at the bottom of every printed page. Report rows export as CSV/JSON.
- Buttons added (small additive edits): `AlertsPage.tsx` (export visible alerts + copy link, columns in `alerts-centre/exportColumns.ts`), `HistoryTable.tsx` (all stored samples, not only the page; columns in `reports-export/historyColumns.ts`), `LabPage.tsx` (JSON export of baseline/current/saved with the estimate and carbon-fallback notes; columns in `what-if-lab/exportColumns.ts`; existing CSV button and its test untouched).
- `what-if-lab/saved.ts`: `csvCell` now re-exported from the shared util (same behaviour, superset input type).
- `features/registry.test.ts`: list gained `reports-export` (the test asks for it).

## Assumptions
- Runs export not wired: `src/runs/` and `src/components/runs/` are absent from the zip, so the run result shape is unknown and `RunMonitor` cannot be edited. Drop `<ExportButtons>` into it once its columns are known.
- No backend `summary.csv` plugin: the report is built from the live frame the browser already holds. No new env vars.
- Zone-less timestamps are UTC (backend contract).
- Telemetry-history share link copies the page address; it carries whatever the page's query string holds.

## Test results
- `vitest`, `tsc`, `lint:ci`, `build`: NOT RUN. `npm ci` ends with `Exit handler never called!` and installs no tools (`node_modules/.bin` missing).
- Run for real: the three pure test files (`exportTable.test.ts`, `shareLink.test.ts`, `reportModel.test.ts`) executed under Node 22 with a small `expect` shim, also with `TZ=America/New_York` and `TZ=Asia/Kolkata`: `passed 11, failed 0` / `passed 3, failed 0` / `passed 8, failed 0`. Node type-strip parse of every changed `.ts` file: 0 errors.
- Written, not executed: `ReportExport.test.tsx` (buttons, print call, empty/stale states, labels).

## Not verified
- Anything involving React, `.tsx` files (no parser available), lint, build, and `bundleScan`.
- Print layout in a real browser (page breaks, the repeated footer); dark/light and 360 px by CSS reading only.
- `.gitignore` line 245 is `runs/`, which also ignores `src/runs/`: likely why those files never reach a zip or a fresh clone. Not changed here (out of scope).
