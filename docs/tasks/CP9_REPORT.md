# CP-9 report: evaluation harness

**Status: delivered (v2, see "Delivery correction"). The harness runs offline and writes `docs/copilot/EVAL_REPORT.md`. Two of the four gates pass, one fails, and one passes only narrowly in-sample. Numbers below are from the supplied zip, not from your checkout: re-run there.**

## Delivery correction (v2)
The first ZIP replaced `src/copilot/docs_answer.py`, `llm.py`, `rag/corpus.py` and `rag/search.py` as whole files, built from the CP-7 zip. The real checkout already had newer versions (CP-8: `DocsPassage.flags`, `llm.enhance(private_terms=...)`), so extracting the ZIP broke 175 tests. That was my error: the roadmap says the supplied zip can be older than the checkout. v2 ships **new files only** plus `cp9_apply_product_patch.py`, which edits the three product files in place by anchor, writes nothing if any anchor is missing, and is safe to re-run. `llm.py` is no longer touched (the first ZIP changed only a comment there). The patch was verified only against the CP-7 files; it has not been run against your CP-8 files.

## What changed
- `tests/copilot_eval/questions.yaml` (new): 50 golden questions: 24 in-corpus (expected source chunk, expected intent), 10 out-of-corpus, 9 adversarial, 7 other-intent (including a live-state question that mentions the runbook). Gates and recorded floors live in the same file.
- `tests/copilot_eval/harness.py` (new): the engine. Retrieval layer (replay of the product's floors, fit, leave-one-out), end-to-end layer through the real `answer_question`, scripted-fake rephrase variants through the real `llm.enhance`/`validate`, eight injected-fault failover scenarios through the real router, optional real-provider run, report renderer.
- `scripts/copilot_eval.py` (new): CLI. `--write-report`, `--json`, `--no-failover`, `--no-fail`, `--real --real-limit N`. Exit code 1 if a gate fails, 2 if BLOCKED (checkout differs from the question file).
- `tests/copilot_eval/test_harness.py` (new, 33 tests): assumed files and headings exist; harness arithmetic; the replay equals `rag_search.search`; recorded floors are not undercut; every unfaithful variant is rejected; failover call counts; report fields; real-run path with fake HTTP.
- `docs/copilot/EVAL_REPORT.md` (new, generated).
- **Product code changed (small, deliberate; applied by `cp9_apply_product_patch.py`):**
  - `src/copilot/rag/search.py`: new `min_coverage` floor (the `Hit.coverage` hook CP-6 left "for CP-9"), new reason `low_coverage`, `SearchResult.min_coverage`. Defaults replaced the placeholder: score floor 6.0 -> **6.5**, coverage floor **0.40**. A caller that passes its own `min_score` keeps the old semantics (coverage floor 0), so no existing test changed.
  - `src/copilot/docs_answer.py`: `DocsRetriever(min_coverage=...)` pass-through.
  - `src/copilot/rag/corpus.py`: `docs/copilot/EVAL_REPORT.md` is always excluded from the corpus and from the scan's "skipped" list. Without this the evaluation would index its own report (it quotes the questions) and change the corpus it describes.
  - `DOCS_UNGROUNDED_MAX` stays 0 (see below); `llm.py` is untouched in v2.

## Results (offline, this zip)
| Gate | Value | Target | |
|---|---|---|---|
| hit@3 served (retrieval) | 0.875 | >= 0.85 | PASS (in-sample; leave-one-out 0.833) |
| correct refusal (end to end) | 0.800 | >= 0.90 | **FAIL** (retrieval-only refusal is 0.900; leave-one-out 0.700) |
| accepted answers with an unknown number | 0 | 0 | PASS |
| adversarial handled | 9/9 | 1.00 | PASS |

Other numbers: ranking with no floors hit@1 0.708, hit@3 0.875, MRR 0.796. Failover 29/29 as intended, 0 raised. Unfaithful scripted replies rejected 80/80. Latency p50 0.5 ms, p95 2.6 ms (our code only).

## Findings you should know
1. **Only 10 of 24 in-corpus questions reach retrieval end to end.** The rest have no docs cue ("runbook", "documentation", "how do I ...") and go to an older intent. That is CP-7's design, but it means the user-facing cited-answer rate is 0.417 while the retrieval gate looks healthy. This is the biggest gap and no gate measures it. The recorded floor `routed_in_corpus` keeps it from getting worse.
2. **No threshold alone meets both retrieval gates.** The placeholder 6.0 gave hit 0.875 but refusal 0.600. The best score floor alone gives 0.833 / 0.900. Adding the coverage floor reaches 0.875 / 0.900 in-sample, exactly on both targets, and leave-one-out falls to 0.833 / 0.700. The working band for coverage is about 0.36 to 0.44.
3. **A CP-7 test found a false accept the first 50 questions lacked** ("pizza recipes" matched `CLAIMS.md` on the word "say"). I replaced O10 (world-cup trivia, the easiest negative) with it before fitting. That is the one post-hoc edit to the set; it is recorded in the file header. One question moves hit@3 by 4.2 points and refusal by 10, so the gates are noisy.
4. **Chunker size, overlap and BM25 field weights do not help.** A grid over 5 chunk sizes x 7 weight pairs left the best attainable score on the plateau every time (probe, not shipped).
5. **Known hole, measured:** a reply that reverses a passage using only its own words is accepted 10/10 (variant H1). `ungrounded_text` is a lexical guard. A test pins this so it cannot silently change either way.
6. **CP-12 rule:** the hit@3 gate passes in-sample, so by the roadmap rule CP-12 is skipped. I would not read that as strong: the out-of-sample estimate is below the gate, and the three misses (D13, D16, D23) look like vocabulary or ranking problems. Your call.
7. **`DOCS_UNGROUNDED_MAX` left at 0.** One extra connecting word ("according to") is rejected (F2). Raising it needs real-model output, not my scripted replies.

## Tested here
- 33 new tests pass. 251 pass across the new tests and the existing rag, llm, router tests (`pytest tests/copilot_eval tests/test_copilot_rag_*.py tests/test_copilot_llm.py tests/test_copilot_router.py`). Also run and green: answer, tools, catalogue (except below), local, presets, providers, `test_task33_claims`.
- `ruff check` and `ruff format --check` clean on the touched files.

## Not done / not verified
- **Known failure, unchanged:** `tests/test_copilot_rag_search.py::...[what are the Copilot limits-LIMITS.md]` (score 5.8 vs floor 6.5). It already failed on the untouched zip. It is the same Copilot-vs-"assistant" vocabulary gap as D23. Reported, not fixed.
- **Not run here:** `test_copilot_api.py`, `test_copilot_adversarial.py` (need gymnasium and the ML stack), and `test_copilot_catalogue.py::test_every_api_path_is_in_the_openapi_document` (same reason). Please run them. Retrieval defaults changed, so a route-level docs question is worth one look.
- **The real-provider path is not run.** It is tested only with a fake HTTP layer. Nothing here says how a real model is rejected.
- The report's `Commit` reads "unknown" because the supplied zip has no `.git`. Re-run in your checkout.
- The frontend was not touched or run.
- No confidence intervals. No per-intent data policy (CP-8). CP-11 owns the CLAIMS rows for this.

## Decisions for you
1. Ship the coverage floor as is, or revert to the score-only floor (8.0: refusal 0.900 / hit 0.833, fails the hit gate)?
2. Is the end-to-end refusal gate (strict: no citation AND an explicit refusal) the right definition? O07 falls to a feature-catalogue answer with no citation; under a looser "no citation" reading refusal would be 0.9.
3. Do you want routing recall (finding 1) added as a gate or a task before CP-11?
