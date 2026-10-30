# CP-6 report: retrieval index and search

## What changed (new files only; no CP-5 file was edited)
- `src/copilot/rag/tokenize.py`: one tokenizer for documents and queries (accent folding, `[a-z0-9]+` tokens, stop words, crude stemmer). `normalize_query` caps a query at 300 characters and 32 terms.
- `src/copilot/rag/index.py`: `build_index`, `load_index`, `check_freshness`, `default_index_path`. The index is one SQLite file, written to a temporary file and moved into place, so a failed build never damages the old index.
- `src/copilot/rag/search.py`: `search(index, query, k)` returns `SearchResult` with `hits` (chunk, score, `matched_terms`, `coverage`), `best_score`, the threshold used and a reason code (`ok`, `no_query_terms`, `no_match`, `below_threshold`).
- `scripts/build_copilot_index.py`: build, `--check`, `--query`.
- Tests: `tests/test_copilot_rag_search.py` (47).

## Deviation from the roadmap (please check)
The roadmap says SQLite FTS5, with pure-Python BM25 only as a fallback. I made the **BM25 the primary**, stored in SQLite tables, and load it into memory at startup. Reasons: (1) the corpus is about 120 chunks, so speed is irrelevant; (2) the same scores on every SQLite build (FTS5 is optional in some builds); (3) matched terms come for free; (4) there is no MATCH query syntax for a hostile query to reach, because search never runs SQL at all; (5) CP-9 can retune field weights without a rebuild. If you want FTS5 anyway, it can be added behind the same `search()` interface in CP-12.

## Behaviour
- **Fields:** a chunk is scored on its text (weight 1), heading path (3) and file name (2). BM25 `k1=1.2`, `b=0.75`.
- **Threshold:** hits under `min_score` are dropped; `DEFAULT_MIN_SCORE = 6.0` is a **placeholder** (roadmap: set from CP-9 data). Rejected searches still report `best_score`.
- **Staleness:** `check_freshness` compares each document's `doc_hash` with the index and reports `fresh`, `stale` (lists changed, added, removed documents), `missing` or `incompatible` (bad file, wrong schema or tokenizer version). Callers must fall back, not crash: `load_index` raises only `IndexUnavailable`.
- **Safety:** a query is normalised and capped first, only `[a-z0-9]+` terms leave the tokenizer, and search is pure Python. Tests run SQL-injection, FTS-operator, NUL-byte, HTML and path-traversal queries and check the index file is byte-identical afterwards.
- **Index location:** `data/copilot/docs_index.sqlite` (override `COPILOT_DOCS_INDEX_PATH`; relative paths are relative to the repo root). `*.sqlite` is already in `.gitignore`. I did not edit `.env.example`; CP-11 owns that file.

## Measured here, on the supplied repo's docs (this sandbox only)
- 19 documents, 123 chunks, 1,665 terms, index 412 KiB. Build 98 ms, load 11 ms, freshness check 22 ms. Search p50 0.075 ms, p95 0.149 ms (800 calls).
- 20 hand-written in-corpus questions and 16 unrelated ones, best-hit score with no threshold:
  - in-corpus: 18 of 20 scored 5.67 or more; the two lowest were "what is the sensitivity analysis" (3.45) and "what is physics v2" (4.38).
  - unrelated: 7 of 16 matched nothing at all; the other 9 scored 3.05 to 5.43 on one generic word ("best pizza recipe" 5.43, "explain quantum entanglement" 5.14).
  - **Finding:** no single score separates the two groups. At 6.0 no unrelated question gets a hit, but the three lowest in-corpus questions above (sensitivity 3.45, physics v2 4.38, "which physics versions exist" 5.67) are also refused. The placeholder leans towards "not documented" rather than citing a wrong passage. CP-9's 40 to 50 questions are what should fix the number, and may show that a coverage rule is needed too (see `coverage` below).
- `coverage` (share of the query's idf weight that the chunk matched) is reported on every hit but does **not** gate anything. On these 36 questions it did not separate the groups either (single-word queries score 1.0 whatever they ask).

## Test results
- `pytest tests/test_copilot_rag_search.py tests/test_copilot_rag_corpus.py tests/test_copilot_rag_chunker.py --noconftest`: 84 passed, 0 failed (47 new, 37 from CP-5).
- `ruff check` and `ruff format --check` on every new file: clean.
- Mutation check: ignoring the threshold, making the freshness check always say fresh, removing stemming, zeroing the heading/file-name weights and skipping the tokenizer-version check each made at least one test fail.

## Not verified
- Run with `--noconftest` (your `tests/conftest.py` needs numpy, pandas and the twin model, not installed here). The new modules use only the standard library.
- Only `python3.12` on Linux. Not run on Windows; the code builds the SQLite URI with `Path.as_uri()` (handles spaces and drive letters) and the script re-encodes stdout to UTF-8, and a test builds into a folder with a space in its name, but none of that is run on Windows here.
- Retrieval quality beyond these 36 hand-checked questions. No relevance judgements by a second person; CP-9 does that properly.
- The "real corpus" tests will fail if your real docs differ enough (that is the drift check), notably if `docs/SLO.md` or the runbook texts change.
- Nothing here is wired to `/api/copilot/ask`; CP-7 does that.
