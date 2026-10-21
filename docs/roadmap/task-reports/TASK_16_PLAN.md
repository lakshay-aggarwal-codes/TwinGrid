# Task 16 — RT-002 plan

Own files: `src/signal_state.py`, `tests/fixtures/signal_state_cases.json`, `tests/test_signal_state.py`,
`twin-stream-insight-main/src/contract/signalState.{ts,test.ts}`, new `src/components/signal/*` (badge, view model, rule facts),
small edits to `components/shell/ThermalLegend.tsx` and `components/alerts/AlertRowItem.tsx`, `docs/adr/009-alert-ack-routes.md` (D-16).
Not edited (Task 15 entry points): `features/alerts-centre/AlertDetail.tsx`, `LiveTwin.tsx`, `OperationsConsole.tsx`.
Order: inventory constants -> hand-written fixture -> Python `evaluate` + tests -> TS mirror + parity test -> badge/view model -> wiring -> ADR -> gates.
