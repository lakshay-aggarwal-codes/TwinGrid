# CP-0 report: baseline and characterization

**Status:** done. Tests only; no production file was changed.

## What changed

| Path | Purpose |
| --- | --- |
| `tests/characterization/copilot/test_intents_golden.py` | 21 golden cases over all 6 intents (answer, evidence, unknowns, warnings, links, intent, mode, limits), per-case contract invariants, routing table, history/injection-in-history check, unknown-alert `NotFound` |
| `tests/characterization/copilot/test_llm_outcomes.py` | off / not configured / nothing to phrase; accepted rephrase (golden of answer and request shape); 12 rejection codes; 4 forbidden-wording classes; unavailable: timeout, 429, 500, 503, 401, 403, 404, invalid JSON, 5 bad-envelope shapes, oversize, redirect, connection refused; log contents; defaults and bad numbers |
| `tests/characterization/copilot/test_assumed_files.py` | repo-drift check: assumed files and names must exist (existence only, not content) |
| `tests/characterization/copilot/conftest.py`, `_support.py`, `__init__.py` | loopback fake provider, env isolation, golden helper |
| `tests/characterization/copilot/golden/intents/*.json` (21), `golden/llm/accepted_rephrase.json` | stored expected JSON |
| `docs/copilot/CURRENT_STATE.md` | env variables and where each is read, request path, outcome table, known gaps |

## How the tests are built

- The LLM path is configured only through `COPILOT_LLM_*` and observed through the returned `Answer` and the log
  `outcome=` word. A real loopback HTTP server plays the provider, so timeouts, status codes and redirects go through
  `requests`. No external network. Because of this, CP-1's refactor behind a provider layer must leave them unchanged.
- Goldens never change silently. A mismatch fails; re-recording needs `COPILOT_CHAR_UPDATE=1` and a reviewed diff.
- The what-is-this cases use a small fixed catalogue so later edits to `docs/copilot/capabilities.json` do not move them.

## What was tested

- **In this sandbox:** 110 new tests pass. The three existing files that load here (`test_copilot_answer.py`,
  `test_copilot_llm.py`, `test_copilot_tools.py`) pass: 95 passed, 1 deselected (`live_llm`).
- **Teeth check:** temporarily removing the `production-ready` forbidden-wording pattern and rewording the "cause is not
  determined" sentence made 8 new tests fail; the files were then restored byte for byte.

## What was NOT tested

- **The new tests were not run under `tests/characterization/conftest.py`.** It imports `fastapi`, `httpx`,
  `pytest_asyncio` and `sqlalchemy`, which this sandbox cannot install (no network). I ran them with
  `--confcutdir=tests/characterization/copilot` instead. The new tests do not use anything from the parent conftest, so
  they should behave the same on your machine, but that is not proven here.
- `tests/test_copilot_catalogue.py` (one test imports `api.main`), `test_copilot_adversarial.py` and `test_copilot_api.py`
  could not run here for the same reason (missing `fastapi` / `sqlalchemy`). **Existing copilot tests that fail on your
  machine are to be reported, not fixed**; I have none to report.
- The `live_llm` test was not run (no key, no network), as designed.

## Findings (recorded, nothing fixed)

1. **Contract rule 7 is not met today.** The provider receives the question, string evidence including the stored alert
   message, and the alert id (`entity: "alert:42"`). Pinned in `golden/llm/accepted_rephrase.json`; CP-8 must change it.
2. **Routing quirks** from substring matching: "Which layout is preferred?" routes to `why_red` ("preferred" contains
   "red"); "Why did the model change?" routes to `why_red` because only "changed" and "change since" are keywords.
   Pinned in `test_routing_table`.
3. Only one provider is supported and any failure goes straight to rule-based (expected; CP-1/CP-2 change this).

## Note for later tasks

CP-1 must keep all of these passing unchanged. CP-2 may add fields to the log line (the tests match `outcome=<word>`
anywhere in it) and may add attempts, but a single failing provider must still end as rule-based plus the same warning.
CP-7 and CP-8 will legitimately change `accepted_rephrase.json` and `CURRENT_STATE.md`; re-record on purpose.
