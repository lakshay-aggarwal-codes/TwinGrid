# Product Roadmap (evidence-first)

Ordering principle: restore trust in the numbers, then earn the claims, then add features.

## 1. Immediate correctness (days)
1. Re-register a physics-1 protocol and re-tune baselines (TG-A-07). Acceptance: `tests/test_baselines.py` green on your machine; new run verifies. Value: unblocks every comparison.
2. Fix or delete `DigitalTwinOptimized` (TG-A-05). Acceptance: parity test passes at 1e-6, or module removed and xfail deleted.
3. Record pyrefly ceiling; get CI green (TG-A-08).
4. Decide on amendment A1 and say so in the viva/report.

## 2. Short-term reliability
- Count PUE violations per step and add to the hard-constraint set with a frontend contract update (TG-A-12).
- Run the full backend test suite and the frontend build/E2E in a clean environment and keep the log (none exists in this audit).

## 3. UI/UX (only after 1-2)
- Label every evaluation view with `physics_version_executed`, carbon `is_real`, and "simulated".
- Add real screenshots and a 2-4 minute recorded demo of: simulate -> compare safe controllers -> export report.
- Accessibility sign-off (not assessed here).

## 4. Scientific validation
- Forecaster: add persistence baseline on the same split. Anomaly: select threshold on validation, score once on test, report event-level metrics. (Unverified claims from the original audit; check the model cards first.)
- Evaluate the five PPO candidates against rule and best constant under the physics-1 protocol with the corrected gate. If PPO loses, report that.
- Real carbon time series (TG-A-11).

## 5. New capabilities (only if 1-4 are done)
Highest value per effort: experiment comparison view (baseline vs candidate, identical scenarios, violations shown first); reproducible report export tied to a run id. Defer fleet, rack-level and ML additions: the physics is a lumped single-room model and cannot support rack-level claims.

## 6. Data-dependent / research
Calibration against a real or licensed facility dataset; physics v2 support in the RL env (action range, observation schema, tuned baselines, retrained policies); sensitivity and uncertainty analysis.
