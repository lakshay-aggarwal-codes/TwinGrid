# Evaluation harness - Phase 2: data engineering (revision 2, after source review)

Scope: a streaming reader, a global time index, declared policies, and an alignment engine. It makes **no scientific
comparison**, computes no accuracy metric, has no TwinGrid adapter, imports nothing from `src`, and does no training or
calibration. Everything below was tested on synthetic fixtures; none of it has been run on the real Danish CSVs by this code.

## Corrections made in this revision

| # | Correction |
|---|---|
| 1 | Ventilation expectations replaced by the locally verified findings: 4,576 rows in exactly three disjoint population patterns (damper only: 1,526; fan speeds + supply temperature: 1,525; the two duct pressures: 1,525), so FULL 0 / PARTIAL 4,576 / EMPTY 0. The old "FULL 1,525 / PARTIAL 1 / EMPTY 3,050" and "101 FULL rows" were wrong and are removed; the 16:47 row is one example of the damper-only pattern, not the only partial row. A data-driven population-pattern census was added. |
| 2 | Bucket reducers are exactly `count`, `min`, `max`, `mean` (and only when approved). `first` and `last` were removed. A bucket containing rows that share a source timestamp is `ambiguous`: row ids are kept, nothing is aggregated. |
| 3 | `source_offset_s` is no longer defaulted to 0. Elapsed series on different clocks need a declared offset or the same stated origin. Tolerance, offset and bucket width must be finite. |
| 4 | Pass 2 now verifies column content, not only timestamps (see "Reader integrity"). |
| 5 | Timestamp text ending in a timezone designator is rejected whatever the configured format says. |
| 6 | Every generated sidecar is listed with relative path, size and SHA-256; `verify` detects modified, missing and added outputs. |
| 7 | Stale "Phase 1" wording fixed; `data_layer/types.py` renamed to `vocabulary.py`; `doctor` now detects a stale module that shadows the standard library. |

## Four layers

| Layer | What it is | Code |
|---|---|---|
| L0 | Immutable raw CSV files. Opened only through the Phase 1 read-only helper; fingerprinted before and after every run. | `guard.py` |
| L1 | Original observations: every row, source order, original values, plus index annotations. Never sorted, dropped, averaged, filled or rewritten. | `data_layer/reader.py`, `observations.py`, `time_index.py` |
| L2 | Policy-controlled derived view. A declared policy applied to L1, with an exclusion ledger and a provenance record. Never replaces L1. | `data_layer/policies.py` |
| L3 | TwinGrid simulated series. A container only (`TimedSeries.from_simulated`); no simulator, no `src`. | `data_layer/alignment.py` |

L1/L2 and L3 meet **only** inside an `AlignmentResult`, whose columns are namespaced `target__*` / `source__*`. A series keeps the
layer and provenance it was created with (L1 measured, L2 derived, L3 simulated) and cannot be relabelled.

## Public interfaces (`research/danish_aau/evaluation/data_layer/`)

| Module | Main names |
|---|---|
| `vocabulary.py` | `Layer`, `TimeBasis`, `TimestampState`, `Completeness`, `AlignmentStrategy`, `AlignStatus`, `PolicyId` |
| `errors.py` | `DataLayerError` and typed subclasses (`DataConfigError`, `ReaderError`, `NumericParseError`, `MaterialisationError`, `PolicyNotApproved`, `AlignmentError`, `ClockMismatchError`, `UnsafeDerivedPath`, `DiscoveryError`) |
| `config.py` | `DataConfig`, `load_data_config()`, `parse_data_config()`, `resolve_duplicate_policy()`, `KNOWN_REDUCERS` |
| `discovery.py` | `discover_sources()` -> `SourceFile` (registered files only) |
| `channels.py` | `resolve_channels()` -> `ChannelSet` |
| `timeparse.py` | `parse_naive_timestamps()`, status codes incl. `TZ_SUFFIX` |
| `time_index.py` | `TimeIndex` (incl. `pattern_census()`), `TimeIndexBuilder`, `column_digest()` |
| `reader.py` | `AauCsvReader.build_time_index()` (pass 1), `.iter_chunks()` (pass 2), `.verify_integrity()` |
| `observations.py` | `ObservationStream.open(...)`, `.iter_chunks()`, guarded `.to_frame(confirm=True)` |
| `policies.py` | `DerivedView`, `stable_time_order()`, `apply_order()` |
| `alignment.py` | `TimedSeries`, `AlignmentSpec`, `align()`, `AlignmentResult` |
| `provenance.py` | `DerivationRecord`, `ExclusionLedger`, `ProvenanceLog`, `safe_output_path()` |
| `validation.py` | `EXPECTED_AUDIT`, `cross_check()` |
| `prepare.py` | `run_prepare()`, `describe_artifacts()` (the `prepare` stage; imported lazily) |

Phase 1 extension points used (checked in the source): `RunContext` (optional `data_config_path`), the `Stage` protocol,
`register_stage()`, `available_stages()`, the manifest and `verify`.

## Reader

Pass 1 streams the file in chunks (default 50,000 rows), keeps the original timestamp text, parses it with the explicit
configured format(s), and builds one global `TimeIndex`: `_src_row`, parse status, `_elapsed_s`, `_delta_s`, ordering flag,
global duplicate groups (including groups that straddle chunk boundaries or are not adjacent), group conflicts, per-row
completeness and population pattern. Pass 2 streams only the requested columns/rows and attaches the annotations.

- `_src_row` = 1-based ordinal of the non-blank data line (same convention as the Phase 1 row count). Stable under chunking and selection.
- Conflict = the raw text of any non-timestamp column differs within a duplicate group ("21.30" vs "21.3" counts).
- Non-numeric, non-missing cells raise `NumericParseError` by default (`reader.non_numeric = "raise"`, kept); `"flag"` records them as NaN.
- Only `reader.na_values` (default `[""]`, after stripping) are missing. Nothing is filled or interpolated.
- `to_frame(confirm=True)` is the only way to materialise; it also refuses over `reader.materialise_cell_limit` unless `allow_large=True`.
- Memory is bounded by chunk size, not small: on a synthetic 90,902 x 52 file the peak was about 123 MB at chunksize 5,000, 157 MB at 10,000 and 385 MB at 50,000 (about 10 s), with identical results.

### Reader integrity (what pass 2 does and does not verify)

Pass 1 stores, per chunk and per non-timestamp column, a SHA-256 of the raw cell text. Pass 2 recomputes them and raises `ReaderError`
on any difference, together with the chunk layout and the timestamp text of every row. So pass 2 **does** detect a changed measurement
value even when the timestamp and the cell length are unchanged, **for the timestamp column and every column it reads**.

Pass 2 does **not** verify columns it does not read. `verify_integrity()` re-reads and verifies all of them. The `prepare` stage streams
every measurement column and reports `content_integrity_verified_columns` and `content_integrity_unverified_columns`. Neither check
claims to detect every possible change to the file; they detect changes to the columns they read, row count, and chunk layout.

## Timestamps

State is always `naive_unspecified`. No timezone is assumed and no UTC conversion exists. `%z`/`%Z` formats are rejected by the
configuration. Independently of the format, any text that ends in a timezone designator after a time component (a literal `Z`, an
offset such as `+02:00`, `+02` or `-0500`, or `UTC`/`GMT`) gets the status `tz_suffix_rejected`: the row is kept, the text is untouched,
no value is derived, and it is counted separately from parse errors. Date-only text (`2024-09-17`) is not affected. A Phase 1
`timestamps.timezone` declaration is recorded as metadata (`timezone_applied: false`) and never applied.

## Policies

- Duplicates: `keep_all_ordered` (primary; nothing removed). `exclude_ambiguous` exists only as an approved sensitivity policy (`policies.approved_sensitivity`; not approved), removes every row of a conflicting group and writes a complete ledger. Keep-first, keep-last and averaging do not exist.
- EMPTY rows (no expected field populated): kept in L1; the L2 valid view excludes them with a ledger (`exclude_empty_rows`), or keeps them flagged (`keep_empty_flagged`). PARTIAL rows are always kept. In the locally observed ventilation file there are no EMPTY rows and no FULL rows.
- Population patterns: `TimeIndex.pattern_census()` lists each distinct populated-column signature (exact column list, row count, first/last source row and timestamp text); each row keeps its `_pattern_id`. It is descriptive: it does not infer simultaneity, a shared acquisition schedule, or why cells are empty.
- Sorted view: `stable_time_order()` records the permutation and its SHA-256; unparsed rows sort last.

## Alignment

`exact`, `nearest` (explicit tolerance), `backward_asof` (explicit tolerance or explicit `allow_unbounded`), `bucket` (trailing window
`(t - width, t]`).

- Bucket reducers are exactly `count`, `min`, `max`, `mean`, and only when listed in `approved_reducers`. None is approved by default. `first` and `last` do not exist.
- A bucket that contains rows sharing a source timestamp is `ambiguous` (`duplicate_source_timestamps`, or `conflicting_duplicates` when flagged conflicts are present): all row ids are listed, values stay NaN, nothing is reduced.
- Every target row is retained with `align_status` (matched / unmatched / ambiguous), `align_reason`, candidate source rows and `align_dt_s`. Ambiguous and unmatched rows carry no source value.
- Clocks: naive wall clocks must share a clock id or carry an explicit equivalence note. Two elapsed series on **different** clock ids need a declared `source_offset_s` (0.0 is a deliberate claim that both start together, never a default) or the same stated `origin_text` on both. The same clock id with different origins is refused. The relationship used is recorded as `offset_basis`.
- Naive vs elapsed bases, tz-aware series (blocked pending a documentary TimeMapping) and offsets between naive clocks are refused.
- `tolerance_s`, `source_offset_s` and `bucket_width_s` must be finite numbers; NaN, infinity, booleans and strings are rejected. Non-finite elapsed values in a series become invalid times.
- Source row order never matters.

## Running the stage

```powershell
python research\danish_aau\run_evaluation.py run --stage preflight --stage prepare --hash-inputs
```

`prepare` writes only under the run directory: `time_index_<key>.csv`, `duplicate_groups_<key>.csv` (if any), `exclusion_ledger_<key>_<policy>.csv`
(if any), `provenance_<key>.json`, and `stage_prepare.json`. It writes no copy of measurement values. `stage_prepare.json` lists every
sidecar under `artifacts` with relative path, kind, byte size and SHA-256 (the raw dataset is never listed). The manifest records the stage
report's SHA-256. `verify` checks: the stage report hash, every artifact's size and SHA-256 (modified or missing), and that the run directory
contains nothing else (added). Listings are sorted and deterministic across repeated runs.

## Kilo Code: local verification procedure (revision 2)

Run in `the TwinGrid repository root`, with the project venv.

**Apply the COMPLETE ZIP.** `TwinGrid_AAU_Phase2_complete.zip` contains every Phase 2 file (including `runner.py`, `p2_fixtures.py` and the whole
`data_layer` package), so it works whether or not an earlier Phase 2 ZIP was applied; extracting over identical files is harmless. The earlier
`..._review_corrections.zip` is only a delta and fails (`No module named 'p2_fixtures'`, `unexpected keyword argument 'data_config_path'`) on a tree that
lacks the first Phase 2 ZIP. Prerequisite: Phase 1 and the fingerprint fix (`..._fix_source_fingerprint.zip`) must already be applied.

**Remove the stale module.** The first Phase 2 ZIP created `data_layer\types.py`; extracting a ZIP cannot delete it. It shadows the
standard library whenever Python starts inside that folder and must be removed. `doctor` fails until it is gone.

```powershell
Set-Location (git rev-parse --show-toplevel)
Expand-Archive -Path (Join-Path $env:USERPROFILE "Downloads\TwinGrid_AAU_Phase2_complete.zip") -DestinationPath . -Force
Remove-Item research\danish_aau\evaluation\data_layer\types.py -ErrorAction SilentlyContinue
Test-Path research\danish_aau\evaluation\data_layer\types.py
Test-Path research\danish_aau\evaluation\data_layer\vocabulary.py
Test-Path research\danish_aau\tests\evaluation\p2_fixtures.py
Select-String -Path research\danish_aau\evaluation\runner.py -Pattern "data_config_path" -Quiet
python -m pytest research\danish_aau\tests\evaluation -p no:cacheprovider
python research\danish_aau\run_evaluation.py doctor
Measure-Command { python research\danish_aau\run_evaluation.py run --stage preflight --stage prepare --hash-inputs --run-id p2c }
python research\danish_aau\run_evaluation.py verify research\danish_aau\outputs\p2c
python research\danish_aau\run_evaluation.py run --stage preflight --stage prepare --hash-inputs --run-id p2d
(Get-FileHash research\danish_aau\outputs\p2c\stage_prepare.json).Hash -eq (Get-FileHash research\danish_aau\outputs\p2d\stage_prepare.json).Hash
(Get-Content research\danish_aau\outputs\p2c\manifest.json | ConvertFrom-Json).determinism.manifest_core_sha256
(Get-Content research\danish_aau\outputs\p2d\manifest.json | ConvertFrom-Json).determinism.manifest_core_sha256
git status --short realData
```

Expected: `Test-Path ...types.py` -> `False`; the `vocabulary.py`, `p2_fixtures.py` and `data_config_path` checks -> `True`; 446 tests pass; `doctor` has no FAIL; both `verify` runs pass every
check including `stage_reports_unchanged` and `artifacts_unchanged`; the two `stage_prepare.json` hashes are equal.

Then re-hash all 16 local CSVs the same way `raw_integrity_snapshot_2026-10-31.json` was produced and compare to it.

Report as measured facts (do not edit expectations to force a match):

1. Tests: total and failures (446 expected: 142 Phase 1 + 304 Phase 2).
2. Ventilation (`files.ventilation.time_index`): `completeness_counts` (locally verified expectation FULL 0 / PARTIAL 4,576 / EMPTY 0), `population_patterns` (three entries; exact `populated_columns`, `n_rows`, first/last source row and timestamp text), `missing_by_column`, and every `cross_check` line.
3. Main file: `n_duplicate_groups` (46 recorded), `n_conflicting_duplicate_groups`, `delta_seconds_counts`, `n_ordering_violations`, `n_timestamp_tz_suffix_rejected` (0 expected), `stream_check` (`non_numeric_cells`, `content_integrity_verified_columns`).
4. Every file: all `cross_check` mismatches with expected vs actual; `unclassified_measurement_columns`; `l2_view` rows in view and excluded.
5. Elapsed time and peak memory of the run (synthetic reference: about 10 s and 385 MB at chunksize 50,000).
6. Both runs: identical `stage_prepare.json` hash, identical artifact lists, identical manifest core hash.
7. Only registered files were read by `prepare`; the raw folder is unchanged (snapshot comparison and `git status`).

## Known limitations

- No real-data execution by this code. The ventilation patterns and completeness counts are the reviewer's local findings; the other expectations are the earlier audit's and remain unverified.
- Pass 2 verifies the timestamp column and the columns it reads, row count and chunk layout. It does not verify columns it does not read (use `verify_integrity()`), and it reports the chunk's row range, not the exact row, of a difference.
- Memory at the default chunk size is about 385 MB on a 90,902 x 52 file (see Reader).
- The tz-suffix rule recognises Z, numeric offsets after a time component, and UTC/GMT; other named zones (for example `CET`) are not special-cased and fail only if the configured format cannot parse them.
- `_src_row` counts non-blank lines; a quoted field containing a newline would differ from a physical line number (none is known).
- `_elapsed_s` is measured from the first parseable row in source order, not the earliest timestamp.
- The default timestamp format has whole seconds; fractional seconds need a configured format.
- Bucket reduction runs a Python loop per target: about 17 s for 90,902 targets, 0.14 s for 304.
- A data config supplied with `--data-config` from outside `config/` is hashed in the stage report but is not part of the source fingerprint.
- `exclude_ambiguous` removes conflicting groups only; identical duplicates are kept.
- Time-index CSV bytes are deterministic within one pandas version; they are not guaranteed identical across pandas versions.

## Unresolved decisions

1. Phase 1 `config/default.toml` keeps `duplicate_timestamps = "undeclared"` (preserved as instructed), so Phase 1 readiness still lists it as blocking while the Phase 2 data config declares `keep_all_ordered`. If the two disagree, Phase 2 fails loudly.
2. Whether comparisons (Phase 3) need a declared timezone, given `naive_unspecified` and elapsed-time alignment. None is declared.
3. Whether L1/L2 value tables should be written to disk (currently none are).
4. Cross-file clock equivalence (main vs supplementary loggers) and the measured-vs-simulated origin or offset have no default; each alignment states its relationship.
5. No bucket reducer and no `exclude_ambiguous` sensitivity run is approved.
6. `reader.non_numeric` stays `raise`; switch to `flag` only if the real data requires it.
