# R_L1: Assistant validator rejects forbidden wording

**Verdict: PARTIAL** (code and tests written; the pytest run is yours).

## Changed
- `src/copilot/llm.py`: `validate()` now raises `Rejected("forbidden_wording")` when the model's own typed words (with every
  `{{E#}}` removed) match a claim pattern: named cause, claimed action, calibration / production-ready / savings claims,
  affirmative normal/live/healthy, number words. The draft's own "The cause is not determined by available evidence." and
  "not a statement that the signal is normal." are stripped before the scan.
- `tests/test_copilot_adversarial.py`: strict xfail marker removed; the 9 `known_gaps` cases are now normal tests.
- `tests/test_copilot_llm.py`: 7 new rejection params, plus 3 positive controls (negated calibration, negated normal, plain "One alert").
- `docs/copilot/LIMITS.md`: one bullet describing the rule.

## Checked here (no pytest available: pypi unreachable from the sandbox)
- Called `validate()` directly on all 9 `known_gaps` replies: all 9 raise `forbidden_wording`. Two control replies were accepted.
- Python syntax of the three edited modules parses.

## NOT run (please run)
```powershell
python -m pytest tests/test_copilot_llm.py tests/test_copilot_adversarial.py -q; ruff check .; ruff format --check .
```
Expect 0 failed and the xfail count down by 9. Possible issue: ruff format may rewrap the long `pytest.param(...)` line.
Known limit: wording rules are regexes; a paraphrase not matching them still passes (numbers, links and markup stay covered separately).
