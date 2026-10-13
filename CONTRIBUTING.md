# Contributing

## Setup

See `README.md`'s Local Setup section.

## Before submitting a change

Open a pull request against `main`; the template lists the checklist. CI runs the gates in `.github/workflows/ci.yml`.
Run the relevant ones locally first:

- Backend: `ruff check .`, `ruff format --check .`, `pytest tests -m "not postgres"`.
- Frontend (in `twin-stream-insight-main`): `npm ci`, then `npm run verify` (typecheck, lint with 0 warnings, tests, build).
- Routes added or changed: `python scripts/gen_api_reference.py`, and commit `docs/api/` (a test fails when it is stale).
- Migrations: additive only (new tables or nullable columns); exactly one Alembic head (`python audit_alembic_graph.py`).
- Never weaken, skip or delete a test to get green.
- Data is simulated and must stay labelled so. Do not add "measured", "validated on real data", "calibrated" or
  "production-ready" wording without evidence in the repository.
- Never commit secrets or real credentials. A secret scan (`.github/workflows/secret-scan.yml`) is configured; the only
  allowed placeholders are listed in `.gitleaks.toml`.
- If you're touching physics (`src/digital_twin.py`, `src/optimizer.py`, `src/data_generator.py`), read the Physics section of `docs/architecture/system.md` — `DigitalTwin` is the single physics implementation, and the data generator and the RL environment (`src/rl/env.py`) both run it; a physics change moves all three.
- If you change the RL reward function or observation space shape, the existing `models/optimizer/ppo_model.zip` checkpoint becomes stale and must be retrained — note this in your PR description.

## Security issues

Do not open a public issue; follow `SECURITY.md`.

## Dependencies and workflows

Dependabot opens weekly grouped update PRs. After a Python update merges, regenerate `requirements.lock` with the
`bootstrap` job (see the header of `requirements.txt`). A new GitHub Action must be added to
`docs/governance/UNPINNED_ACTIONS.md`.

## Commit style

Conventional-commit-style prefixes (`feat:`, `fix:`, `docs:`, `test:`, `ci:`, `refactor:`) — see the git history for examples from this project's phased build-out.
