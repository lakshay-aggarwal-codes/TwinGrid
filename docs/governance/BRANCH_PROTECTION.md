# Branch protection for `main` (commands only, NOT applied)

Nothing here has been run. Branch protection is a repository setting; the owner applies it with the GitHub CLI
(`gh auth login` first) or in Settings > Branches. Replace `OWNER/REPOSITORY`.

## Which checks to require

Required status check names are the job ids of `.github/workflows/ci.yml`:

| Check | Require? | Why |
|---|---|---|
| `lint` | yes | ruff, ruff format, external-data register |
| `test` | yes | pytest (no skips allowed) |
| `test-postgres` | yes | Alembic upgrade/check/downgrade and PostgreSQL tests |
| `audit` | yes | `pip-audit` on the lock |
| `frontend` | yes | typecheck, lint, vitest, build, `npm audit --audit-level=high` |
| `docker` | yes | image builds, non-root, `/healthz` |
| `types` | **after one recorded green run** | ceiling recorded (881); require it once the first CI run has been confirmed green |
| `frontend-e2e`, `frontend-contract` | no | `continue-on-error` (advisory) until recorded green once |
| `analyze (python)`, `analyze (javascript-typescript)` | after the first CodeQL run | CodeQL workflow |
| `gitleaks` | after the first run | secret-scan workflow |

A check can only be required after it has run once on the repository, because GitHub lists known check names
from past runs.

## Apply (classic branch protection)

Save as `protection.json`:

```json
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["lint", "test", "test-postgres", "audit", "frontend", "docker"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
```

Then:

```powershell
gh api --method PUT repos/OWNER/REPOSITORY/branches/main/protection --input protection.json
```

- `require_code_owner_reviews` is `false` because `.github/CODEOWNERS` is still a placeholder; set it to `true`
  after the owner fills it in.
- `enforce_admins: false` lets a sole maintainer merge; set `true` when there is a second reviewer.
- A single-maintainer repository cannot satisfy 1 required approval on its own PRs: set
  `required_approving_review_count` to `0` in that case.

## Check what is currently applied

```powershell
gh api repos/OWNER/REPOSITORY/branches/main/protection
```

## Also worth enabling (Settings > Code security)

Dependency graph, Dependabot alerts and security updates, secret scanning with push protection, private
vulnerability reporting. These are repository settings, not files; this repository does not know whether they are on.
