# Task 20 (roadmap): documentation consistency sweep

(Named `Task20_docs_sweep_REPORT.md`: `Task20_REPORT.md` is the earlier onboarding-tour task.)

## Inputs and evidence labels
- **Verified local source:** the uploaded zip (read and edited), `docs/tasks/Task4*`, `Task6*`, `Task9*` reports, `src/policy_evaluation.py`.
- **Owner-reported:** the Task 9 run (`outcome: C`) and its `REPORT.md`, pasted into the chat. `results.json` itself was not uploaded.
- **Not seen:** `reports/policy_evaluation_physics1/full_0fcafef9d28fd539/results.json` (the card's `EVIDENCE` lines and the new test read it on your machine).

## Decisions
1. **Outcome C is reported as it came out.** Card, claims row C-08, README, judges pack, limitations and `ML_DOCUMENTATION.md` now say: five candidates scored once, outcome C, claim allowed none, a fixed 22.75 C closed-loop setting beat every seed. The mixed result against the rule baseline is stated too (selected seed ahead across scenarios, not in every family, seed-level interval includes zero). Safety counters were zero for every policy, so the comparison is about reward, water and energy.
2. **Patents: no filing confirmed, so renamed neutrally** (the roadmap default). 28 lines in 5 files under `src/` and `config.yaml`, `DEPLOYMENT.md`, `data/external/REGISTER.json` reworded ("Design:", "drought-override rule"). `LICENSE` (GPL text) untouched. The serialised key `patent_objective` is kept (saved `models/optimizer/config.json` and `tests/test_t23_carbon_aqueduct_contracts.py` read it); it is commented as a label. If a real filing exists, send its number and the wording can be tied to it.
3. **Stale or wrong statements fixed:** `src/rl/env.py` comments gave the chilled-water range as 5-15 C (it is 16-25 C under physics 1); `src/optimizer.py` docstring said C = cooling power (it is the carbon term); `DEPLOYMENT.md` said Railway production was "live today" and gave a URL (no deployment is confirmed anywhere, README C-34); `ML_DOCUMENTATION.md` "Real-world validation" / "validated" wording for the NAB check; UI string "validated on a proxy dataset" in `SustainabilityTab.tsx`.
4. **Limitations section** added to the README (simulated, lumped, assumed carbon, no calibration, models) as ledger row C-35; `LIMITATIONS.md` gets the same statement.

## Files
MODIFY `src/digital_twin.py`, `src/optimizer.py`, `src/pinn.py`, `src/rl/env.py`, `src/ingestion/README.md` (comments and docstrings only, no logic), `config.yaml` (comments), `data/external/REGISTER.json` (one string), `DEPLOYMENT.md`, `README.md`, `ML_DOCUMENTATION.md`, `twin-stream-insight-main/ML_DOCUMENTATION.md`, `docs/CLAIMS.md`, `docs/JUDGES.md`, `docs/model_cards/ppo_optimizer.md`, `docs/model_cards/LIMITATIONS.md`, `twin-stream-insight-main/src/components/SustainabilityTab.tsx` (one string).
CREATE `tests/test_task20_docs_consistency.py`, this report.

## Tests
- **Sandbox (Linux, Python 3.12, no pytest/ruff/torch/node):** a minimal runner executed the 7 new tests, all of `tests/test_task33_claims.py` and `tests/test_task31_model_cards.py`: all passed. The result-dependent tests ran against a temporary stand-in `results.json` built from the rounded numbers in your pasted `REPORT.md`; it was deleted and is NOT in the ZIP, so that run proves the test logic and doc wording, not your real file. `scripts/check_register.py`: OK. Edited Python compiles.
- **Not run:** the real `results.json`, pytest itself, the fixture-based tests (`test_external_register.py`, `test_task11_data_truth.py`, `test_task9_api_reference.py`, `test_task18_explain_passport.py`), ruff, any frontend test or build.
- The new result tests skip (never pass) if the run directory is missing.

## Open items I did not change (need a decision)
- **API/Model Passport still serve the older legacy-physics report.** `api/services/evaluation_service.py` reads only `reports/policy_evaluation/`, so the Passport and Evaluation screen say `NOT_EVALUATED` while the physics-1 run says `C`. Fixing it changes a frozen contract (G-EVAL) and fixtures; it needs its own task.
- `models/registry.json` v2 entries still say "not evaluated: evaluation and promotion are T30". Registry edits are a governance step; the card and ledger say so.
- The anomaly-detector artifact still predates the validation-only threshold fix (Task 12 pass 1); its card is unchanged.
- Task 13 (physics v2 in the RL env) is not justified by this result; ADR 008 already warned against it before a PPO result existed.

## Remaining risks
- Commit `reports/policy_evaluation_physics1/full_0fcafef9d28fd539/` (from your machine) in the same commit, or `test_every_evidence_path_exists` fails.
- Docs now describe one physics-1 run, one recipe, five seeds, assumed carbon. Nothing here is a claim about a real facility.
