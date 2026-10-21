# Task 26 plan — SHOW-001 Evidence / Showcase page

Files touched (all owned by Task 26 except one noted line): `scripts/build_evidence.py`, `tests/test_build_evidence.py`,
`twin-stream-insight-main/src/features/evidence/*` (feature module, page, diagram, data layer, tests, `generated/*.json`),
and one added id in `twin-stream-insight-main/src/features/registry.test.ts` (its own comment asks each new feature to do this).

Tests first: `tests/test_build_evidence.py` (parse, missing source, validation, `--check`), `data.test.ts`,
`EvidencePage.test.tsx` (render, filters, not-recorded, honesty).

Commands: `python scripts/build_evidence.py --check`; `pytest tests/test_build_evidence.py`; `ruff check .; ruff format --check .`;
`npm run typecheck; npm run lint:ci; npm run test; npm run build` in `twin-stream-insight-main`.
