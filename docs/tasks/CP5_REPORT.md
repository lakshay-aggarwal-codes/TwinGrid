# CP-5 report: docs corpus and chunker

## What changed (new files only, no existing file touched)
- `src/copilot/rag/corpus.py`: a closed allow-list of Markdown sources (`docs/CLAIMS.md`, `OPERATIONS.md`, `PHYSICS_V2.md`, `SENSITIVITY.md`, `SLO.md`, and everything under `docs/model_cards/`, `docs/runbooks/`, `docs/copilot/`). `scan`, `discover`, `missing_allowed`, `load_document`, `build_corpus`.
- `src/copilot/rag/chunker.py`: `chunk_markdown` cuts a document by heading into `Chunk(chunk_id, source_path, heading_path, doc_hash, ordinal, text, text_hash)`.
- Tests: `tests/test_copilot_rag_corpus.py` (15), `tests/test_copilot_rag_chunker.py` (22).

## Rules enforced
- **Always excluded, cannot be lifted:** any path part starting `.env`; directories named `secrets`, `secret`, `data`, `logs`, `log`, `.git`, `node_modules`, `__pycache__`.
- **`security` directories** are excluded unless the caller passes the file or folder in `extra_allow`. Even then the always-excluded tier still applies.
- Symlinks are never followed, anything resolving outside the repo is refused, files over 512 KiB are skipped. Skips are returned in `Corpus.skipped` with a reason, never dropped silently.
- `extra_allow` entries with `..`, a leading slash or a drive letter raise `CorpusError`.
- Text is normalised before hashing (BOM, CRLF/CR to LF, control characters removed), so Windows and Linux checkouts give identical ids and hashes.

## Chunk ids
`chunk_id` = first 16 hex of SHA-256 over `source_path`, `heading_path`, which repeat of that heading it is, and the part number inside the section. It does **not** depend on the text, so citations survive rebuilds and edits that do not move headings. `text_hash` changes with the text; `doc_hash` (full SHA-256) changes with the document. Editing one document changes only that document's chunk hashes (tested).

## Assumptions
- Only `.md` files are indexed (`docs/copilot/capabilities.json` is not).
- Defaults `max_chars=1200`, `overlap=120` are starting values; CP-9 should tune them. Hard cap includes overlap.
- Heading-level 1 to 6 ATX headings only. Setext headings (`Title` over `====`) are treated as body text.
- A fenced code block longer than the cap is split by lines and the fence markers are not repeated in the later pieces.
- When a section is split, chunk N+1 starts with up to 120 characters copied from chunk N. CP-6 should index `heading_path` as its own field, and CP-7 should not quote the overlap twice.

## Measured on the supplied repo zip (this sandbox only)
- 19 documents, 123 chunks, mean 751 characters, max 1200. Nothing skipped, nothing missing.
- `docs/security/`, `.env*`, `data/` and `logs/` contribute 0 chunks.
- NOT measured: retrieval quality (that is CP-6 and CP-9).

## Test results
- `pytest tests/test_copilot_rag_corpus.py tests/test_copilot_rag_chunker.py --noconftest`: 37 passed, 0 failed.
- `ruff check` and `ruff format --check` on the 5 new Python files: clean.
- Mutation check: removing the `security` rule, removing the `.env` rule, removing CRLF normalisation and treating code fences as headings each made tests fail.

## Not verified
- I ran the tests with `--noconftest` because the repo's `tests/conftest.py` imports numpy, pandas and the twin model, which are not installed here. The new modules import only the standard library, so this should not matter, but run them once in your venv with the normal conftest.
- Full suite not run. CP-0 to CP-4 are not applied in the supplied repo; CP-5 does not depend on their code.
- `test_every_allow_listed_file_and_folder_exists_in_this_repo` is the repo-drift check: it fails loudly if your real checkout lacks an allow-listed document.
