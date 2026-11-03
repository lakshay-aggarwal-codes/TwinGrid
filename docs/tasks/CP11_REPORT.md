# CP-11 report: ops, docs, claims, model card

**Status: built. Documentation, runbooks, claims rows, model card, two perf specs, one test file. Nothing here was run on your
machine.** Evidence labels: *local source* = read in the supplied zip (`TwinGrid-wip-cp8-hardening`); *run here* = executed in the
build sandbox (no network, no pytest, no ruff, no Docker, no Ollama); *unverified* = not executed anywhere.

## What changed
- `docs/OPERATIONS.md`: new "Copilot" section (local-only, cloud failover chain and a two-provider demo, replace a provider key,
  what an outage looks like, rebuild the index, Docker note); `COPILOT_LLM_<NAME>_API_KEY` added to the secrets inventory.
- `docs/runbooks/copilot-providers-down.md`, `copilot-index-stale.md` (new) and two rows in `docs/runbooks/README.md`.
- `.env.example`: block CP11 with the names that were missing (`COPILOT_DOCS_INDEX_PATH`, `COPILOT_LLM_LOCAL_TIMEOUT_S`, the
  per-provider `COPILOT_LLM_<NAME>_*` family). Names only; no values.
- `docs/CLAIMS.md`: rows C-36 failover, C-37 documentation answers, C-38 local-only, C-39 guarded rephrasing (the Boundary column
  is the "does not claim" column, as in the existing ledger). C-24 now says nine runbooks.
- `docs/model_cards/copilot.md` (new): intended use, data flow, evaluation table, limitations, provider-terms caveat.
- `README.md`: the assistant bullet no longer says "No language model is connected"; new Copilot paragraph (wording from
  roadmap section 5 plus the failing gate). `docs/JUDGES.md`: two sentences that said "no language model" corrected.
- `scripts/perf_endpoints.py`: specs `copilot_ask_rag` and `copilot_ask_failover`.
- `tests/test_copilot_cp11_ops.py` (10 tests): every `COPILOT_*` name the code reads is in `.env.example`; no key values; every
  runtime warning code is in OPERATIONS; runbooks linked and commands exist; perf questions route as intended; claims rows used
  by the README; the model card cannot hide a failing gate in `EVAL_REPORT.md`; the old "no language model" wording is gone.
- `scripts/cp11_patch_docs_retriever.py` (one-off, see finding 1).

## Findings you should know
1. **`python scripts/copilot_eval.py` fails in the supplied checkout** with `TypeError: DocsRetriever.__init__() got an
   unexpected keyword argument 'min_coverage'` (run here, local source). `rag/search.py` has the CP-9 coverage floor but the
   `DocsRetriever` pass-through in `docs_answer.py` was never applied. The running product is not affected: the shared
   retriever passes no floors, so `search` takes both fitted defaults. The patch script adds the pass-through by anchor and
   writes nothing if an anchor is missing. With it applied, the full harness ran here (run here, offline, fake providers).
2. **The CP-9 gate numbers did not move after these documents joined the corpus** (22 to 25 documents, 144 to 170 chunks): hit@3
   0.875, correct refusal 0.800 (still **FAIL** against 0.90), unknown numbers 0, adversarial 1.000, leave-one-out 0.833 / 0.700.
   MRR moved 0.796 to 0.793. A retrieval-only before/after on all 34 in-corpus and out-of-corpus questions changed no question's
   outcome. `docs/copilot/EVAL_REPORT.md` still says 22 documents: regenerate it on your machine.
3. **The Docker image has no documents** (`.dockerignore` has `*.md`), so in the supplied compose stack documentation answers
   report `docs_index_unavailable`. OPERATIONS and the model card say so. Mounting the docs and index was not tried.
4. **`docs/copilot/LIMITS.md` still says "There is no language model in this tree"** and `test_copilot_adversarial.py` reads that
   file, so I did not touch it. It now contradicts the README and the model card. Fixing it needs a decision on the test.
5. Historical task reports (TASK_14/15, R3_TASK_13, EVIDENCE_MATRIX) also say "no language model". Left as history.

## Not done / not verified
- Not run on your machine: `pytest`, `ruff`, the demo steps in OPERATIONS (Ollama, the dead-first-provider failover demo, the
  PowerShell login block), `perf_endpoints.py` against a live server. The 10 new tests and the existing claims test
  (`test_task33_claims.py`, 8 tests) were run here with a small stand-in runner, not pytest: all passed.
- The failover demo uses an unreachable local URL to force a fall-through. Cloud serves documentation questions only by
  default (CP-8), so the demo question is a documentation one and needs the index and a checkout-run backend.
- No real provider was run; no provider terms were verified; free-tier numbers are as recorded in `docs/copilot/PROVIDERS.md`.
- Roadmap row "A runbook for all providers down and index stale": done as two runbooks. "Fresh reader from clone to a working
  local-only copilot" has not been tried by anyone.

## Defaults used
- C-36..C-39 evidence uses existing tests, not new live runs. CP-12 stays skipped (hit@3 gate passes in-sample).
