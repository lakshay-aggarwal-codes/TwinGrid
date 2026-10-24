# R_L1: Assistant validator rejects forbidden wording

**Verdict: DONE** (owner's runs, 2026-10-24).

## Changed
- `src/copilot/llm.py`: `validate()` now raises `Rejected("forbidden_wording")` when the model's own typed words (with every
  `{{E#}}` removed) match a claim pattern: named cause, claimed action, calibration / production-ready / savings claims,
  affirmative normal/live/healthy, number words. The draft's own "The cause is not determined by available evidence." and
  "not a statement that the signal is normal." are stripped before the scan.
- `tests/test_copilot_adversarial.py`: strict xfail marker removed; the 9 `known_gaps` cases are now normal tests.
- `tests/test_copilot_llm.py`: 7 new rejection params, plus 3 positive controls (negated calibration, negated normal, plain "One alert").
- `docs/copilot/LIMITS.md`: one bullet describing the rule.

## Evidence (pasted by the owner)
- `pytest tests/test_copilot_llm.py tests/test_copilot_adversarial.py -rx -q`: **235 passed, 0 failed, 0 xfailed** (before: 216 passed, 9 xfailed).
- `ruff check .`: All checks passed. `ruff format --check .`: 442 files already formatted (after reformatting `tests/test_copilot_llm.py`).
- `pytest tests/test_copilot_llm.py`: 56 passed, 1 deselected.

## Fixture change (not a weakening)
`llm_replies.json`, case `stale_signal_called_normal_and_live`: `must_not_contain` changed from `["is normal", ...]` to
`["normal and live", ...]`. The served rule-based fallback legitimately says "not a statement that the signal is normal", so the
old phrase failed on honest text. The reply itself is still rejected (`rejected_forbidden_wording`) and `assert_no_claims` still runs.

## Limit
Wording rules are regexes; a paraphrase that matches none of them still passes. Numbers, links and markup are covered separately.
