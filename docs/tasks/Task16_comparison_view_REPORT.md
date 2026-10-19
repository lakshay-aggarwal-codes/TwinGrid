# Task 16 (TwinGrid roadmap) — Experiment comparison view

> Named `Task16_comparison_view_REPORT.md` to avoid the numbering collision with the older task list.

## Scope decision (and why)
The roadmap asks for "baseline vs candidate under identical scenarios ... hard constraints first, which constraint decided the outcome, validation status, decision rule text; open a run's config/seeds/physics; read-only, existing endpoints". Most of the single-report surface already exists (outcome banner, identity strip, constraint panel from Task 14). The missing piece was a **head-to-head** view. Built as a panel inside the evaluation screen comparing two policies of ONE report: both were scored on the same scenario set by construction, so "identical scenarios" holds without any cross-report guessing.
Not built, on purpose: comparing two different reports. Executed physics, scenario set and carbon basis can all differ (the legacy-0 and physics-1 reports share seeds but not physics), so a safe version must refuse unless all three match; that is a separate, larger task.

## Changes (frontend only; no backend change)
- `src/evaluation/comparison.ts` (view-model): `policyOptions`, `defaultComparison`, `comparisonView`, `decidingConstraints`.
- `src/components/evaluation/PolicyComparison.tsx` + mounted in `EvaluationView.tsx` (keyed by report id so a different report never inherits a stale selection).
- Tests: `src/evaluation/comparison.test.ts` (12), `src/components/evaluation/PolicyComparison.test.tsx` (10). Docs: `PROVENANCE_AND_FRESHNESS.md`, `G-EVAL.md` addendum, register TG-A-21.

## Behaviour
Hard-constraint eligibility sentence and per-policy status first (words + icon shape, neutral styling); then what decided the report's outcome (outcome, reason, rule text as sent; selected candidate's violated limits and unsafe baselines when the report has PPO decision detail); then the table (four limits first, then other metrics in first-appearance order; difference = compared minus reference, % only when the reference is non-zero, direction word, the metric's own `better`); then uncertainty (paired PPO-vs-baseline intervals only for that exact pair; otherwise "uncertainty not provided"). Missing values read "not provided" and never produce a difference. Defaults carry no ranking: reference = first non-PPO policy in the backend's order, compared = a PPO row if any. The repo's static gate (no sort/rank/min-max/"winner"/highlight) passes unchanged.

## Verification (audit sandbox, Node 22.22; NOT your machine)
- `src/evaluation` + `src/components/evaluation`: 111 passed (8 files). `tsc`: no errors in the new files (the 16 pre-existing errors elsewhere are unchanged, TG-A-20). ESLint on the changed folders clean.
- Whole frontend suite: 10 failed / 1975 passed (vs 10 failed / 1953 passed at the Task 14 state, +22 tests). The 10 failures are the same pre-existing ones (TG-A-20); no new failure.

## Not done / limits
- **No real PPO data exists** (Task 9 pass 2 pending). PPO-specific paths (candidate violations, paired intervals, defaults to a PPO row) are tested with SYNTHETIC shape fixtures; check them against the first real report.
- No browser/E2E run and no assistive-technology pass (labels, scroll-region role and keyboard focus are by construction).
- Run-registry drill-down is not linked: the evaluation payload has no run id for `reports/runs/*`.
