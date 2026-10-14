# Task 13 — Interactive 3D facility inspector

## What changed
New feature `twin-stream-insight-main/src/features/facility-inspector/` (auto-discovered; four widgets in the `facility-inspector` slot of the Live Twin right rail):
- **Hover tooltip** (DOM, positioned by a ref from pointer events, no per-move React state) and **click-to-select**, both from the scene's existing rack events.
- **Readings panel** for the selected rack: temperature, IT power, utilisation, open alerts, health score and a **30-minute sparkline** (history API, same loader as the history page; loading / empty / error / stale states).
- **View controls**: camera presets (Overview, Hot aisle, Top-down) with gsap fly-to (instant under reduced motion); layer toggles Thermal / Airflow / Power / Carbon with a legend using shape glyphs and text, not colour alone.
- **Rack list**: keyboard alternative to the canvas (one tab stop, arrows/Home/End, Enter selects and flies).
- **`?rack=<id>`**: read once the topology has resolved (unknown ids dropped), kept in step via `history.replaceState`.
- Additive edits: `three/useCameraFocus.ts` (+`focusOnPreset`), `three/TwinScene.tsx` (`FocusRequest` gains a `preset` member; props unchanged), `three/Facility.tsx` (publishes hover), `pages/LiveTwin.tsx` (one hook + one handler, on top of the Task 12 version), `features/registry.test.ts` (shipped-features list). New `three/cameraPresets.ts`, `three/inspectorBridge.ts`.

## Assumptions
- **No per-rack data exists on the backend** (and alerts carry no rack). So the readings are the facility-wide live values, labelled "not specific to this rack"; **health score is NOT MEASURED**; open alerts = unacknowledged among the last 50 recorded, facility-wide; the sparkline is the facility outlet-temperature sensor.
- **Alert → rack fly-to not done**: no alert-to-rack mapping exists; selecting an alert still frames the overview (existing behaviour).
- **Not instanced**: the 36 racks stay individual meshes (changing that would change the existing mode components); picking uses the existing r3f events and there is no per-frame state.
- Layers drive the existing view modes (one at a time): Airflow = cooling mode (no airflow measurement), Carbon = WUE tint (carbon intensity only when the backend flags it real), Power = PUE tint.
- "Hot aisle" frames the aisle between the first zone's two rows; the layout does not say which aisle is hot.

## Verified
- `tsc` 6.0.3 syntax check of every new/changed file: no TS1xxx errors. Strict check of the pure modules: no errors in new files (only existing files that import absent packages).
- `logic.test.ts` executed through a minimal `vitest` shim in plain node: `19 passed, 0 failed` (presets, URL, list navigation, bridge, layers/legend incl. band edges vs `getModeColor`, readings, sparkline, tooltip position).

## Not verified
- No `npm ci`/vitest/eslint/build/browser (no `node_modules`, no network). `FacilityInspector.test.tsx` (list, controls, readings, tooltip, host/URL) was written but never executed; expect small jsdom fixes.
- Existing `SidePanel` tests now mount these widgets without providers; the slot error boundary should absorb it, not run.
