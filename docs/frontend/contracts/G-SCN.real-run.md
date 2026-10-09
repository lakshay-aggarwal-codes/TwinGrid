# G-SCN Real Run Verification Record

- **Git HEAD**: `5e75ad7a52574d663bed8b7a1ffad7b7ec4bf03e`
- **Physics Registry Resolution**: RECONSTRUCTED path used (0 matching ZIP entries found across Downloads, Desktop, Documents).
  - *Note*: Verification was run against a reconstructed `src/versions.py`, so this is not confirmation against the original unmodified backend artifact.
  - *Assumptions Made*:
    1. `PHYSICS_V2 = "2"` based on `tests/test_physics_v2.py` and `src/digital_twin.py`.
    2. `KNOWN_PHYSICS_VERSIONS = (LEGACY_PHYSICS_VERSION, PHYSICS_V1, PHYSICS_V2)`.
    3. `physics_identity(version, params=None)` returns `{"physics_version": version, "physics_params_hash": None}` for versions != "2", and raises `PhysicsVersionError` if `params` is provided for non-v2 or missing/lacks `params_hash()` for v2.
    4. `assert_same_physics_identity(*identities)` validates uniform `physics_version` and non-empty matching `physics_params_hash` across identities.

## Step Summary

| Step | Description | Status | Observed Value / Details |
|---|---|---|---|
| 0 | Preflight git status & cleanup | PASS | Cleaned stray JSON files; HEAD `5e75ad7a52574d663bed8b7a1ffad7b7ec4bf03e` |
| 1 | Fix missing physics-v2 registry | PASS (Reconstructed) | Reconstructed `src/versions.py`; `python -c "import src.digital_twin"` succeeded |
| 2 | Apply BC-09 scenario registry | PASS | Extracted 6 files from `BC09_backend_scenario_registry.zip`; scenario routes registered in `api/main.py` |
| 3 | Place G-SCN confirmation record | PASS | Extracted from `BC09_G-SCN_confirmation_record.zip`; contract files present |
| 4 | Fix requirements.lock encoding & hashes | PASS | SHA-256 hashes generated from PyPI; verified with `tests/test_lockfile.py` |
| 5 | Environment configuration (.env) | PASS | `.env` present and gitignored; `ENVIRONMENT=development`; hex credentials set |
| 6 | Docker build & up | FAIL | `docker compose build` succeeded, but `backend` container failed to boot during startup `alembic upgrade head` due to duplicate revisions committed in `alembic/versions` |
| 7 | Authentication | NOT RUN | Stopped at Step 6 per instructions |
| 8 | Scenario & Whatif captures diff | NOT RUN | Stopped at Step 6 per instructions |
| 9 | Pytest test execution | NOT RUN | Stopped at Step 6 per instructions |

## Files Changed

- `src/versions.py` (Modified)
- `api/main.py` (Modified)
- `api/routes/digital_twin_routes.py` (Modified)
- `requirements.lock` (Modified)
- `api/routes/scenario_routes.py` (Added / Untracked)
- `api/services/scenario_registry.py` (Added / Untracked)
- `tests/test_scenarios.py` (Added / Untracked)
- `docs/frontend/contracts/G-SCN.md` (Added / Untracked)
- `docs/frontend/contracts/G-SCN.capture-scenarios.json` (Added / Untracked)
- `docs/frontend/contracts/G-SCN.capture-whatif-heat-wave.json` (Added / Untracked)
- `docs/frontend/contracts/G-SCN.real-run.md` (Added / Untracked)
