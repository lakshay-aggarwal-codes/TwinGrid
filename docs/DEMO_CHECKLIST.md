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
the simulator; the tuned PID collapsed to the rule baseline (all gains 0), so it is not a working PID result. Carbon is a flat assumed
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
