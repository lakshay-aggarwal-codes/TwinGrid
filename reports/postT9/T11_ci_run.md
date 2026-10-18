# T11 / Task 7: type-check ratchet record

| Field | Value |
|---|---|
| Checker | pyrefly 0.64.1 (now pinned `==` in `requirements-dev.txt`) |
| Config | `pyrefly.toml` (Python 3.12) |
| Command | `pyrefly check --output-format=json` (as in the `types` job) |
| Environment | owner's Windows machine, project `.venv` (NOT the Linux CI image) |
| Date | 2026-10-18 |
| Result | **881 errors** (36 suppressed, 239 warnings not counted), identical on 2 consecutive runs |
| Ceiling set | `PYREFLY_ERROR_CEILING: "881"` in `.github/workflows/ci.yml` |

Breakdown (local): unsupported-operation 410, bad-argument-type 240, missing-attribute 172, not-iterable 14,
bad-return 10, bad-assignment 9, bad-index 6, bad-typed-dict-key 5, missing-import 4, others 11.
Largest files: tests/test_datasets_v2.py 185, src/data_pipeline.py 123, tests/test_baselines.py 41,
tests/test_artifact_gate.py 31, tests/test_physics_v2.py 28.

## Not yet observed
- The count on GitHub's Linux runner with `requirements.lock` installed. If it differs, record it below with the run URL.
  Differences can come from installed packages (torch/TensorFlow stubs, resolved imports), not from the code.

| Date | Source | Count | Run URL | Note |
|---|---|---|---|---|
| 2026-10-18 | Windows .venv, pyrefly 0.64.1 | 881 | n/a | baseline |

## Ratchet rule
1. The ceiling may only go down. When the `types` job prints "Type errors fell", lower the ceiling to that number in the same PR.
2. Exception, once: if the first Linux CI run prints a higher count than the Windows baseline, set the ceiling to that
   number and add a row above. After that the ceiling never rises.
3. Changing the pinned pyrefly version re-baselines the count; do it in its own PR and add a row above.
4. Do not hide errors with `# pyrefly: ignore` or by widening `project-excludes` to move the number; that defeats the gate.

## Other CI recorded facts (Task 7)
- `frontend-e2e` and `frontend-contract` keep `continue-on-error: true`: no green-run log was supplied, and
  `frontend-contract` additionally requires committed real fixtures. Remove the flag only after one recorded green run each.
