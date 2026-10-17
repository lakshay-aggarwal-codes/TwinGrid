# Task 33 report: README, claims ledger and judges pack

## What changed
- **`README.md`** rewritten as the single entry point: what it is and is not, Mermaid architecture, quickstart (marked "not timed"), feature tour with screenshot placeholders, ML results, engineering facts, links. Every claim bullet ends in a `[C-nn]` tag.
- **`docs/CLAIMS.md`**: 34 rows, each with status, evidence files and boundary (fact 26, result 3, assumption 2, hypothesis 2, future 1). Every ML number points at the model cards, which point at `models/registry.json` and the report files.
- **`docs/JUDGES.md`**: five-minute demo mapped to pages and claim ids, the ten hardest questions with honest answers, a differentiators table. **`docs/DEMO_CHECKLIST.md`**: pre-demo checklist and fallbacks.
- **`twin-stream-insight-main/docs/frontend/STATUS.md`**: added a table of roadmap tasks T1 to T24, T30, T31, T33 with links to their reports; marked the FloorHeatmap note as partly resolved (the file no longer exists). The rest of the file is unchanged and still says FE-19 and FE-20 are not signed or measured.
- **`PERFORMANCE_OPTIMIZATION.md`**: a status banner and neutral wording. It said "ready for production deployment", "Real-time Ready" and "physics accuracy" about timings from an earlier session. The numbers are untouched and still not re-measured.
- **`tests/test_task33_claims.py`** (8 tests): ledger rows complete and unique, every evidence path exists, hypotheses are not worded as met, every README claim bullet and judges row carries a real ledger id, every ledger row is used, the ten questions are present, and the overclaim words are absent from the public documents and the frontend source.

## Scan of docs and UI strings
Searched for "production-ready", "validated", "real-time", "calibrated", "digital twin of a real facility", "optimal", "AI-optimized", "state-of-the-art". Fixed: `PERFORMANCE_OPTIMIZATION.md` (above). Already qualified, left alone: the physics, ML and CONTRIBUTING documents (they forbid the words), the equipment-health caption ("validated on a proxy dataset, not on this facility"), the frontend provenance labels. No frontend string needed changing.

## Assumptions
- Tasks 25 to 29 were not in the repository copy I was given, so the README, ledger and STATUS table do not mention them. A ledger row only passes the test if its evidence file exists, so adding those features later means adding rows.
- Quickstart is written from `scripts/demo.ps1`, `Procfile` and `package.json`, not run. Screenshots are placeholders.
- The only `STATUS.md` in the repo is the frontend one, so that is the one I updated.

## Not verified
- `pytest` is not installed here: the claims test ran on a small stand-in runner (`passed 8, failed 0`; removing a README tag or breaking an evidence path makes it fail). The demo script and quickstart commands were not run.
- Stale files that Task 4 deleted still exist in the repository copy I was given (zip files cannot delete). They contain old claims. To remove them, see the PowerShell block in the chat reply.
