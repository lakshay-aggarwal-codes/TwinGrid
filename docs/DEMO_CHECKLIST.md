# Pre-demo checklist

Tick each line before presenting. The demo is simulated data only. [C-26]

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
