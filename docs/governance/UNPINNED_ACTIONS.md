# GitHub Actions that are not pinned to a commit SHA

Every `uses:` in `.github/workflows/` references a **major version tag** (for example `actions/checkout@v4`), not a
full commit SHA. A tag can be moved by the action's owner; a SHA cannot. This is a known, accepted gap: SHAs could
not be resolved offline when these workflows were written, and the list below is the work to close it.

Mitigations in place: workflows declare least-privilege `permissions:`; only `GITHUB_TOKEN` is used (the release
workflow's only secret); no workflow runs on `pull_request_target`; Dependabot (`github-actions` ecosystem, weekly)
proposes updates.

## Inventory

| Action | Used in |
|---|---|
| `actions/checkout@v4` | ci, release, load, codeql, secret-scan, sbom |
| `actions/setup-python@v5` | ci, release, load |
| `actions/setup-node@v4` | ci, release |
| `actions/upload-artifact@v4` | ci, release, load |
| `actions/download-artifact@v4` | release |
| `actions/attest-build-provenance@v2` | release |
| `docker/setup-buildx-action@v3` | release |
| `docker/login-action@v3` | release |
| `docker/metadata-action@v5` | release |
| `docker/build-push-action@v6` | release |
| `github/codeql-action/init@v3` | codeql |
| `github/codeql-action/analyze@v3` | codeql |
| `gitleaks/gitleaks-action@v2` | secret-scan |
| `anchore/sbom-action@v0` | sbom |

A test (`tests/test_task10_governance.py`) fails if a workflow uses an action that is missing from this table.

## How to pin one (per action)

1. Find the commit the tag points to: `gh api repos/<owner>/<repo>/commits/<tag> --jq .sha`
2. Replace `@v4` with `@<40-char sha> # v4` in every workflow that uses it.
3. Keep the action name in this table (the test matches the name; Dependabot updates SHA-pinned actions and keeps the
   version comment).
