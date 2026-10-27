# ML-002 runbook: finish Task 17 on your own machine

> **Superseded (R3 Task 14, 2026-10-28).** The run this page asks for was made as `baselines-v6`, not `baselines-v5`, after the
> lock changed; `baselines-v5` is left unedited as superseded history. Do not follow the `baselines-v5` commands below. Use
> `python scripts\repro.py verify baselines-v6`; after any later commit it prints one expected `FAIL code_revision`
> (see `docs/DEMO_CHECKLIST.md` and `docs/roadmap/task-reports/R3_TASK_4_REPORT.md`). The rest of this page is kept as history.

Why this exists: a run must carry the real git revision and be made on the machine that will verify it. The configs,
tests and docs in the Task 17 zip were produced and checked in a sandbox without git; the run directory `baselines-v5`
that two existing tests expect has to be created here. Apply Tasks 5 and 7 first.

Run from the repo root (`C:\Users\Lakshay\Desktop\data center\DigitalTwin-main`) in PowerShell with the virtual
environment active.

## R0. Apply and check the starting state
```powershell
Expand-Archive -Path "$HOME\Downloads\TwinGrid_Task17_retune-baselines.zip" -DestinationPath . -Force
git status
python -c "import json; print(json.load(open('configs/baselines/pid.json'))['tuner_version'])"
```
Expect `baselines-tuner/3`.

## R1. Create the new baselines run, then verify it (required)
```powershell
python -m src.baselines.cli run --run-id baselines-v5 --check-determinism
python -m src.baselines.cli verify baselines-v5
```
Expect `PASS baselines-v5`. The summary in `reports\runs\baselines-v5\REPORT.md` should match these sandbox values to about
six digits (mean test reward per episode): constant -36.3272, lookup -36.0675, pid -54.2422, rule -54.8517.
If it does not, stop and tell me before committing anything.

Verify straight after the run. The verifier compares the recorded git revision with the current one, so once you commit
(including the run directory itself) it reports a `code_revision` mismatch. That is how `baselines-v3` and `baselines-v4`
already behave.

## R2. Tests
```powershell
$env:JWT_SECRET_KEY = "ci-test-secret-not-for-production"; $env:ENVIRONMENT = "development"; $env:PYTHONHASHSEED = "0"
python -m pytest tests/test_baselines.py tests/test_pue_hard_constraint.py tests/test_repro_framework.py -rs
python -m pytest tests/test_recommendation_ranges.py tests/test_task5_hard_constraint_set.py tests/test_task19_optimizer_rules.py tests/test_task31_model_cards.py tests/test_task20_docs_consistency.py -rs
python -m ruff check .
```
`tests/test_baselines.py` has two tests that read `reports\runs\baselines-v5`; they pass only after R1.

## R3. Optional: regenerate the PPO re-run with your own environment
The zip ships `reports\policy_evaluation_physics1\rerun_t17` made in a sandbox (numpy 2.5.4, Python 3.12.3; the file records this).
To replace it with your own numbers (they should agree to about 1e-9, and the decision must be `C`):
```powershell
python -m src.policy_evaluation run --out reports/policy_evaluation_physics1/rerun_t17 --candidate-format numpy --candidates-dir models/candidates/ppo --model-id-prefix ppo-p1-e2-cd2345024
python -m pytest tests/test_task31_model_cards.py -rs
```
Do NOT run this with `--out reports/policy_evaluation_physics1`: the folder name `full_0fcafef9d28fd539` is the same and the
first run would be overwritten.
