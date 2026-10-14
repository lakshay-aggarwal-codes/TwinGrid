# Task 12 — Command palette and shortcuts

## What changed
New feature `twin-stream-insight-main/src/features/command-palette/` (auto-discovered; no router/App edits):
- **Ctrl/Cmd+K** opens a `cmdk` palette on every page (it lives in the `settings` slot, i.e. the account bar, which is mounted on every route once signed in; the bar also gets a "Commands Ctrl K" button). Capture-phase handler, so it also replaces the live twin's own Ctrl+K; that page's header "Search" button still opens its older rack/zone search.
- Fuzzy search (cmdk) over: **pages** (core + feature nav pages), **scenarios** (backend registry, loaded only while the palette is open), **racks, zones and recent alerts** (from the facility layout / alert events), plus every command features register. Groups: Recent, Navigate, Scenarios, Racks, Zones, Alerts, Actions (feature groups follow).
- Registry: rows react live to `commandRegistry` register/unregister and are role-filtered (`minRole`). The live-twin page contributes its rack/zone/alert commands through `useSceneCommands` (2 lines in `LiveTwin.tsx`).
- **`?`** opens a shortcuts dialog (built-in keys plus any `shortcut` hint a command carries); ignored inside text fields.
- Recent commands (last 5, localStorage, never throws). Keyboard operable; Escape closes; focus returns to where it was (not after running a command, which may move focus itself). Ctrl+K/`?` do nothing while another dialog is open.
- Edited existing files: `src/pages/LiveTwin.tsx` (+1 import, +5 lines), `src/features/registry.test.ts` (shipped-features list now `["command-palette", "simulated-data"]`).

## Assumptions / not done
- **No "toggle theme"**: the app has one (dark) palette and no light theme, so a toggle would do nothing. Add it when a light theme exists.
- **No "start tour"** (Task 20 absent), **no "export view"**, **no "acknowledge alert"** (no alert list is held outside the incidents panel); the palette's "Alerts" rows open the incidents panel.
- **Runs**: there is no run-list endpoint, so only "Go to New simulation run" is searchable; runs are not listed individually.
- Choosing a scenario saves it as the selected scenario and opens `/analytics`; if you are already there, it applies on the next load of that page (the library reads the selection once). Nothing is run by selecting.
- Rack/zone/alert rows exist only while the live-twin page is mounted.
- The `src/runs/*` modules referenced by `pages/Runs.tsx` are absent from this upload (as in earlier tasks); nothing here imports them.

## Verified
- Syntax check of every new/changed file with `tsc` 6.0.3 (`TS1xxx` errors: none); strict type check of `recents.ts` and `shortcuts.ts`: clean.
- Plain-node run of the pure logic (recents order/cap/broken storage, Ctrl/Cmd+K and `?` rules, page/command items, group order, recents resolution): `pure-logic checks passed`.

## Not verified
- **No vitest, full `tsc`, eslint or browser run**: `node_modules` is not in the upload and there is no network. `CommandPalette.test.tsx` (open/search/execute/close, Enter, focus return, registry commands incl. live add/remove and role gating, scenarios, `?`, no-router mount) and `logic.test.ts` were written but never executed; expect to fix small jsdom/cmdk details on the first run.
- Existing tests that render `AccountMenu` (without a router or query client) now also mount the palette button; the widget is written to work without either, but those tests were not run.
