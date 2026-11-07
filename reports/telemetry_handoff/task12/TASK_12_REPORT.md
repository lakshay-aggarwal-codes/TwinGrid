# Task 12 report

```text
Task number and title: Task 12 - Deterministic cleaning, ledger and time handling (Danish AAU v5)
Status: Ready for review as CODE + SYNTHETIC TESTS only. The real-file numbers (Tier 1 conflict-missing count, 50% air-speed cadence gap, the full Task 4 / Task 6 comparison) are NOT produced yet: they need the owner-run script below. The owner alone approves.
Base commit and branch: 26f86656dc174c754e451aec16125ae3edb7bd17 as recorded by the owner in task12_base_commit.txt. The branch is not recorded in the supplied zip and the zip has no .git, so neither is verified here. Owner git status listed untracked scratch items (.cp9_backup, evidence_tools, ...); none were used except research/danish_aau/evidence_tools being present in the zip.
Inputs checked: protocol lock verify -> 1.0.0, 0ff45216...47098 (approved Lakshya Aggarwal 2026-11-05). TASK_08_CONTRACT.md (LF) 194869a4... = approved value. TASK_07_ADR.md 8f13794c... and TASK_09_ADR.md 47ae669e... match the Completed Context.
Files read: Master Handoff Task 12; Tasks 2-8 Completed Context; Context 8B/8C (Tasks 9, 10); TASK_11_REPORT; TASK_08_CONTRACT and contract/telemetry_contract.py (validator rules); TASK_07_ADR; TASK_09_ADR (sections 3, 5, 6, 8, 10, 14); protocol_v1.toml, protocol/{protocol,rules}.py; adapter/{schema,source,reader,local_check}.py; evaluation/data_layer/{reader,time_index}.py; screening/run_task6_screen.py and reports/task6_screen/task6_screen_output.txt; owner JSONs task11_local_check / task11_rerun / task11_integrity.
Files created (new paths only): research/danish_aau/cleaning/{__init__,catalogue,tier1,config,errors,resolve,flags,ledger,l1,cadence,reference,local_run}.py ; research/danish_aau/tests/cleaning/{conftest,test_cleaning}.py ; this report (reports/telemetry_handoff/task12/TASK_12_REPORT.md, the only file outside the two owned folders, and it is a report). Modified/deleted: none. No protocol, adapter, contract, config or frozen path touched.
Design: reuse, not a second reader. clean_file() streams the Task 11 AdapterReader (all 51 columns, raw text kept). Rows whose timestamp is unique are converted in bulk (float -> ticks, with an exact Decimal ROUND_HALF_EVEN re-round of the SOURCE TEXT for near-ties); every repeated-timestamp group goes through the protocol's own rules.resolve_group, so the conflict logic is the locked reference implementation. clean_rows() is a reference path (every group through resolve_group); a test proves both paths give identical digests for chunk sizes 2, 3, 5 and default. No timezone, no UTC, no resampling, no imputation, no interpolation; seconds are counted on the naive label only.
Decisions made / proposals for the owner: see "Owner decisions" below (Q1-Q7). Nothing in the locked protocol or the approved contract is changed.
Evidence (SHA-256, CR-stripped, first 16 hex): __init__ 7787dad5a52f1b47; cadence ba9cc234a72959f2; catalogue 1c185fd8200edfc8; config d8ebd220cd2caadb; errors 79ca776d1fa986e0; flags 8f4b22b398866928; l1 153f36fa40fc2455; ledger f0cc9671da049b03; local_run d7321e003c1a18df; reference b85bb7e5772b9c2b; resolve f46c54999f186c3d; tier1 484f8a9c2c520e9b; tests/conftest e4a9ed812406fe7b; tests/test_cleaning 56e8d7f0af037bea. cleaning_code_sha256 (all .py of the package, LF) 2f12f7c764cd462d (also written to every L1 manifest and to the local-run JSON).
Commands executed and exact results (agent sandbox: Python 3.12.3, numpy 2.5.4, pandas 3.0.6, pytest 9.2.0; NOT the owner's venv):
  python -m research.danish_aau.protocol verify -> OK 0ff45216...
  pytest research/danish_aau/tests/cleaning -> 37 passed
  pytest cleaning + protocol + contract + adapter -> 207 passed, 1 failed (adapter test_schema_matches_task4_profile_and_manifest: needs docs/datasets/danish-server-room-v5/manifest.json, which is not in the supplied zip; environmental, not a code fault)
  ruff check / ruff format on the new paths -> clean
  Mutation controls (each reverted afterwards; package diff vs backup empty): disabling the Decimal near-tie fallback -> 5 tests fail; clipping instead of flagging out-of-range -> 2 fail; imputing a tie value -> 10 fail.
  Timing (synthetic, not real data): 200,100 rows x 51 columns: index 8 s, clean 10 s, peak RSS about 0.8 GB. Real-file time and memory are NOT measured.
  Not run: the evaluation suite (the zip lacks src/repro/canonical.py and docs/, so 112 tests fail for that reason in my sandbox), backend/frontend suites (untouched).
Tests (37, synthetic only; year-2000 timestamps, patterned values): catalogue closed/unique/contract-shaped; Tier 1 = 40 columns = Task 6 REGISTER classes R+P = adapter columns minus the 11 cooling/room probes; vector ticks == Decimal ticks on 4,500+ strings incl. exact ties; half-even cases; exact duplicate keeps the value and the lowest row is bookkeeping only; tie -> missing, never imputed, other cells survive; no majority vote; groups of size 3 and 74; blank never conflicts, all-blank -> blank_cell; tie only outside Tier 1 counted separately; input order never matters (8 shuffles identical digest); typed refusals; range flag keeps the value (never clips) and marks the row; conflict dispositions never overwritten; flatline off by default, gap and blank break runs, out_of_range has priority, report never applies; ledger reconciles, validates against contract validate_ledger_entry, tampering detected; cadence profile; reference tables internally consistent; file path == reference path for 4 chunk sizes incl. near-ties (1.015 -> 102, where plain float rounding gives 101); read-only/repeatable; non-numeric cell refused; L1 byte-identical on rerun, chunking and shuffled input; L1 format, no local paths, no UTC text; L1 tamper detection; observation rows obey the contract state/reason/disposition rules; local script on a full 16-file synthetic directory incl. period cleaning and rerun digests.
Data/licence/privacy limitations: no raw or row-level data was available to the agent; fixtures are synthetic. The local script writes aggregates only (counts, per-column tie counts, timestamp TEXT of large steps). Licence unchanged (local-only).
Open blockers and exact owner action: (1) run the local script (command below) and return task12_local_run.json (aggregates only); (2) answer Q1-Q7; (3) commit the two new folders and this report by name (do not `git add .`).
Dependencies now unlocked (do not start them): none are unlocked until the real-file numbers are returned and the owner accepts Q1-Q7. Task 13 (identity mapping) does not depend on this task; Task 14 and Task 15 need the numbers and the L1 format.
```

## 1. First step: adapter profile vs the Task 4 table

Compared from the owner's task11_local_check / rerun / integrity JSONs (aggregates). The three JSONs agree with each other.

| File | Rows | First / last timestamp text | Rows in repeated groups (Task 4 groups + extra rows) | Result |
|---|---|---|---|---|
| temperature_power (full) | 1,371,363 | 2024-09-16 16:58:30 / 2024-10-02 13:53:02 | 1,074 (499 + 575) | equal |
| idle_1 | 58,202 | 2024-09-16 16:59:59 / 2024-09-17 09:10:00 | 0 | equal |
| 25 % | 90,902 | 2024-09-17 09:40:00 / 2024-09-18 10:55:00 | 92 (46 + 46) | equal |
| 50 % | 77,102 | 2024-09-18 11:25:00 / 2024-09-19 08:50:00 | 88 (44 + 44) | equal |
| 75 % | 88,261 | 2024-09-19 09:20:00 / 2024-09-20 09:51:00 | 0 | equal |
| 100 % | 258,123 | 2024-09-20 10:21:00 / 2024-09-23 10:03:00 | 156 (78 + 78) | equal |
| idle_2 | 789,610 | 2024-09-23 10:33:00 / 2024-10-02 13:53:02 | 580 (290 + 290) | equal |
| surrounding | 1,526 | 2024-09-16 16:45:00 / 2024-10-02 14:00:00 | 0 | equal |
| ventilation | 4,576 | 2024-09-16 16:45:00 / 2024-10-02 14:05:00 | 0 | equal |
| air-speed, 7 files | 5,822 ... 137,027 | see below | 0 | rows inside the Task 4 range; 0 repeats |

**Differences: none** in anything Task 4 states numerically. Two limits of this comparison:
- The adapter JSON reports only the number of rows inside repeated groups, so the Task 4 split (groups vs extra rows) is verified only as their sum. The new script computes both numbers separately.
- Task 4 gives the air-speed files only as a row range and "same span". Observed spans (informational, not a difference): air_speed 2024-09-16 16:58:49 -> 2024-10-02 13:55:16 (the 1 s file ends at 13:53:02); idle_1 16:59:59 -> 09:10:10; 25 % 09:40:00 -> 10:55:01; 50 % 11:25:01 -> 08:50:05; 75 % 09:19:55 -> 09:51:07; 100 % 10:20:57 -> 10:03:02; idle_2 10:33:02 -> 13:53:06. The air-speed spans overlap the temperature/power spans but are not identical to them.

## 2. Tier 1 conflict-missing count (what Task 15 will verify against)

**Not produced: it needs the raw files.** The script computes it in one pass and returns, for the full file: `tier1.cells_made_missing_by_tie` (the number), the split rack probes vs power, the per-column counts for the 40 columns, `groups_with_tier1_ties`, `groups_with_ties_only_outside_tier1`, and `all_51_minus_tier1_ties`.

What Task 15 should verify (definitions fixed here):
- stored cells = 40 x `unique_seconds` (reference: 40 x 1,370,788 = 54,831,520, Task 9 estimate);
- missing cells with reason `conflict_unresolved_tie` = `tier1.cells_made_missing_by_tie`;
- missing cells with reason `blank_cell` = 0 (Task 4 and Task 6: no blanks in the 51 columns);
- observed cells = stored cells - missing cells; flagged cells = 0 with the default (flag-free) configuration.

Cross-checks the same run performs (all 51 columns, against Task 6): 1,371,363 raw rows; 1,370,788 unique seconds; retained 1,370,289; exact_duplicate 0; conflict_cell_missing 1,074 rows; group sizes {2: 497, 6: 1, 74: 1}; 10,602 cells made missing; 0 blank cells; 7,032 near-tie cells re-rounded (the last is informational: it depends on the float parser). Any mismatch is listed in `task6_differences`. The Tier 1 number is by construction at most 10,602, and 10,602 minus it is the number of tie cells in the 11 cooling/room columns.

## 3. Reason-code catalogue (proposal)

| Code | Used for | Status | Meaning | v5 expectation |
|---|---|---|---|---|
| `conflict_unresolved_tie` | record missing; ledger | active | Locked protocol tie reason: conflicting cell, no documented authority field. observed=false. | Tier 1 count from the script |
| `blank_cell` | record missing | active | Every row of the group is blank for that cell. A blank never conflicts with a value. | 0 in the 51 columns |
| `out_of_range` | record flagged; ledger | needs owner | Outside owner-supplied limits. Flagged, value kept, never clipped. No limits exist (Task 4 ranges are descriptive), so NOT evaluated by default. | 0 |
| `flatline_run` | record flagged; ledger | needs owner | Cell in a run of >= N identical values at consecutive stored seconds (step <= protocol gap step 3 s). Applied only when switched on; N defaults to the protocol screening value 10. | reported, not applied |
| `source_authority_rule` | ledger | reserved | Conflict resolved by a documented authority field. authority_fields is empty, so never produced. | 0 |
| `non_numeric_value` | record invalid | reserved | The adapter refuses a non-numeric cell (typed error) instead of emitting an invalid record. | 0 |
| `dropped_row_reason_undefined` | ledger | reserved | Placeholder: the protocol defines no drop rule, so no row is dropped. A future rule must add its own code. | 0 |

All codes match the contract pattern `[a-z][a-z0-9_]{0,63}`. Dispositions: the ledger holds exactly one of the six protocol dispositions per raw row. `flagged` is assigned only to a row that would be `retained` and carries a flagged Tier 1 cell; `dropped_with_reason` is always 0 in v1.

## 4. 50 % air-speed cadence gap

**Not answered from the supplied files** (the adapter JSONs carry no cadence). Task 4 places the single 1,112 s gap in the FULL `AAU_air_speed.csv`; whether the 50 % file contains a cadence gap is not established. The script returns `air_speed_50_cadence_gap`: step histogram, the largest step with the timestamp texts at both ends, and every step above 2 x the 10 s nominal (20 s), for all 16 files, computed on distinct naive timestamps. It reports and never fills, resamples or interprets a gap, and steps are naive label seconds (timezone not established).

## 5. L1 file set (format proposal; Task 9 left the format to this task)

```
observations/<column_slug>.tsv   40 files, one line per stored second, ascending by naive second
ledger/AAU_temperature_and_power_use.tsv   one line per raw row, ascending by source row
l1_manifest.json                 sha256 / bytes / rows per file, counts, protocol and code hashes, l1_sha256
```
Observation columns: `ts_text, value_ticks, state, quality, reason_code, disposition, group_size, first_row_ordinal` (`value_ticks` = integer steps of 0.01 degC / 0.1 W, empty when missing). Ledger columns: `row_ordinal, ts_text, disposition, reason_code, group_size, first_row_ordinal`. UTF-8, LF, no timestamps, no absolute paths, no platform text, so a rerun is byte-identical (tested, including chunk size and shuffled input). Row ordinals follow the confirmed base (1-based data row, header excluded). `first_row_ordinal` is the lowest row of the group and `group_size` is carried per record: this answers the Task 9 point C-5 ("Task 12 to confirm"). Period files are NOT written: they are 100 % subsets of the full file and are never imported as separate streams (Task 9). Uncompressed size is an estimate, not measured: about 55-60 bytes per observation line x 54.8 M lines is roughly 3 GB. This task writes L1 only for synthetic fixtures; the real L1 run is a Task 14 command.

## 6. Owner decisions (defaults in bold)

1. **Q1 Disposition scope.** The protocol assigns one disposition per raw row of the whole file (all 51 columns), so a Tier 1 cell can carry `conflict_cell_missing` when the only tie in its group is in a cooling/room column. Default: **keep the file-level (protocol) disposition**, with the per-cell state carried separately. Alternative: a Tier-1-scoped disposition (the script reports how many groups this affects: `groups_with_ties_only_outside_tier1`).
2. **Q2 Flatline flag.** Default: **off** (a 10-sample run of equal 0.01 degC values may be common and flagging it changes `quality` for many records). The script reports how many cells it would mark at the protocol run length 10. Decide on, off, or another N.
3. **Q3 Range limits.** Default: **no limits, not evaluated** (none are established). Supply limits per measurand if wanted; flagged, never clipped.
4. **Q4 L1 format** as in section 5 (uncompressed TSV, about 3 GB estimated). Approve, or ask for compressed or binary parts (the hash would then cover the uncompressed stream).
5. **Q5 Blank reason name** `blank_cell` and the reserved codes in section 3. Approve or rename.
6. **Q6 Tier 1 column selection** in cleaning/tier1.py (3 power + 37 rack probes, i.e. the 11 cooling/room probes excluded) is a column selection only; no rack, sensor id or mapping is assigned. Confirm it matches Task 7 Appendix A / the 48-label spot-check outcome (G1 O-2 is still open).
7. **Q7 Real-file confirmation.** After the run, confirm `task6_differences` and `task4_differences` are empty (or explain any entry) before Task 14/15 rely on the counts.

## 7. Owner run (PowerShell, repo root)

```powershell
Expand-Archive -Path "$env:USERPROFILE\Downloads\task12_cleaning.zip" -DestinationPath . -Force
python -m ruff format research\danish_aau\cleaning research\danish_aau\tests\cleaning
python -m pytest research\danish_aau\tests\cleaning -p no:cacheprovider -q

# read-only, aggregates only; add --include-periods (6 subset files) and/or --rerun (cleans twice, compares digests) if wanted
python -m research.danish_aau.cleaning.local_run --raw .\realData\danish-server-room-v5\raw --out ..\task12_local_run.json
```
Return `task12_local_run.json`. Expected: about 40 s per index pass (Task 11 timing) plus the cleaning pass of the full file (not measured on real data; the 200 k-row synthetic run took 10 s). Memory at full scale is unmeasured; the Task 6 runner held the same 1.37 M x 51 grid.
