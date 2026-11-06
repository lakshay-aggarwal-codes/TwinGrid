# Copilot: docs index stale or missing

Signals: documentation questions are answered without citations; responses carry `docs_index_unavailable` or
`docs_index_stale`; `python scripts/build_copilot_index.py --check` prints a status other than `fresh`.
The Copilot treats a missing, incompatible or stale index as off. It never answers from out-of-date documents.

1. Check: `python scripts/build_copilot_index.py --check`. It lists changed, added and removed documents, and exits 1 when
   the index cannot be used.
2. Rebuild: `python scripts/build_copilot_index.py`. Any edit to an indexed document (`docs/CLAIMS.md`, `docs/OPERATIONS.md`,
   `docs/PHYSICS_V2.md`, `docs/SENSITIVITY.md`, `docs/SLO.md`, and the folders `docs/model_cards`, `docs/runbooks`, `docs/copilot`)
   makes the index stale, so rebuild after every documentation change.
3. Spot-check: `python scripts/build_copilot_index.py --query "api down"` should list `docs/runbooks/api-down.md`.
4. The server re-checks about every 60 s, so no restart is needed. If the index file is somewhere else, set
   `COPILOT_DOCS_INDEX_PATH` for both the build and the server.
5. In the Docker stack the image contains no `*.md` files (`.dockerignore`), so the index cannot be built or checked there and
   `docs_index_unavailable` is expected. Run the backend from a checkout for documentation answers.
6. Measure after a large documentation change: `python scripts/copilot_eval.py --write-report` and read the gate table
   (`docs/model_cards/copilot.md` lists the last recorded numbers).
