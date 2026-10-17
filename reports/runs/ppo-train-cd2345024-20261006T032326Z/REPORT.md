# PPO candidate generation (T29): lineage record, no evaluation

Experiment: `ppo_training`
Schema: `twingrid-results/1`
Seeds: 0, 1, 2, 3, 4

Generated from `results.json` by `src/repro/report.py`; nothing in this file is typed by hand.

## Summary

| metric | value |
|---|---|
| all_status_candidate | yes |
| claim | candidates with recorded lineage; no performance or safety statement |
| max_numpy_vs_sb3_abs_diff | 8.9407e-08 |
| n_candidates | 5 |
| numpy_tolerance | 1e-05 |

## Registered candidates

| model_id | seed | status | policy_npz_sha256 | training_config_sha256 | numpy_vs_sb3_max_abs_diff | total_timesteps |
|---|---|---|---|---|---|---|
| ppo-p1-e2-cd2345024-s0 | 0 | candidate | da3d97a0a6f6a80c29ae2635feb0767cf92ce875011bd4ca5d90fbbed5465045 | 98ea7f1a78ad89fb70b1b505a5cd358b095182e9c2aef5c78a5a687c12512745 | 8.9407e-08 | 98304 |
| ppo-p1-e2-cd2345024-s1 | 1 | candidate | c1c478ee39bc36847a5a88872ce139e863a17bc42a5dbfae4313f0110535fe98 | 4de8a2557a02bd31f7ec37d8d254c5bdc809fbb805f321f099ecc75959498eb8 | 3.72529e-08 | 98304 |
| ppo-p1-e2-cd2345024-s2 | 2 | candidate | 451cce191905568305f7a2b4997e1b972c5934928718649b7d0dbfe28965e94f | 7cd7036f5f515d4bd9f1309c44924f6f6988fb51decd7ff24ed66dd90fb6f640 | 5.96046e-08 | 98304 |
| ppo-p1-e2-cd2345024-s3 | 3 | candidate | 6f670d855ef74d91d328a29c089230bf021cb4fa009d2dfa63ccc58b6d022a8c | c3a4149e38d6aed9deb1213e8acf95ede8a884ea85d5a92e062a3953521567ee | 8.9407e-08 | 98304 |
| ppo-p1-e2-cd2345024-s4 | 4 | candidate | 70bb33427d1cd54cc72cc02e467caa2aebc94319aa3bb1aae361f058c36f2240 | 873231aa1fb8f472d2aa704df2a8cf2b58d712547451260ebb891538d3293599 | 2.98023e-08 | 98304 |

Full precision: `tables/candidates.csv`

## Notes

- Candidate generation only: no policy here was evaluated, promoted or compared with a baseline.
- The SB3 zips under artifacts_training/ are training-only; the API serves the NumPy export of a promoted policy.
