# R3 Task 13 report: L8 timing and accessibility

Status: **Open.** The automated accessibility run and the command timings are measured. The demo stopwatch runs and the manual accessibility pass are not done, and nothing below claims them.

## Measured (your machine, Windows, Chromium via Playwright, real backend from `demo.ps1`)

### Automated accessibility: `npx playwright test e2e/a11y.spec.ts`

Result: **48 passed, 0 failed, 5.0 min** (`r3_t13_a11y.txt`).

What the 48 cover, from the test names in the run:

| Area | Result |
| --- | --- |
| axe, WCAG 2.0, 2.1 and 2.2 level A and AA tags (`WCAG_TAGS` in the spec), gate = zero serious or critical | `/`, `/analytics`, `/runs`, `/evaluation`, `/telemetry`, `/runs/:id` (unknown-run state), `/alerts`, `/whatif-lab`, `/optimizer`, `/report`, `/fleet`: each in light and dark, passed |
| Admin console tabs (Users, Access requests, Audit log, Webhooks, System) | axe passed |
| Login screen (light, dark, rejected credentials), request form, activation page | axe passed |
| Keyboard and focus | Panels (Simulation Lab, Operations, Incidents): opening focuses the heading, closing returns focus to the toggle. Inspector clear, command palette (Enter and Ctrl+K), model passport drawer, assistant drawer, admin approve dialog: focus trapped or restored, Escape returns focus. Passed |
| Charts | `/analytics`: every chart has a title, a text summary and a data table. Passed |
| Reduced motion | Live Twin, Analytics, access pages: no infinite animation. Passed |
| Reflow at 320 px wide and 640 x 512 (stand-in for 200% zoom) | Sign-in, request form, activation page: no horizontal scroll. Signed-in routes: overflow at most 1 px. The signed-in tests use `expect.soft`, which still fails the test, so these are real passes |

Contrast: axe's colour-contrast rule is part of the WCAG AA tags the spec uses, and no serious or critical finding was raised. This says nothing about the 3D scene, which axe cannot measure.

### Timings (single run each, one machine)

| Item | Seconds |
| --- | --- |
| `demo.ps1` after a reset, Docker image layers mostly cached | 28.7 |
| `repro.py list` | 1.55 |
| `repro.py verify baselines-v6` | 6.44 |
| `src.run_export baselines-v6` | 1.01 |

The first-ever Docker build is not measured. The script says it "can take several minutes".

## Not done, so no claim is made

1. **Demo script timing.** The 9-step script in `docs/DEMO_CHECKLIST.md` has not been run against a stopwatch. The page still says "not yet rehearsed".
2. **Rehearsal timing.** `scripts/rehearsal.ps1` is not in the tree, so the rehearsal log the checklist describes cannot be produced.
3. **Manual pass from `twin-stream-insight-main/docs/frontend/a11y/FE-19.md`:** a screen reader, true browser 200% zoom, and a keyboard-only run of the demo path. FE-19 stays NOT SIGNED.
4. **Not covered by the automated run:** `/runs/:id` for a real run (needs `E2E_RUN_ID`), `ScenarioLibrary` (not reachable from any route), the 3D scene's contrast, and the 5 Playwright runs that failed earlier for environment reasons (see below), which are superseded by this run, not edited.

## Findings for Task 14 (doc and tooling mismatches seen while measuring)

- `DEMO_CHECKLIST.md` says `.\scripts\demo.ps1 -Fresh`, but `demo.ps1` only has `-WithFrontend`. A fresh start needs the `docker compose ... down -v` command from the script header.
- `DEMO_CHECKLIST.md` line 11 names `scripts\rehearsal.ps1`, which does not exist.
- Two Compose stacks were present at once (`twingrid-demo-*` and `digitaltwin-main-*`). The first held port 8000 and the second's backend stayed in `Created`. Earlier Playwright runs failed to sign in during that state. The checklist should say to run `docker ps` before the demo and to stop any other stack.
- Four tests took 42 to 45 s each (`/runs` dark, command palette, `/optimizer` dark, admin approve dialog) while the rest took 1 to 5 s. The cause is not measured. The helper waits out sign-in rate limiting (10 per minute), which may be the reason.

## To close Task 13

1. Run the 9-step demo script twice with a stopwatch. Record the elapsed time at the end of each step and what broke.
2. Do the four manual checks in Chrome (320 px, 200% zoom, keyboard only, screen reader) and write one line for each.
3. Decide whether to write `rehearsal.ps1` (a separate task) or drop the claim from the checklist.
