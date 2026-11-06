# Danish AAU v5 offline evaluation: plan (Phases 1-4)

Status: Phase 1 implemented (see `EVALUATION_HARNESS.md`). Phases 2-4 are PROPOSED and wait for review.
Basis: the TwinGrid repo ZIP and `danish_aau_dataset_context.md`. The real `realData` folder was NOT available when this
was written; nothing here was run against it, and no measurement value appears in this document.

## 0. What was and was not reviewed

| Item | Status |
|---|---|
| `research/danish_aau/audit/audit_danish_aau.py`, `docs/manifest.md`, `reports/*`, `tests/test_audit_validation.py` | **Not in the supplied ZIP.** Described only by the context document. NOT reviewed. Phase 1 therefore does not duplicate the audit's job (timestamp parsing, duplicate/interval analysis) and does not touch those paths. |
| Existing audit tests failing with `research/research/...` | Not inspected. Likely cause: a cwd-relative path join. The harness anchors all paths on the file location (`paths.py`) and its tests pass from four different working directories. |
| TwinGrid interfaces (section 1) | Read from source and smoke-run headlessly (legacy-0, 1, 2 all step). |

Kilo Code, first task: report the public functions of `audit_danish_aau.py` (discovery, timestamp parsing, duplicate
detection) so Phase 2 imports them instead of re-implementing.

## 1. TwinGrid interfaces needed

| Interface | Where | Use / caveat |
|---|---|---|
| `DigitalTwin(physics_version=, start_time=, max_it_power_kw=, idle_power_fraction=, air_flow_m3_s=, physics_params=, ...)` | `src/digital_twin.py` | Construct per run. **Defaults describe a 500 kW facility**; the AAU room is far smaller, so scale must be declared (blocker B3). |
| `twin.step({"utilisation", "outside_temp_C", "humidity_pct", "cooling_mode", "chilled_water_temp_C", ...}, dt_seconds=)` | same | `dt_seconds` in (0, 3600]; legacy-0 accepts only 300 s; v2 additionally limited to `max_dt_over_tau * C_th/UA` (3600 s at defaults). Inputs validated against `INPUT_RANGES`. |
| `DataCentreState` / `.to_dict()` | same | Comparable fields: `outside_temp_C` (an INPUT), `server_inlet_temp_C`, `server_outlet_temp_C`, `it_power_kw`, `cooling_power_kw`, `total_power_kw`. |
| `twin.physics_identity` -> `{physics_version, physics_params_hash}` | same / `src/versions.py` | Must be recorded in every simulated artifact. |
| `PhysicsParams` (frozen, hashable) | `src/physics/params.py` | Declared, not fitted, in Phases 1-4. |
| `canonical.py`, `env.py` | `src/repro/` | Reused for hashing, code revision, platform capture (loaded by path; see below). |
| `src/calibration` (Task 23) | `src/calibration/` | **Not used.** Rejects timezone-less timestamps and has a one-shot test block; evaluation must not consume it. |

`import src` calls `setup_logging()` (rewires the root logger, writes `logs/digital_twin.log`). Only the Phase 3
`twin_adapter.py` may import `src`, lazily.

## 2. Architecture

```
research/danish_aau/
  run_evaluation.py            cwd-independent entry point                           [P1]
  config/default.toml          strict TOML, explicit declarations                    [P1]
  config/channel_map.toml      USER-AUTHORED sensor mapping with sources             [P3]
  evaluation/
    paths.py _reuse.py config.py provenance.py registry.py guard.py
    inventory.py manifest.py runner.py cli.py __main__.py  stages/preflight.py       [P1]
    io/loader.py                 read-only CSV load, naive timestamps kept naive     [P2]
    timeline.py                  sequence key, interval classes, gap flags           [P2]
    policies.py                  duplicate / alignment policies (declared only)      [P2]
    quality.py                   checks vs context-doc expectations                  [P2]
    derived.py                   derived copies + provenance sidecars                [P2]
    stages/prepare.py                                                                [P2]
    twin_adapter.py              ONLY module importing src (lazy)                    [P3]
    targets.py                   comparison-target registry (comparable? why not?)   [P3]
    alignment.py                 binning to the twin step                            [P3]
    stages/compare_*.py                                                              [P3]
    metrics.py uncertainty.py plots.py report.py stages/report.py                    [P4]
  tests/evaluation/              synthetic-fixture tests per module
  outputs/                       git-ignored run directories
```

Principles: raw files read-only and fingerprinted before/after every run; derived data is a separate copy with a
provenance label per column; policies are declared in config and recorded in the manifest, never defaulted;
a comparison that is not defensible is emitted as `unavailable` with the reason, not omitted.

### Phase 2 - loading, alignment, policies
- Loader: naive timestamps stay naive; the declared timezone is attached only as metadata. Parse failures are errors, not NaT.
- Duplicate timestamps (46 differing pairs): policies `keep_all_ordered` (sequence key) and `exclude_ambiguous` only; the
  second is a sensitivity variant. Averaging / first / last stay rejected.
- Ventilation: populated rows only, no fill. Interpolation: none. Cross-file join: by timestamp with a declared tolerance, never by row number.
- Audit the 50/75/100/idle files before enabling them (`dataset.load_period`).
- Add `tzdata` for Windows in a research-only requirements file (not the main lock).

### Phase 3 - scientifically valid comparisons
Only targets that survive section 3 are computed; the rest are written as `unavailable` with reasons.
1. Outside temperature: **data-sanity / alignment check only** (it is a twin INPUT; see B2).
2. IT power: normalized and, if a scale is declared, absolute.
3. Temperature: only for channel groups declared in `channel_map.toml`; otherwise `unavailable`.
Never: airflow vs point velocity, AHU pressure vs `water_pressure_bar`, damper vs `cooling_mode`, cooling power / PUE / WUE / carbon (no measured counterpart).

### Phase 4 - metrics, plots, reports
MAE, RMSE, MBE, Pearson r (supplementary), MAPE only when the target is safely nonzero; block bootstrap intervals with a recorded seed;
effective sample size; error read against instrument uncertainty (PT100 0.21 degC, PDU 1.25%). Reports (JSON + Markdown) carry a fixed
banner: simulated vs measured legend, "TwinGrid physics v2 is uncalibrated; timestamp overlap is not validation". Plots use matplotlib
imported lazily (not in the project requirements).

## 3. Scientific blockers and assumptions

| # | Blocker | Consequence | Needed |
|---|---|---|---|
| B1 | Timezone of naive timestamps unknown; main and supplementary files may use different clocks. | Cross-file joins and any external weather comparison are unsafe. | User declares timezone + basis; sensitivity to clock offset between files. |
| B2 | `outside_temp_C` is an INPUT to the twin. | Driving the twin with `Outdoor_temperature` makes the "comparison" zero-error by construction. Reporting it as a result would be misleading. | Treat as sanity check / forcing signal only. Units of `Outdoor_temperature` are also unconfirmed. |
| B3 | Scale and driver mismatch: defaults model 500 kW; AAU has three rack-level channels and no utilisation signal ("25% load" is an experiment label). | Absolute power error is dominated by the declared scale, not model quality. Fitting the scale to the same window is calibration. | Declare scale from nameplate/layout a priori, or compare normalized power vs load fraction across periods (scale-free; needs the other periods audited). |
| B4 | Power channel meaning: 3 channels vs 6 racks; some equipment unmeasured; channel-to-port unresolved. | A sum of channels may not equal total IT load. | User-confirmed mapping from the layout workbook. |
| B5 | Temperature channel-to-location mapping unresolved (images not inspected). | No defensible inlet/outlet aggregate; an all-channel mean is meaningless. | `channel_map.toml` authored from the images, each group with its source. |
| B6 | Cooling power, PUE, WUE, carbon have no measured counterpart (room cooled by a building AHU). | Not comparable. | None; reported as unavailable. |
| B7 | Time-scale: 1 s data vs twin dt in (0, 3600] s; v1/v2 inlet floor at 18 degC; air lag 10 min. A ~25 h window with steady load carries little dynamic information. | Result is mostly steady-state agreement; structural offsets must be reported as structural. | Declared bin size and warm-up exclusion. |
| B8 | No humidity measurement; twin default is constant 50 %. | Declared assumption, listed in every report. | - |
| B9 | One experiment per load level. | Correlated samples; naive confidence intervals overstate certainty. | Block bootstrap; report effective n. |
| B10 | Duplicate policy unvalidated; supplementary acquisition schedule undocumented. | Policies stay explicit and sensitivity-tested. | User choice. |

## 4. Acceptance criteria

**Phase 1** (met on synthetic fixtures; real-data items pending Kilo): harness imports without `src`; raw data opened read-only and
fingerprinted; unknown config keys rejected; timezone and duplicate policy default to `undeclared` and block comparisons; manifest has a
deterministic core hash, no absolute paths and no calibration/validation claim; `verify` detects tampering; tests pass from any cwd;
`doctor`/`inventory`/`run` execute locally on the real folder and report match/mismatch against the context document's numbers.

**Phase 2**: derived copies reproduce byte-identically from the same config; duplicate clusters (14) / pairs (46), interval counts and the
101 in-window supplementary observations reproduce the context document's figures on the real data, or each difference is explained;
no raw file changes; every derived column has a provenance label; policy choice appears in the manifest.

**Phase 3**: every target is either computed with a stated physical scope or `unavailable` with a reason; the twin adapter records
`physics_identity`; no twin input is compared to itself as a result; no parameter is fitted on the evaluation window; a pre-declared scale is a required input for absolute power.

**Phase 4**: metrics unit-tested against hand-computed values; results are reproducible from one command; each report states
uncalibrated/unvalidated status, the data kind (real vs fixture), policies, sample sizes and uncertainty; MAE below instrument uncertainty is flagged as not meaningful.
