# Task 26 — SHOW-001 Evidence / Showcase page          Status: PARTIAL
Base: TwinGrid-main.zip as uploaded (git baseline tag in sandbox)     Date: 2026-10-21
Environment: Python 3.12.3, Node 22.22.2, no network (npm ci failed), no pytest, no ruff.

## Summary
Adds `/evidence`, a static page (no API calls) built from the repo's own documents by `scripts/build_evidence.py`:
scope, claims ledger with filters, model status incl. the registered PPO outcome C / claim allowed none, architecture
diagram with text equivalent, "how it was verified" (reads `evidence/status.json`, absent -> "not recorded for this
build"), and a skills map whose paths are verified to exist. Frontend gates were NOT run (see below).

## Acceptance checklist
- Page renders without backend: met for server render (esbuild + react-dom/server, all 6 sections, 35 claim rows); browser/vitest render NOT run.
- Generated data matches docs: met, `python scripts/build_evidence.py --check` exit 0.
- Honesty test passes: met in SSR check (no banned word outside quoted source text; none used positively in supported rows). The vitest version is NOT run.
- `--check` fails when stale: met, covered by `test_check_detects_missing_and_stale_and_write_fixes_it`.
- Every figure shows its source path: met (per-claim paths, per-section Source lines, PPO run files).
- Accessible/responsive: partial by construction (headings, table captions/scopes, aria-pressed, glyph+word status, overflow-x tables, SVG with title/desc). No axe or browser run; no conformance claim.

## Changed files
- scripts/build_evidence.py — generator with `--check`
- tests/test_build_evidence.py — 11 tests
- twin-stream-insight-main/src/features/evidence/{index.ts,EvidencePage.tsx,ArchitectureDiagram.tsx,data.ts} — feature
- .../evidence/{EvidencePage.test.tsx,data.test.ts} — tests
- .../evidence/generated/*.json — generated data
- twin-stream-insight-main/src/features/registry.test.ts — added "evidence" to the shipped-features list (cross-task edit, one line)

## Commands run
- `python scripts/build_evidence.py` / `--check` -> exit 0
- 11 Python tests via a hand-written runner (pytest not installed) -> 11 passed, 0 failed
- esbuild bundle + react-dom/server render of EvidencePage, normal and empty data -> as described above
- tsc against stub declarations -> clean (weak check, not the project config)

## Pre-existing failures observed
None observed; the full suites were not run.

## Not run / blocked
- Frontend gates (no network): `cd twin-stream-insight-main; npm ci; npm run typecheck; npm run lint:ci; npm run test; npm run build`
- `ruff check .; ruff format --check .` (hand-wrapped long lines; run `ruff format .` if it complains)
- `pytest tests/test_build_evidence.py tests/test_task33_claims.py`
- Browser check, axe scan.

## Decisions and defaults used
- Filters: Supported = fact+result; Assumption; Not supported = hypothesis+future (unknown kinds count as not supported). Every row shows its limit.
- Headline PPO outcome shown only if all recorded runs agree, otherwise "runs disagree"; policy table comes from the latest run.
- `LIMITATIONS.md` section "Wording rules" is skipped (guidance to authors, names the banned words).
- Banned-word list lives only in the test file because `test_task33_claims.py` scans frontend source for some of those words.
- Quoted source text (`data-quoted="source"`) may contain a banned word only as a denial or in a non-supported row.

## Requested cross-task changes
- `evidence/status.json` (repo root) is to be filled by the integrator with real run results. Format is in the docstring of `scripts/build_evidence.py`. After editing it, run `python scripts/build_evidence.py`.
- Re-run the generator whenever `docs/CLAIMS.md`, `LIMITATIONS.md` or a PPO `results.json` changes (Task 21 may add `--check` to CI).

## New limitations or risks
- Architecture diagram is hand-drawn; it can drift from `docs/architecture/system.md`.
- Skills-map file lists are curated in the script, not discovered.
- No authz-matrix fragment: the route is frontend-only.

## Next tasks unblocked
Task 21 (CI can run `--check`), Task 28 (a11y sweep includes /evidence), Task 30 (integrator fills status.json).
