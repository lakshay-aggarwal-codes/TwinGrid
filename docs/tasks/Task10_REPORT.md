# Task 10 - Supply chain and governance files

Claim: **scanning configured** (never "scanning passing").

## What changed
- New: `.github/dependabot.yml` (pip, npm, github-actions, docker; weekly, one grouped PR each), `workflows/codeql.yml` (Python + JS/TS), `workflows/secret-scan.yml` (gitleaks, full history), `.gitleaks.toml` (default rules + regex allowlist of documented placeholders only), `workflows/sbom.yml` (SPDX artifact), `CODEOWNERS` (placeholder, rules commented out), PR template, issue templates (bug, feature, config).
- New docs: `docs/governance/BRANCH_PROTECTION.md` (`gh api` commands, not applied; required checks taken from `ci.yml` job ids), `docs/governance/UNPINNED_ACTIONS.md` (all 14 actions, how to pin).
- Rewritten: `SECURITY.md` (implemented vs CI-run vs configured-only; contact `<OWNER MUST FILL>`; old "Dependabot is not configured" line removed). Updated: `CONTRIBUTING.md`.
- `ci.yml` untouched. `tests/test_task10_governance.py` (9 tests).

## Assumptions
- All new workflows have top-level `permissions: contents: read`; CodeQL's job adds `security-events: write`. No `pull_request_target`; only `GITHUB_TOKEN`.
- Actions pinned by major tag (no network to resolve SHAs); listed in UNPINNED_ACTIONS.md.
- gitleaks-action needs a `GITLEAKS_LICENSE` secret on organization-owned repos (noted in the workflow).
- `types` is left out of the suggested required checks: `ci.yml` makes it fail until `PYREFLY_ERROR_CEILING` is recorded.
- Dependabot edits `requirements*.txt`, not the hash-pinned lock; CONTRIBUTING says to regenerate the lock via the `bootstrap` job.
- CODEOWNERS rules are commented out because an unknown handle makes GitHub report errors.

## Test results (real output)
- pytest is not installed in the sandbox (no network); the 9 tests were run with a minimal runner: `passed 9 failed 0`.
- All `.github/**/*.yml` parse with PyYAML; `.gitleaks.toml` parses with tomllib.

## Not verified
- Real `pytest`/`ruff` run; any workflow on GitHub (CodeQL, gitleaks, SBOM, Dependabot); whether gitleaks flags anything in the history.
- The `OWNER/REPOSITORY` and `<OWNER MUST FILL>` placeholders must be filled by the owner.
