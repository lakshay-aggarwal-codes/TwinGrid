# Pre-demo checklist

Tick each line before presenting. The demo is simulated data only. [C-26]

## Once, on a clean machine (the rehearsal)

Do this on a fresh clone, at least a day before. Its purpose is to find what breaks, not to pass. Nothing here has been run on
a clean machine by the maintainers yet; the first log decides what gets fixed. [C-34]

- [ ] `git clone <your repository URL> TwinGrid-clean`, then `cd TwinGrid-clean`.
- [ ] `.\scripts\rehearsal.ps1 -FreshVenv -TryLock` (Python 3.12, no Docker needed). It writes `rehearsal_logs\rehearsal_<time>.txt`.
- [ ] Open the SUMMARY at the end of that log. Every FAIL line is a defect to report, with the log attached.
- [ ] Docker path: `.\scripts\demo.ps1 -Fresh`, then run `.\scripts\demo.ps1` a second time with no switch. The second run must reuse
      the database without an error and print "no new accounts" (migrations on an existing database).
- [ ] `python scripts\check_lock_drift.py` prints "no drift". It checks the files only; it does not prove the lock installs on Windows
      (`-TryLock` does that, and may fail because the lock was generated for Linux).
- [ ] Record the wall-clock times the script prints. No time on this page is a measurement until you have these.

## The three-minute path (no Docker, no browser needed)

All of it reads one stored simulator run, so it works offline. Say "simulated" first. [C-01]

| Step | Command (PowerShell, repository root, venv active) | Say |
|---|---|---|
| 1. Simulate | `python scripts\repro.py list` | "These are stored simulator runs. Each has a manifest recording the code, configs, seeds and physics version." |
| 2. Compare the safe controllers | `python scripts\repro.py verify baselines-v4` | "Four fixed controllers, tuned on validation scenarios and scored on 60 held-out scenarios, with hard limits on temperature and PUE. It re-checks every recorded hash." |
| 3. Open the report | `python -m src.run_export baselines-v4 --out baselines-v4.md` then `notepad baselines-v4.md` | "The report is rebuilt from the stored result, not retyped. It names the seeds, the physics version, the assumed carbon signal and the violation counts." |

What step 2 should print: WARN lines for platform (the run was recorded on one machine) and for the dirty tree are expected and are
not failures; say so if asked. Any FAIL line is a defect to send with the rehearsal log. Before Task 21 every stored run printed
`FAIL REPORT.md: differs from the version regenerated` because the pre-commit trailing-whitespace hook had stripped two spaces the
generator emitted; the generator no longer emits them (regression test in `tests/test_repro_framework.py`). Not yet confirmed on a
clean Windows machine: whether the schema-hash lines pass there (they need gymnasium installed).

To simulate afresh instead of reading the stored run: `python -m src.baselines.cli run --run-id demo-1` (how long it takes has not been
measured; the rehearsal's `-Simulate` switch measures it). A fresh run from an edited tree is marked DIRTY and cannot be promoted.

What the stored run shows, and does not show: a fixed 22.75 C setpoint and a lookup table scored better than the rule baseline inside
the simulator; in this stored run (`baselines-v4`) the tuned PID collapsed to the rule baseline (all gains 0), so it is not a working PID result.
The shipped `configs/baselines/*.json` were re-tuned afterwards (`baselines-tuner/3`, PUE counted) and `baselines-v5` is meant to be produced on your machine
(`docs/roadmap/task-reports/TASK_17_REPORT.md`); it is not in this tree, so do not describe `baselines-v4` as the current configuration. Carbon is a flat assumed
figure. This is a comparison of simple controllers in a simulator, not evidence for any real facility. [C-04] [C-08]

## If asked (simulated, checked, assumed)

| Question | Say | Do not say | Claim |
|---|---|---|---|
| What is simulated? | "All of it: temperatures, power, water and carbon come from our own simulator." | "Real data", "a model of a real facility". | [C-01] |
| What has been checked against a real facility? | "Nothing. There is no real measurement in the repository." | "It matches real data." | [C-01] [C-03] |
| What has been tested? | "The code has automated tests and CI is configured. A green run of the whole suite on this exact tree has not been recorded." | "All tests pass." | [C-32] [C-34] |
| What is assumed? | "Engineering values for the physics, a flat carbon figure of 475 gCO2/kWh, and scenarios we generated." | "Fitted", "measured". | [C-03] [C-04] |
| Do the AI policies beat the baselines? | "No claim. The one scored policy was worse than the rule baseline; newer candidates are not evaluated." | "The AI saves energy." | [C-08] |
| Why is the stored run marked DIRTY? | "It was made from a working tree with uncommitted changes, so it is reproducible by hash but not promotable." | "Fully reproducible." | [C-34] |
| Why do the PID and rule rows match? | "The tuner chose zero gains, so the PID reduced to the rule. It is a tuning outcome, not a result about PID control." | "PID performs the same as rule in general." | [C-08] |
| Is it ready to run a facility? | "No. It controls no equipment and targets are untested hypotheses." | Any readiness claim. | [C-02] [C-25] |
| What would real use need? | "Real data to calibrate the physics, a shadow period, integration, and security and operations review. None is built." | "It only needs deployment." | [C-33] |
| Can I see it live? | "Yes, the Docker demo uses seeded simulated data and says so in the status bar." | "Live facility data." | [C-26] [C-16] |

## An hour before
- [ ] Docker Desktop is running.
- [ ] From the repository root: `.\scripts\demo.ps1 -WithFrontend` (macOS or Linux: `scripts/demo.sh`). First run builds an image; leave time for it.
- [ ] Copy the three demo passwords the script prints. They are shown once.
- [ ] `http://localhost:8000/healthz` answers, and `http://localhost:8080` loads the sign-in page.

## Fifteen minutes before
- [ ] Sign in as `demo_operator`. The status bar shows **Live** and data origin **Simulated**.
- [ ] In a second window sign in as `demo_admin` (needed to approve a proposal).
- [ ] Open each demo page once: `/`, `/whatif-lab`, `/alerts`, `/optimizer`, `/fleet`. Each loads without an error panel.
- [ ] Press Ctrl or Cmd + K and open the Model Passport.
- [ ] Clear the saved tour state if you want the welcome dialog: browser storage key `twingrid.tour.v1`.
- [ ] Full screen, zoom 100%, notifications off, charger plugged in.

## Fallbacks
- [ ] Screenshots of each page saved locally.
- [ ] If the API is down: `docker compose --env-file .env.demo -f docker-compose.yml -f docker-compose.demo.yml up -d`, then `docs/runbooks/api-down.md`.
- [ ] If the feed looks stale: `docs/runbooks/stale-feed.md`.
- [ ] To start fresh: `docker compose --env-file .env.demo -f docker-compose.yml -f docker-compose.demo.yml down -v`, then run the demo script again.

## Do not say
See the list in [`CLAIMS.md`](CLAIMS.md). Say "simulated", "uncalibrated", "not evaluated".


## Demo script, 4 to 6 minutes (not yet rehearsed; step lengths are targets)

Open a fresh private window. Say "simulated" in the first sentence. Steps marked **(not in this tree)** need a feature that is missing
or has not been run; skip them and say so rather than improvising.

| Step | Do | Say |
|---|---|---|
| 1. Start | Open the dashboard, sign in (`demo_viewer`). A one-click read-only demo button is **(not in this tree)**. | "Everything you will see is simulated." |
| 2. Data origin | Point at the status bar and an origin badge. | "Each figure says where it comes from. Carbon is a flat assumed figure." |
| 3. Facility | Hover and click a rack in the 3D facility. | "A simulated layout; per-rack values are not measurements." |
| 4. Alert | Open a seeded alert, then **Explain this**; click a citation chip and show its row in the evidence table. | "The answer is a template filled from evidence the server fetched; it lists what it does not know." |
| 5. Model limits | Open the Model Passport. | "Each model shows its status and its limits, including the weak ones." |
| 6. What-if | Run one what-if comparison. | "Two simulated runs; no claim about a real site." |
| 7. Access | Admin window: open the access-request queue and the audit trail for a separate test request. The public request form is **(not in this tree)**. | "Access is a recorded owner decision." |
| 8. Evidence | Show the latest recorded test or CI result, and one measured performance number **only if** `reports/perf/2026-10/` has one. Today it has none. | "Nothing is quoted that we did not measure." |
| 9. Boundaries | Show `docs/CLAIMS.md`. | "What is and is not checked, and why." |

## Five-minute script for a viewer (Playbook v3.1, Task 32 draft)

Status: **drafted from the code, not rehearsed.** Run it twice before presenting (Task 31 asks for this) and write down what broke. Say
"simulated" in the first sentence. Steps that depend on parts not in this tree are marked.

| Min | Do | Say |
|---|---|---|
| 0:00 | Open a private window; start `.\scripts\demo.ps1`; sign in as `demo_viewer`. (A public read-only demo button does not exist yet; the API route does.) | "Everything is simulated; the bar says so." |
| 0:30 | Status bar and data-origin badges. | "Each number says where it came from." |
| 1:00 | 3D facility: click a rack. | "A simulated layout; no per-rack physics behind it." |
| 1:40 | Alerts: open a seeded alert, press "Explain this", open the evidence table. (Needs the assistant UI applied and a stack run; not checked.) | "The answer is a template over these rows; unknowns are listed." |
| 2:30 | Model Passport. | "Limits first, including the model that did badly." |
| 3:00 | What-if lab: one comparison. Carbon is an assumption. | "Two simulated runs; carbon is a flat assumed 475." |
| 3:50 | Admin queue: show a separate test access request and its audit trail. (A public request form is not in this tree; create the test request with the API.) | "Access is decided by the owner, and recorded." |
| 4:20 | Show the last CI result and one measured number **only if** it exists in `reports/perf/2026-10/` (none yet). | "This is what was measured, and this is what was not." |
| 4:40 | `docs/CLAIMS.md`: what is and is not validated. | "Every claim has evidence and a boundary." |

Caution: the stored run used in the three-minute path above is `baselines-v4`, recorded before the baselines were re-tuned
(`baselines-tuner/3`); its PID row (all gains 0) does not match the shipped `configs/baselines/pid.json`. The re-tuned run is created on your machine
(`docs/roadmap/task-reports/TASK_17_REPORT.md`); until then say the stored run is older than the shipped configs.
