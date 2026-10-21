# Runbook: run the held-out anomaly evaluation (Task 18)

Needs **TensorFlow** (the autoencoder). Everything else is NumPy and pandas. Run once; the test split is scored once, ever.
Not covered by the protocol hash, so it can be corrected without invalidating anything.

1. **Confirm the caps.** Read the numbers in `reports/anomaly_eval/PROTOCOL.md` section 5 and 10 (K 3, 2 false-alarm episodes
   per day, 5 % of rows may alert, 6-row tolerance). 2 false alarms a day is acceptable for a simulator, too many for a real
   operator. To accept them set `"caps_status": "preregistered"` in `configs/anomaly/anomaly_v2.json`. To change them, edit the
   values in the protocol's JSON block **and** the config, then re-lock (step 2). Do this before any test scoring.
2. **Lock.** `python -m src.anomaly_eval lock` rewrites `reports/anomaly_eval/PROTOCOL.sha256.json`. Skip it if you changed nothing:
   the committed hash already matches. It refuses once `TEST_SPLIT_USED.json` exists.
3. **Dataset.** `python scripts/make_datasets.py --plan-only` (expect at least 30 events in val and test). Then either place the real
   cleaned inputs in `data/cleaned/` and run `python scripts/make_datasets.py`, or add `--allow-synthetic-weather
   --allow-synthetic-water-stress` (the result then says synthetic inputs were used). Note the printed dataset id.
4. **Optional dry run on validation only** (never reads test):
   `python -m src.anomaly_eval validate --dataset-dir data/datasets/<id> --allow-synthetic-inputs`
   (add `--no-detector` to run only the baseline without TensorFlow).
5. **The one run.**
   `python -m src.anomaly_eval final --dataset-dir data/datasets/<id> --run-id t18-<date> [--allow-synthetic-inputs]`
   It verifies the protocol hash, the config, the dataset manifest and ids, fits both scorers, chooses thresholds on validation, writes
   `TEST_SPLIT_USED.json`, scores test once, and writes `reports/anomaly_eval/runs/<run-id>/results.json` and `REPORT.md`.
6. **After it ran:** commit `TEST_SPLIT_USED.json` and the run folder. Copy the conclusion sentence into the model card and
   `docs/CLAIMS.md` C-07 (and the model passport text), whatever it says. If the detector did not beat the baseline, say so.
7. **Verify the machinery any time:** `pytest tests/test_anomaly_eval.py tests/test_anomaly_eval_t18.py -q`.

If a run crashes after `TEST_SPLIT_USED.json` was written, the test split counts as looked at. Do not delete the marker to run
again; record the failure, fix the cause, and write a new protocol version with a new dataset or a fresh held-out set.
