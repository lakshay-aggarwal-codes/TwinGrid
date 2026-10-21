# Anomaly detector held-out evaluation: protocol (Task 18, ML-003)

**This file is hashed before any test scoring.** `PROTOCOL.sha256.json` holds its SHA-256 (line endings normalised to LF).
`python -m src.anomaly_eval final` refuses to run if the text changed after the hash was recorded, if the machine-readable
block below disagrees with `configs/anomaly/anomaly_v2.json`, or if the test split was already scored. Changing anything
here means a new protocol version, a new hash, and an explicit note in the report.

## 1. Question and what it can support

Does the autoencoder anomaly detector find injected faults better than a simple rolling z-score rule, on scenarios it was
never tuned on, measured per **event** (not per row), with the false-alarm rate stated per simulated day?

Scope: **synthetic injected anomalies only**, two fixed fault types (`leak`, `thermal`), produced by the same generator
family that produced the training data. A good result says nothing about real faults. A poor result is reported as poor.

## 2. Data

Dataset v2 from `scripts/make_datasets.py` (split id and scenario-set id are in the block below and are checked against the
dataset manifest). One scenario is a contiguous 14-day window at 5-minute cadence inside one city and one month block.

| Split | Scenarios | Planned events | Cells |
|---|---|---|---|
| train | 90 | 180 | 45 city x month-block cells |
| validation | 24 | 48 | 12 cells |
| test | 52 | 104 (52 `leak`, 52 `thermal`) | 26 cells: six cities absent from train/validation, month block D (Oct to Dec) absent from train/validation, workload regime `burst` absent from train/validation |

Splitting is **by whole scenario and by cell**, not by a single time cut. Consequences, stated plainly:

* No scenario is shared between splits. Every scenario is scored as an independent segment: detector windows, rolling
  statistics, alert episodes and detection windows never cross a scenario boundary.
* The detector trains on **normal windows of the train split only** (any window touching an injected row is excluded).
  The threshold is chosen on validation only. The test split is scored once.
* The protocol does **not** guarantee a minimum calendar gap between a train scenario and a validation or test scenario of
  the same city. The leakage a gap protects against (overlapping input windows) cannot occur here, because the longest
  look-back is 24 rows (2 hours) and no window crosses a scenario. That is a structural argument, not a measured gap.
* Inside a scenario, events stay at least 12 rows from either end and at least 24 rows apart.

## 3. Event types and counts

Each scenario carries exactly one `leak` (flow x2.5, pressure x0.4, 13 rows) and one `thermal` spike (outlet temperature
+8 to +15 C, 9 rows). The runner stops (`InsufficientEventsError`) below 30 events in validation or test, and reports a
per-type figure only for a type with at least 5 events. Both types have 24 (validation) and 52 (test) events.

## 4. Scorers

* **autoencoder**: `src.anomaly_detector.AnomalyDetector`, `seq_len` 12, the training settings and seed in the config
  (single training seed 0; seed-to-seed variation is **not** measured, see section 9). Score of a row = reconstruction error
  of the window ending at that row.
* **rolling_zscore** (baseline): the largest absolute feature z-score of a row against the preceding 24 rows (current row
  excluded), over the five features. First 24 rows of a scenario are not scored. Nothing is fitted; the window is fixed and
  never tuned. Formula and floor: `src.anomaly_eval.rolling_zscore_scores`.

Features for both: `water_flow_lpm`, `water_pressure_bar`, `server_outlet_temp_C`, `it_power_kw`, `humidity_pct`.

## 5. Threshold rule and caps (identical for both scorers)

Pick the threshold on **validation only**: maximise event recall subject to (a) false-alarm episodes per simulated day at
most the cap and (b) the fraction of rows that alert at most the row cap; ties go to the higher threshold. If no threshold
meets both, that scorer is **not scored on test** and the report says so; the caps are never relaxed.

Caps are the implementer's proposal until the owner sets `caps_status` to `preregistered` in the config. They are part of the
hashed block below; the runner refuses while `caps_status` is not `preregistered` or the config differs from this text.

An **alert episode** merges alerts separated by fewer than K = 3 non-alert rows. An event is **detected** if an alert falls in
`[start, end + 6 rows]`. A **false alarm** is an episode overlapping no detection window.

## 6. Metrics

On the test split, per scorer: event recall, event precision (episodes that overlap a detection window / all episodes),
**event F1** (harmonic mean of those two), false-alarm episodes per simulated day, detection delay (median and IQR, minutes,
over detected events), and event recall per event type. Row-level figures are diagnostic only and not used for any claim.

Intervals: **cluster bootstrap over test scenarios** (resample whole scenarios with replacement), 2000 replicates, seed
20261018, 95 % percentile interval. Wilson intervals for proportions are also in the metric core.

## 7. Primary comparison and decision rule

Primary metric: event F1, autoencoder minus rolling_zscore, with a **paired** bootstrap (same resampled scenarios for both).

* Interval entirely above 0: the autoencoder beat the baseline on this protocol.
* Interval entirely below 0: the baseline beat the autoencoder. This is reported as such.
* Interval includes 0: **no demonstrated advantage**. The model card then says the detector is not shown to beat a
  rolling z-score rule.

No other metric can overturn this rule after the fact.

## 8. Procedure and one-shot rule

1. Lock this file (`python -m src.anomaly_eval lock`). 2. Generate the dataset. 3. Optional: `validate` stage (never reads test).
4. `final --run-id <id>`: verifies the lock, fits both scorers, chooses thresholds on validation, writes
   `TEST_SPLIT_USED.json`, then reads the test split and scores each scorer once. A second run is refused while that marker exists;
   a crash after the marker still counts as a look.

## 9. Known limits (stated before results)

* Synthetic faults with fixed, strong signatures. A rolling z-score rule may already be near ceiling, in which case the
  comparison is decided by false alarms and delay, and the evaluation cannot show the detector is better on harder faults.
* A development smoke run of the baseline on the **validation** split of a scratch dataset built with synthetic weather and
  water-stress inputs was done while writing the code, before this file was locked. It informed this limit (the baseline
  detected every validation event there) and nothing else. **The test split was not read.**
* Single training seed for the autoencoder. A seed sweep would be a new protocol version.
* The shipped model artifact predates this protocol. Whether the shipped artifact or a retrained candidate is scored is stated
  in the report (the runner trains a fresh candidate from the protocol's config).
* If the dataset is built with synthetic weather or water-stress inputs, the report says so on its first lines.

## 10. Machine-readable pre-registration (hashed with the file)

<!-- PREREG:BEGIN -->
```json
{
  "schema": 1,
  "dataset_split_id": "9750a1bae82e251b0bc59c7ef2cb7bc9b17d89f4050d7eff156a70484d57de43",
  "dataset_scenario_set_id": "aa8fbfcb6fe3d8d4885f5757c7a1b46237dd18bdfe98e4b92b0c8c8e1d45b726",
  "cadence_s": 300,
  "seq_len": 12,
  "seed": 0,
  "k_gap": 3,
  "tolerance_rows": 6,
  "false_alarm_cap_per_day": 2.0,
  "max_alert_row_fraction": 0.05,
  "baseline": {"name": "rolling_zscore", "window_rows": 24},
  "bootstrap": {"method": "cluster over scenarios", "reps": 2000, "seed": 20261018, "level": 0.95},
  "primary_metric": "event_f1",
  "primary_scorer": "autoencoder"
}
```
<!-- PREREG:END -->
