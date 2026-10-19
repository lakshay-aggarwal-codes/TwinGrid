# Task 23 (roadmap): facility-data calibration workflow

**Status: BLOCKED. Design only; no code, no data, no calibrated parameters.**

## Why blocked
The roadmap requires a licensed or user-owned facility dataset. None is in the tree: `data/external/REGISTER.json` lists 15 public sources (weather, grid carbon, water risk, ASHRAE papers, building-energy competition data, aircraft-engine run-to-failure, NAB, cluster traces, solar). None is measured telemetry from a data-centre cooling plant with IT power, room or inlet temperatures, and cooling power. `data/cleaned/` holds only a README. Nothing in this design is a result.

## What data would unblock it (minimum)
- 30 or more contiguous days, one facility or one hall, cadence 5 minutes or finer, with a written licence or owner permission for this use.
- Channels: IT power (kW) and utilisation or a proxy; supply/inlet and return/outlet air temperature; chilled-water supply setpoint and measured supply temperature; cooling electrical power (kW) and, if available, heat removed (kW); outside dry-bulb and humidity; cooling mode or equivalent state; water use if metered.
- Units, sensor locations and any known meter faults, in writing.

## Import schema and unit checks
- One tidy table: UTC timestamp, channel name from a fixed list, value, unit, quality flag. Timezone-less timestamps are rejected, not guessed.
- Unit check per channel against a plausibility table (for example inlet 5 to 45 C, utilisation 0 to 1, power not negative); out-of-range values are flagged, never clipped.
- Cadence check: the median step must match the declared cadence; gaps and duplicates are reported with counts.
- Raw files stay local; the repo stores only the dataset id, SHA-256, licence note and a schema report.

## Missing data
- Every channel carries a boolean `observed` mask next to its value. Nothing is interpolated across a gap longer than two steps; shorter gaps may be interpolated and are marked `imputed`.
- Fits use only rows where all channels they need are `observed`. The report states how many rows each fit used.

## What the data could identify (hypotheses until checked on real data)
| Parameter group (`src/physics/params.py`) | Needs | Expectation |
|---|---|---|
| `max_it_power_kw`, `idle_power_fraction` | IT power against utilisation | Likely identifiable |
| `coil_ua_kw_per_k` with `thermal_capacitance_kj_per_k` | Room temperature, heat removed, a load step | Time constant likelier than each alone |
| COP coefficients per cooling mode | Cooling electrical power against heat removed, over a range of outside conditions | Only the modes and ranges that occur in the data |
| `tau_chw_min`, `chw_rate_limit_c_per_5min` | Setpoint changes against measured supply temperature | Needs logged setpoint steps |
| Water group | A water meter and mode labels | Only if metered |
| Capacity derate, wet-bulb factor, humidity terms | Wide weather range | Probably not identifiable; keep published values and report them as not identified |

An identifiability check (profile likelihood and parameter correlation, on the training block) decides the final list. Parameters the data cannot pin down stay at their published values and are listed as such.

## Procedure
1. **Split in time, never at random:** contiguous blocks, for example first 60% fit, next 20% validation, last 20% test. Chosen and written down before fitting, in a pre-registration file like `reports/policy_evaluation_physics1/PREREGISTRATION.json`, with acceptance criteria.
2. **Fit** the identifiable parameters on the fit block by bounded least squares through the existing `PhysicsParams` validation, so out-of-range values are impossible. Choices among model options use the validation block only.
3. **Score the test block once.** Reuse the one-shot pattern from `src/anomaly_eval.py` so a second read raises an error.
4. **Compare with nulls:** the published-parameter model and a persistence predictor on the same block. The calibrated model must beat both on the pre-registered metrics (inlet and outlet temperature error, cooling power error, PUE error) or the result is reported as "no improvement".
5. **Uncertainty:** block bootstrap over days for parameter intervals; prediction intervals and error by operating regime on the test block. Report intervals, not point values alone.
6. **Provenance:** the fitted parameters get a new `physics_params_hash` and a label "calibrated to dataset `<id>`, `<N>` days, split `<id>`". The word "calibrated" appears in the README or UI only after step 4 passes, and only for that facility and period. A claims-ledger row is added at that point, not before.

## Rules that stay
- No invented, synthesised or "representative" data is ever labelled measured. Synthetic data may be used only to test the pipeline (parameter recovery from simulated data), and is labelled synthetic everywhere.
- Calibration to one facility is not a claim about any other.
- Physics versions 1, 2 and legacy-0 are not mixed in one fit.

## Planned code (once unblocked)
`src/calibration/{schema,checks,split,fit,identifiability,report}.py`, `scripts/calibrate.py`, tests for schema rejection, unit checks, mask handling, time-split leakage, one-shot test scoring, and synthetic parameter recovery.

## To unblock, send
A description of the dataset (owner, licence, columns, units, cadence, duration) and one day of rows with identifying details removed.
