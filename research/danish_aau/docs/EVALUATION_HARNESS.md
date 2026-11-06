# Evaluation harness - Phase 1 guide

Phase 1 = foundation only: configuration, path anchoring, header-level inventory, run manifest, CLI. It reads no
measurement values, produces no comparison or metric, and does no calibration or training.

## Commands (PowerShell, from anywhere)

```powershell
python research\danish_aau\run_evaluation.py doctor
python research\danish_aau\run_evaluation.py inventory --count-rows --hash
python research\danish_aau\run_evaluation.py run --count-rows --hash-inputs
python research\danish_aau\run_evaluation.py verify research\danish_aau\outputs\<run_id>
python research\danish_aau\run_evaluation.py show-config
```

Common options: `--config <toml>`, `--raw-dir <path>` (else `$env:TWINGRID_AAU_RAW_DIR`, then the config, then
`realData/danish-server-room-v5/raw` relative to the repo root). Exit codes: 0 ok, 2 failed check / bad config / bad usage,
3 `--require-ready` with undeclared timezone or duplicate policy.

## Tests

```powershell
python -m pytest research\danish_aau\tests\evaluation -p no:cacheprovider
```

Synthetic fixtures only; the real `realData` folder is not needed or touched. The pre-existing
`research/danish_aau/tests/test_audit_validation.py` is not touched and not run by the command above.

## Key design points

- **Isolation**: no import of `src`, `api`, `models`, DB or web libraries (AST-checked); nothing in production imports `research`.
  `src/repro/canonical.py` and `env.py` are reused by file path because `import src` rewires logging and writes `logs/`.
- **Raw data**: opened only through `open_raw_bytes` (read-only, confined); `RawDataGuard` compares path/size/mtime before and after every run.
- **Declarations**: `timestamps.timezone` and `policies.duplicate_timestamps` default to `undeclared`; averaging/first/last of duplicates is not selectable; interpolation and ventilation filling are not selectable.
- **Manifest**: deterministic core hash (config without machine locations, registry, input fingerprints, code revision, **evaluation source fingerprint**); `claims.calibrated` and `claims.validated_against_real_data` are false and `verify` fails if altered; `data_kind` says `synthetic_fixture` or `reported_real_dataset`.
- **Source fingerprint** (`evaluation/fingerprint.py`): SHA-256 over the relative path and (line-ending-normalised) content of `evaluation/**/*.py`,
  `config/*.toml`, `run_evaluation.py`, `docs/EVALUATION_*.md`, `src/repro/canonical.py`, `src/repro/env.py`. It reads the filesystem, so untracked
  files count (the reused `env.code_state` digest does not include untracked content). Outputs, caches and the raw dataset are excluded; tests are not covered.
  The per-file list is stored in the manifest (`source_files`); `verify` checks it hashes to the stored fingerprint AND that the current tree still matches
  (`source_unchanged`, which names added/removed/modified files). `code_revision` is kept in the core as before.
- **Expectations** in `registry.py` come from the context document and are unverified; "match" is not a data-quality verdict.

## Validation by Kilo Code on the local machine

Run in `the TwinGrid repository root` after extracting the ZIP (see its extraction command), with the project venv.

1. `python -m pytest research\danish_aau\tests\evaluation -p no:cacheprovider` - expect all pass (142 passed in the authoring sandbox, Python 3.12.3; the project pins 3.12.10).
2. `doctor` - expect no FAIL; WARN for undeclared timezone/duplicate policy is expected.
3. `inventory --count-rows --hash` - for each of the four registered files record status and every mismatching check
   (size, n_columns, first_column, data_rows). Expected from the context document: 52/17/7/7 columns, 90,902/9,091/1,526/4,576 rows,
   sizes 46,786,437/2,926,941/156,859/225,183 bytes. Also record: detected delimiter, BOM, encoding, unclassified columns, and the
   list of UNREGISTERED CSVs (names of the 50/75/100/idle files). **Report these as measured facts; do not adjust the registry to force a match without telling the user.**
4. `run --count-rows --hash-inputs`, then `verify` on the run directory - expect all PASS.
5. Re-run step 4 with a new run id and NO source edits in between; the `manifest core sha256` must be identical. (Editing any covered file between runs changes it, and `verify` of the earlier run then reports `source_unchanged` FAIL; that is intended.)
6. Confirm the raw folder is unchanged (the run itself fails if not) and `git status` shows no change under `realData/`.
7. Report the public functions of `research/danish_aau/audit/audit_danish_aau.py` (needed to avoid duplication in Phase 2).
8. Note any Windows-specific failure (paths with spaces, console encoding, tzdata).

## Unverified without the local dataset

Everything involving real files: that the four filenames resolve, the actual delimiter/encoding/BOM, that sizes, column counts and
row counts equal the reported ones, the real column names matching the classification patterns (`Temperature mod N ch M`, `velocity N`),
runtime of `--count-rows`/`--hash` on the 46 MB file, and Windows behaviour. Tested only on synthetic fixtures and on Linux.
