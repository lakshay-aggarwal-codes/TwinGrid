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

1. **Demo script timing.** A stopwatch run exists (`reports/task13/demo_timing_20261027-1337.csv`, two runs of the nine steps, made with `scripts/time_demo.ps1`), but it is **not a valid timing of the demo** (see "Recorded but not usable" below). The checklist's "4 to 6 minutes" is still unmeasured.
2. **Rehearsal timing.** `scripts/rehearsal.ps1` is not in the tree, so the rehearsal log the checklist describes cannot be produced.
3. **Manual pass from `twin-stream-insight-main/docs/frontend/a11y/FE-19.md`:** a screen reader, true browser 200% zoom, and a keyboard-only run of the demo path. FE-19 stays NOT SIGNED.
4. **Not covered by the automated run:** `/runs/:id` for a real run (needs `E2E_RUN_ID`), `ScenarioLibrary` (not reachable from any route), the 3D scene's contrast, and the 5 Playwright runs that failed earlier for environment reasons (see below), which are superseded by this run, not edited.

## Recorded but not usable: `demo_timing_20261027-1337.csv`

| Run | Total | Longest step | Shortest step |
| --- | --- | --- | --- |
| 1 | 12.0 s | Start, 5.0 s | What-if, Evidence, Boundaries, 0.4 s each |
| 2 | 8.1 s | Start, 1.4 s | Boundaries, 0.5 s |

The script times your Enter presses, not the demo. These values cannot be demo durations: step 4 is "open a seeded alert, click Explain this, click a citation chip and show its row" (1.6 s in run 1, 0.8 s in run 2) and step 6 is "run one what-if comparison" (0.4 s and 0.9 s), and the "Say" column alone is longer than that. The notes column is empty, so nothing is recorded as skipped or broken. The most likely reading is that the Enter key was pressed through the steps without performing them (for example, to test the script), but I have no evidence of what was done. The file is kept unedited; a valid run supersedes it, it does not replace it.

## Findings for Task 14 (doc and tooling mismatches seen while measuring)

- `DEMO_CHECKLIST.md` says `.\scripts\demo.ps1 -Fresh`, but `demo.ps1` only has `-WithFrontend`. A fresh start needs the `docker compose ... down -v` command from the script header.
- `DEMO_CHECKLIST.md` line 11 names `scripts\rehearsal.ps1`, which does not exist.
- Two Compose stacks were present at once (`twingrid-demo-*` and `digitaltwin-main-*`). The first held port 8000 and the second's backend stayed in `Created`. Earlier Playwright runs failed to sign in during that state. The checklist should say to run `docker ps` before the demo and to stop any other stack.
- Four tests took 42 to 45 s each (`/runs` dark, command palette, `/optimizer` dark, admin approve dialog) while the rest took 1 to 5 s. The cause is not measured. The helper waits out sign-in rate limiting (10 per minute), which may be the reason.

## To close Task 13

1. Run `.\scripts\time_demo.ps1 -Runs 2` and, at each step, actually do it and say the "Say" line before pressing Enter. Note anything that broke or was skipped.
2. Do the four manual checks in Chrome (320 px, 200% zoom, keyboard only, screen reader) and write one line for each.
3. Decide whether to write `rehearsal.ps1` (a separate task) or drop the claim from the checklist.

## Update 2026-10-28: demo stopwatch run (owner's choice B)

Status: **Done, with the gaps named below.** One run, one machine, timed by the owner's Enter presses (good to about a second), nine steps of the "Demo script" in `docs/DEMO_CHECKLIST.md`. Data: `reports/task13/demo_timing_20261028-0045.csv`.

| Step | Name | Seconds | Cumulative |
| --- | --- | --- | --- |
| 1 | Start | 1.1 | 1.1 |
| 2 | Data origin | 5.7 | 6.8 |
| 3 | Facility | 20.3 | 27.1 |
| 4 | Alert | 49.0 | 76.1 |
| 5 | Model limits | 2.6 | 78.7 |
| 6 | What-if | 27.8 | 106.5 |
| 7 | Access | 1.3 | 107.8 |
| 8 | Evidence | 0.5 | 108.3 |
| 9 | Boundaries | 0.5 | 108.8 |

Notes were left blank for every step, which the script reads as "nothing broke or was skipped".

**What this does and does not show**

- Steps 2 to 6 took 2.6 to 49 s each. Step 4 (alert and "Explain this") was the longest at 49 s. Whether "Explain this" worked was not stated separately, so the open AI-D-3 question in `R_L9_REPORT.md` (G3) is not closed by this run.
- Steps 1, 7, 8 and 9 took 0.5 to 1.3 s, which is shorter than doing the action (sign-in, opening the admin queue, showing a CI result, opening `docs/CLAIMS.md`). They are most likely pressed through, not performed. **The 108.8 s total is therefore not a demo duration, and no demo length is claimed.** `DEMO_CHECKLIST.md` keeps "not yet rehearsed; step lengths are targets".
- A real run would perform steps 1, 7, 8 and 9 and include the narration ("Say" column); this run timed neither.

**Manual accessibility checks (320 px, 200% zoom, keyboard only, screen reader):** none were reported, so they are **not done**. FE-19 stays NOT SIGNED. Waived by the owner under option B until results are supplied.

**Not changed:** the 48-test automated run and the command timings above stay as measured. `scripts/rehearsal.ps1` is still absent.

### Addendum: screenshot of the assistant (2026-10-28, 00:46 on the owner's clock, one minute after the run)

On the Live Twin page (`localhost:8080`) the assistant drawer for Alert 3 opened and answered. It showed "Why is this alert red?", the badge "Rule-based explanation, no language model is configured", five evidence rows (E1 score 0.91, E2 threshold 0.0122, E3 over_threshold true, E4 severity CRITICAL, E5 message "Demo: IT power spike far outside its recent range (simulated)"), a warning that the threshold is the currently configured detector's, and a "Not known from the available evidence" list that includes "Root cause is not determined by available evidence". The header showed the "Fallback carbon (flat constant)" and "Simulated" badges.

So "Explain this" works from the Live Twin page. This is **not** the `/alerts` route where AI-D-3 failed, so AI-D-3 is not closed. The screenshot is not tied to the step 4 timing above, and the question of whether steps 1, 7, 8 and 9 were performed was not answered.

### Addendum: "Explain this" on /alerts (2026-10-28, owner's observation)

The owner opened `/alerts`, opened an alert and clicked "Explain this": the assistant drawer opens. This is a manual check by the owner, once, with no screenshot or log. The automated drill AI-D-3 (`e2e`, assistant spec) was **not** re-run, so its pass is not claimed.
