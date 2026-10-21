# Task 18 — ML-003 Anomaly detector held-out evaluation          Status: PARTIAL (protocol + code + runbook delivered; NO result)
Base: `TwinGrid-main.zip` as uploaded     Date: 2026-10-21
Environment: Linux sandbox, Python 3, numpy + pandas. **TensorFlow is not installed**, pytest and ruff are not installed, no network.

## Summary
The evaluation cannot be scored here because the detector needs TensorFlow. What is delivered: a protocol written first and hashed before any test scoring; a rolling z-score baseline, cluster-bootstrap intervals, event-level F1, a paired comparison with a pre-registered decision rule, and a one-shot run driver in `src/anomaly_eval.py`; a runbook; 25 new tests; and an honest update of the model card and ledger row C-07. **No held-out number exists, and none is claimed.**

## Acceptance checklist
| Criterion | Result | Evidence |
|---|---|---|
| Protocol written first, hash recorded before results | met | `reports/anomaly_eval/PROTOCOL.md`, `PROTOCOL.sha256.json` (sha256 `16af3f2e…ca57`, recorded before any test scoring); `test_the_committed_protocol_hash_matches_the_committed_text_and_the_config` fails if the text or config drift |
| Threshold on validation only | met (inherited + tested) | `select_threshold_segments` refuses any other split; driver fits and thresholds before reading test |
| One-shot test scoring | met in code | `TEST_SPLIT_USED.json` is written BEFORE the test file is read and blocks any later run; test asserts the marker exists when the first test scenario is scored (mutation-checked: moving the marker after the read makes it fail) |
| Event-level P/R/F1, false alarms per day, delay median/IQR, per type, bootstrap CIs, vs baseline | met in code, not run on the real detector | `bootstrap_metrics`, `paired_bootstrap_difference`, `RollingZScoreScorer`, `render_comparison`; point estimates equal the existing metric core (tested) |
| Honest conclusion even if poor | met | decision rule is in the hashed protocol and in `conclusion()`; "includes 0" gives "NO DEMONSTRATED ADVANTAGE"; "baseline beat detector" is stated as such |
| Old F1 kept as preliminary, in-sample; ledger/card consistent | met | card section renamed "Preliminary figures (in-sample…)"; C-07 rewritten; README and JUDGES wording already matched |
| An actual held-out result | **NOT MET (blocked)** | needs TensorFlow, a generated dataset and the owner's decision on the caps |

## Changed files
- `src/anomaly_eval.py` — appended section "T18" (about 450 lines) plus a docstring note and imports; **no existing function changed** (existing 87 tests still pass under a shim).
- `reports/anomaly_eval/PROTOCOL.md`, `PROTOCOL.sha256.json`, `RUNBOOK.md` — new.
- `tests/test_anomaly_eval_t18.py` — new, 25 tests.
- `docs/model_cards/anomaly_detector.md` — heading and bullets (no new numbers outside code spans, so the card's number-tracing test still passes).
- `docs/CLAIMS.md` — C-07 row only.
- `docs/roadmap/task-reports/TASK_18_REPORT.md` — this report.

## What the protocol fixes (summary)
Dataset v2 (split id and scenario-set id are pinned and checked against the manifest); splits by whole scenario and cell, 52 test scenarios with 104 events (52 per type), 24 validation scenarios with 48 events; two scorers, the autoencoder and a rolling z-score (24-row trailing window, five features, nothing fitted); the same threshold rule and caps for both; event recall, precision, F1, false alarms per simulated day, delay, per type; 2000-replicate cluster bootstrap over scenarios (seed 20261018); primary comparison = paired event-F1 difference.

## Things you should know
1. **The caps are still the implementer's proposal** (`caps_status: PROPOSED_UNCONFIRMED`). The runner refuses until you set `preregistered`; changing the numbers means editing the protocol and re-locking before the run. My view stands from the earlier report: 2 false alarms per day is acceptable only as a simulator cap.
2. **No calendar gap between splits is guaranteed.** Splits are by whole scenario and city/month-block cell, not one time cut. The protocol says so and argues why window leakage cannot happen (longest look-back is 24 rows; no window crosses a scenario); that is a structural argument, not a measured gap.
3. **A development smoke run preceded the lock** and is disclosed in the protocol: the baseline alone was run on the **validation** split of a scratch dataset built with synthetic weather/water-stress inputs. It detected all 48 validation events (about 1.1 false-alarm episodes per day, event precision about 0.12, median delay 0 minutes). It informed one thing: a likely ceiling effect, written into the protocol limits and card. The **test split was never read.** These validation numbers are not a result and are not in the card.
4. Single training seed for the autoencoder (seed variation not measured); a seed sweep would be a new protocol version.
5. The runner trains a **fresh candidate** from the config; it does not score the shipped, legacy-waiver artifact.

## Commands run
- `python3 -m py_compile` on all new/changed Python.
- 25 new tests + 87 existing `test_anomaly_eval.py` + 5 model-card + 8 claims tests, all passing under a small pytest-shim runner (not real pytest). Two deliberate mutations (marker written after the test read; unpaired bootstrap) each made one test fail.
- `python scripts/make_datasets.py --plan-only` (104/48/180 events) and a full synthetic-input generation in a scratch copy (20 s) to exercise the loader; `run_validation` with the baseline on that scratch dataset, validation only.

## Pre-existing failures observed
None.

## Not run / blocked
- `pytest tests/test_anomaly_eval.py tests/test_anomaly_eval_t18.py -q` under real pytest.
- **`ruff format src/anomaly_eval.py tests/test_anomaly_eval_t18.py` then `ruff check .`**: CI runs `ruff format --check .`. About 40 lines exceed 120 characters, so CI will fail until the formatter has been run once. Behaviour does not change.
- The whole real run (TensorFlow detector, real or synthetic-input dataset, `final`), `tests/test_anomaly_detector.py`, `tests/test_train_anomaly.py`.
- `AutoencoderScorer` is written against `AnomalyDetector`'s API as `scripts/train_anomaly.py` uses it but has never executed.

## Requested cross-task changes
- Model Passport text (`api/plugins/explainability.py`, not owned) and the registry entry's `evaluation_ref`: update after the run; they were not touched because there is no result.
- Task 32 (audit docs): `docs/audit/TwinGrid_Final_Assessment.md` still says no event-level evaluation has been run, which remains true; revisit after the run.

## New limitations or risks
- The `final` run is irreversible by design (marker). A crash after the marker means the test split counts as used.
- `scripts/train_anomaly.py` also evaluates the test split once in its own run; running both on the same dataset spends the split twice. Use `src.anomaly_eval final` for this evaluation and do not run train_anomaly's test step on that dataset.

## Next tasks unblocked
Task 19 (forecaster) can reuse the same pattern (protocol first, hash, one-shot marker, paired bootstrap).
