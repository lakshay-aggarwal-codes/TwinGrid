# Task 16 — RT-002 One signal/alert state policy          Status: PARTIAL
Base: TwinGrid-main.zip (no git history; local baseline tag; owner's working copy not seen)   Date: 2026-10-20
Environment: Python 3.12.3, pytest 9.1.1, ruff 0.6.9; Node 22.22.2, npm 10.9.7, vitest 5.0.4 (`npm ci` from the lockfile).

## Summary
§8.5 is implemented in Python (`src/signal_state.py`) and TypeScript (`src/contract/signalState.ts`); both pass the same 32 hand-written
cases in `tests/fixtures/signal_state_cases.json` (95 Python tests, 42 TS tests). A new `SignalStateBadge` (icon + text + border style) is wired
into the thermal legend, where stale, offline and unknown are now distinct states and a last-known number can never come out normal. The
rule facts (rule id, value, threshold, observed_at, origin, evidence) are in a new `AlertRuleFacts` and mounted in the older alert row.
PARTIAL: the facts are NOT yet mounted in the alerts-centre `AlertDetail.tsx`, because that file is Task 15's entry-point file.

## Acceptance checklist
- Fixture parity (Python = TS) on all cases -> MET (both suites read the one file; expected values were written by hand, not generated).
- UI shows distinct stale / offline / unknown states -> MET for the thermal legend (tests: stale, disconnected, reconnecting -> `stale`; connecting -> `unknown`; unavailable -> `offline`).
- Stale is never green; offline/unknown never show a number; colour is never the only signal -> MET in `SignalStateBadge` (tests assert no `success` class, no digits, distinct icon + text + border style).
- Alert detail shows rule id, threshold, value, observed_at, origin, link to evidence -> PARTIAL: component done and mounted in `AlertRowItem`; the alerts-centre `AlertDetail` mount is for Task 15 (below). The alert record carries no threshold, so it reads "not reported" there.
- D-16 decision recorded -> MET: `docs/adr/009-alert-ack-routes.md` (keep both; alerts centre uses PATCH, the older list uses POST).

## Inventory (step 1) and what was derived
- Critical bounds = `SAFETY_ENVELOPE` in `src/digital_twin.py`: inlet 18-27 °C, outlet <= 45 °C, PUE <= 2.0 (a Python test compares the rules with the envelope and sweeps 100-400 tenths of a degree against `SafetyEnvelope.violations`).
- Stale window = the browser's rule in `hooks/liveness.ts` (3 intervals, min 5 s, default 3 s interval -> 9 s), mirrored in `stale_after_s()`; a test reads the constants out of that file.
- No warning band exists anywhere in the repo, so the default rules have none. `INLET_SCALE.warnAt = 24` and `OUTLET_SCALE.warnAt = 38` (`three/thermalMapping.ts`) are colour-ramp midpoints (the outlet one is described there as "chosen"), so they were NOT adopted as warning thresholds. OWNER CONFIRM if a warning band is wanted.

## Changed files
CREATE `src/signal_state.py`, `tests/test_signal_state.py`, `tests/fixtures/signal_state_cases.json`, `twin-stream-insight-main/src/contract/signalState.ts`,
`.../contract/signalState.test.ts`, `.../components/signal/{signalView.ts,SignalStateBadge.tsx,AlertRuleFacts.tsx,signalState.ui.test.tsx}`, `docs/adr/009-alert-ack-routes.md`, plan + report.
MODIFY `.../components/shell/ThermalLegend.tsx` (badge per reading; a no-data block with the two badges), `.../components/alerts/AlertRowItem.tsx` (one `AlertRuleFacts` in the evidence panel).

## Commands run
- `pytest tests/test_signal_state.py`: 95 passed. `ruff check .` pass; `ruff format --check .` 390 files.
- `npm run typecheck`: 16 errors before and after, none in files touched here (pre-existing: admin-console, capacity).
- `npm run lint:ci`: 3 warnings before and after (optimizer-approvals, pre-existing), 0 in the new files (`eslint --max-warnings 0` on them passes).
- `npx vitest run`: baseline 163 files / 1991 passed / 10 skipped; after 165 files / 2063 passed / 10 skipped, 0 failures.
- `npm run build`: fails on baseline AND after without `VITE_API_BASE_URL` (environment guard); with `VITE_API_BASE_URL=https://api.example.test` it builds.
- Not run: Playwright e2e, the whole Python suite (no Python file other than the new ones changed).

## Decisions and defaults used
- A value without an observation time -> `unknown` / `no_value` with no number (freshness cannot be judged). A non-finite value (NaN, inf) -> treated as no value. A timestamp ahead of `now` -> age 0, not stale. Naive datetimes raise in Python.
- Bounds are crossed only by strict `>` / `<` (same as `SafetyEnvelope`). `threshold` is the crossed bound for warning/critical, else null. `stale` keeps its value and age but has no threshold.
- Ages are whole milliseconds in both languages; `observed_at` is output as canonical UTC text (`...SSZ`, `.fff` only if non-zero).
- Rule ids: `inlet_temp_c`, `outlet_temp_c`, `pue` (`default_rules()` / `DEFAULT_SIGNAL_RULES`).
- The thermal legend holds "value + age", not a timestamp, so `stateFromAgedReading` evaluates on a relative timeline; when the feed machine says "not live" the window is forced to -1 so any age is `stale`.
- Rule facts take their threshold and evidence link as props so the component needs no router or network.

## Requested cross-task changes
- Task 15 (owner of `features/alerts-centre/AlertDetail.tsx`): mount `<AlertRuleFacts ruleId={alert.type} value={alert.score} valueLabel="Value (detector score)" threshold={explanation?.score_vs_threshold?.threshold ?? null} observedAt={formatUtc(alert.created_at)} origin={alert.origin} evidence={<Link to={replay}>Open this moment in Replay</Link>} />`.
- Task 14: `from src.signal_state import evaluate, default_rules, unavailable` now resolves; `SignalState.to_dict()` is the §8.5 shape; remove the `rule_unavailable` fallback at integration (Task 33 item).
- Frontend integrator: the `PUE` reading in `TwinHeader` and the KPI cards still show their own stale handling and do not use the badge yet.

## New limitations or risks
- Only the thermal legend and the older alert row use the new badge/facts; other readouts keep their existing last-known styling (they agree with the policy but do not call it).
- No warning band, so `warning` cannot occur with the default rules; it is covered by the fixture rules only.
- The Python and TS rule numbers are kept equal by tests (fixture <-> envelope), not by a single source file.

## Next tasks unblocked
- 14 (signal adapter), 15 (AlertDetail mount), 23 (history/backfill), 28 (accessibility sweep).
