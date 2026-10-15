# Task 19 report: optimizer UI, baseline recommendation, approvals

## What changed
- **Backend.** Plugin `api/plugins/optimizer_proposals.py` (recommendation, sandbox, proposals, admin decision). Pure rules in
  `src/optimizer_proposals.py`; baseline selection in `src/baseline_recommendation.py` (reads `configs/baselines/{pid,rule}.json`,
  refuses infeasible/stale ones via `check_lineage`, ranks by the stored validation reward, asks the winner's own policy for the
  set-point). Table `optimizer_proposals` (migration `20261006000000`), repository `api/repositories/proposal_repository.py`.
- **Frontend.** `src/features/optimizer-approvals/` at `/optimizer`: PPO panel (status from the Model Passport; "Request a PPO run" reuses
  the existing optimize client and reducer; a 503 shows the reason and that nothing ran), baseline recommendation card with predicted
  effect and an editable sandbox, proposals list with admin approve/reject, shadow-mode agreement chart.

## Rules enforced
- PPO is never described as better than the baselines unless the stored decision is outcome `A`; then only the stored `claim_allowed` text, verbatim.
- Operator or admin proposes; only an admin decides, never on their own proposal, once. Every step writes an audit row.
- Predictions are labelled "model estimate on simulated data". Approval is a recorded decision only.

## Assumptions
- The recommendation always comes from the best usable **baseline**; a PPO run is shown as simulator output and cannot be proposed (it is a summary, not a set-point).
- "Best" means the highest validation reward stored in each baseline's config, on simulated scenarios; the page says so and says it is not a comparison with PPO.
- The shadow chart shows cooling-mode agreement only (all the summary endpoint reports).
- `admin` accounts are not created by the app; they come from the seed or the database.
- Also edited: `models/db_models.py`, `tests/test_alembic_chain.py` (head moves to `20261006000000`).

## Test results
Nothing could be executed here (no network, so no Python or npm dependencies). Only `py_compile` on all new/changed Python, a TypeScript
syntax parse of every new `.ts/.tsx`, and earlier a direct run of the Task 17 pure module passed.
Written, not run: `tests/test_task19_optimizer_rules.py`, `tests/api/test_task19_optimizer_proposals.py`, and in the feature folder
`logic.test.ts`, `api.test.ts`, `OptimizerPage.test.tsx` (503 handling, role flow, audit entries, claim gating).

## Not verified
- `pytest`, `ruff check`, `ruff format --check`, `npm ci`, `typecheck`, `lint:ci`, `vitest`, `build` were not run; new tests may need small fixes.
- The Alembic round trip and `alembic check` were not run (Task 17 and 19 migrations).
