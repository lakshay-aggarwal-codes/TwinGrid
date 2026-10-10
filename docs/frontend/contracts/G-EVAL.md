# G-EVAL: Contract Confirmation Record (BC-11 evaluation results)

**STATUS: GATE NOT OPEN. THERE IS NO EVALUATION ENDPOINT IN THIS BACKEND SNAPSHOT.**
This record (1) states exactly what exists today, from the code and from the one real evaluation report in the repo, (2) fixes the response shape the
frontend needs, field by field, from keys that already exist, and (3) lists what the backend must add (prompt **BE-G2**). FE-17 starts only after BE-G2 is
merged and the "To capture" runbook below is clean. **Nothing in the "Required shape" section exists yet; it is a specification, not a capture.**

## What exists today (facts)

| Item | State |
|---|---|
| HTTP route that returns evaluation results | **None.** `grep` of `api/` finds no evaluation route; `api/services/optimization_service.py` mentions "evaluation" only in a gate comment. |
| `POST /api/optimize` (FE-09 card) | Returns a simulator summary with **no** outcome, CI, baselines or claim. It is not BC-11. |
| Evaluation artefacts (files only) | `reports/policy_evaluation/baselines_only_0fcafef9d28fd539/{results.json,REPORT.md}` (T8 harness, `src/policy_evaluation.py`, `schema_version` 1); `reports/policy_evaluation/PREREGISTRATION.{json,md}`. The T30 runner `scripts/eval_policies.py` writes `reports/runs/<run_id>/{manifest,status,PREREGISTRATION,results,decision}.json`, but **no `reports/runs/` directory exists in the repo**, so no T30 output exists to capture. |
| Real data present | Exactly one report: baselines-only, outcome `NOT_EVALUATED`, `claim_allowed: "none"`, **no PPO row**, generated 2026-10-02. Captured unchanged as `G-EVAL.capture-results-baselines-only-v1.json` (sha256 `e17f1473bbad6a2db47bb31b3016eec212a1011e5a3a5aee9641504e8462c822`). |
| PPO candidates evaluated | None. So outcomes A, B, C have **never been produced** on this repo. Their shapes below come from `decide_outcome()` in code, not from a run. |

### Vocabulary in code (backend-authoritative)
- `decision.outcome` (T8 / `src/policy_evaluation.py`): `A`, `B`, `C`, `NOT_EVALUATED`.
- `decision.claim_allowed` (T8): `"simulator-validated candidate"` (only when A) or `"none"`. T30 adds: `"simulator-validated candidate, robust to the listed perturbations in this simulator"` / `"none"`.
- T30 `decision` adds `t8_outcome`, `promotable`, `registry_action` (`promote`|`reject`|`none`), `result` (`promote` | `"no promotable policy"`), `criteria[{id,passed}]`, `gates[{id,passed}]`, `scope_limit`.
- **Not backend vocabulary:** `evaluation_status`, `inconclusive`, `unsafe`, `data-limited` (named in the FE-17 prompt). The frontend must not invent them; any value outside the four codes renders neutral as "Unrecognised outcome".

### What is NOT in the results (so the UI must say "not provided")
- **No definition text per outcome.** `decision.reason` is a sentence about *this run*, not a definition of A/B/C. Definitions live in prose in `PREREGISTRATION.md`.
- **No uncertainty on per-policy means.** `summary_test_mean_per_episode.<policy>.<metric>` are means with no CI. CIs exist **only** as paired PPO-minus-baseline differences inside `decision.detail.per_baseline.<baseline>.{seed_level_diff,scenario_level_diff}` = `{n, mean, sd, se, df, t_critical, ci_low, ci_high}` (t-based, 95 %, level in the pre-registration `confidence`), and only when PPO candidates exist. In the baselines-only report there are none.
- **No `policies` array and no `ci_level` field.** Policies are dictionary keys (`rule`, `best_constant`, `ppo_seed_<n>`); the CI level is `EvalConfig.confidence` (0.95), not emitted in `results.json`.
- **No dataset identity.** Inputs are `scenario_inputs`: "synthetic diurnal weather and workload from DataCentreEnv; simulated plant".
- **Carbon is not real:** `carbon: {is_real: false, flat_curve: true}`. Carbon figures are fallback values and must carry that label.

### Two ids that must not be confused
| id | Source | Meaning |
|---|---|---|
| `scenario_set_id` in G-RUN / `GET /api/runs` | `sset-<registry_version>-<12 hex>` | content hash of the BC-09 *scenario registry* (what-if presets). |
| `scenario_set_id` in evaluation results | 16 hex, e.g. `0fcafef9d28fd539` (validation `a290e92dcf0037b0` n=30, test `b8329f196c910981` n=60) | hash of the pre-registered *evaluation episodes* (synthetic DataCentreEnv, 3 water-stress families). |
They are unrelated. The UI labels them "Scenario registry set" and "Evaluation scenario set" and never shows one as the other. (This closes open decision 1 of G-RUN: the ids do not collide in value, but they do collide in name.)

## Required shape (SPECIFICATION for BE-G2; read-only projection, nothing computed)

`GET /api/evaluations` (list) and `GET /api/evaluations/{evaluation_id}` (one). JWT, any role, rate class `general`. `evaluation_id` = the report directory name
(`baselines_only_0fcafef9d28fd539`). Ids are validated against the directory listing; anything else is 404 (no path traversal).
Responses are produced by reading `results.json` (and `decision.json` when present) and renaming nothing that the backend vocabulary above defines.

List item: `{evaluation_id, source: "policy_evaluation_v1", generated_at_utc, outcome, claim_allowed, ppo_evaluated: bool}`; newest `generated_at_utc` first. **Only the v1 format (`reports/policy_evaluation/<id>/results.json`, `schema_version` 1) is served.** T30 `reports/runs/*` is out of scope until a real T30 run exists and has its own CCR (`source` stays in the shape so that addition is not a breaking change).

Detail (every key below already exists in `results.json`/`decision.json`; those marked **new** are static backend-owned text):
```
evaluation_id, source, origin: "simulated" (**new**, static: the harness only runs DataCentreEnv), schema_version, generated_at_utc (environment.generated_at_utc),
physics_version, scenario_inputs, carbon {is_real, flat_curve},
scenario_set_id, scenario_sets {validation{id,n}, test{id,n}}, preregistration_sha256,
decision { outcome, reason, claim_allowed, [selected_seed, simpler_controllers_within_tolerance, detail ...verbatim when PPO present],
           [T30: t8_outcome, promotable, registry_action, result, criteria, gates, scope_limit] },
policies: [ { policy_id, kind: "rule"|"best_constant"|"ppo", metrics: { <metric>: number } } ]   // backend order; from summary_test_mean_per_episode
metrics:  { <metric>: { better: "higher"|"lower", definition: string } }                          // copied verbatim from PREREGISTRATION.json `metrics`
outcome_definitions: { A: string, B: string, C: string }                                            // copied verbatim from PREREGISTRATION.json `outcome_rules`; no NOT_EVALUATED entry exists, so none is invented
ci_level: 0.95                                                                                     // copied from PREREGISTRATION.json `config.confidence`; not computed
selection { best_constant{name,chilled_C,mode}, selected_ppo_seed, selected_by }                    // verbatim
```
Rules for BE-G2: no recomputation, no re-ranking, no new statistics, no CI synthesis, no `evaluation_status` invention; unknown/absent stays absent; `per_scenario_test` is **excluded** from v1 of the endpoint (size, 60 episodes x policy) and may be added later by its own CCR.

## What FE-17 must follow (differences from the FE-17 prompt in the roadmap pack)
| FE-17 prompt says | Reality | Resolution |
|---|---|---|
| rows = backend `policies` | backend has dict keys; BE-G2 projects them to `policies[]` in order `rule, best_constant, ppo_seed_*` | FE renders in the array order, never sorts. |
| CI as `mean [lo, hi]` with `ci_level` | CIs only for paired differences in `decision.detail`; level comes from the BE-G2 `ci_level` (0.95, copied from the pre-registration) | FE shows paired-difference CIs only where `decision.detail` provides them, labelled "paired difference (PPO minus baseline), t-based, level <ci_level>"; if `ci_level` is absent: "level not provided". Per-policy means show "uncertainty not provided". |
| `evaluation_status` verbatim | field does not exist | Not rendered. `decision.outcome`, `decision.claim_allowed` and `decision.reason` are rendered verbatim. |
| origin of an evaluation | backend gives none today | BE-G2 adds static `origin: "simulated"`; without it the strip shows "Unverified source". |
| fixtures: A, B, C, NOT_EVALUATED, inconclusive, unsafe, data-limited | only A, B, C, NOT_EVALUATED are backend values; no A/B/C has ever been produced | Fixtures A/B/C are **synthetic shape fixtures** labelled as such (built from `decide_outcome` keys, never presented as results). `inconclusive/unsafe/data-limited` become one "unknown outcome string -> neutral" test. |
| E2E-2: submit run -> open evaluation comparison | a BC-10 run (what-if) and an evaluation (policy comparison on other synthetic episodes) are **independent**; no run references an evaluation | E2E-2 exercises both flows in one session and asserts the evaluation page does not claim to be derived from the run. |
| "Not evaluated, claim allowed: none, and no PPO row" for the repo's real data | matches the capture | This is the primary acceptance fixture. |

## To capture on the real backend once BE-G2 is merged (PowerShell)
```powershell
$base = "http://localhost:8000"; $pw = Read-Host "check-user password"
$t = (Invoke-RestMethod -Method Post -Uri "$base/auth/login" -ContentType "application/json" -Body (@{username="gscn-check";password=$pw} | ConvertTo-Json)).access_token
$h = @{ Authorization = "Bearer $t" }
$l = Invoke-RestMethod -Uri "$base/api/evaluations" -Headers $h; $l | ConvertTo-Json -Depth 6
$d = Invoke-RestMethod -Uri "$base/api/evaluations/baselines_only_0fcafef9d28fd539" -Headers $h
$d.decision.outcome; $d.decision.claim_allowed; $d.policies.policy_id    # expect NOT_EVALUATED, none, rule best_constant (no ppo)
$d | ConvertTo-Json -Depth 10 | Out-File -Encoding utf8 real-eval.json
try { Invoke-RestMethod -Uri "$base/api/evaluations/..%2F..%2Fetc" -Headers $h } catch { $_.Exception.Response.StatusCode.value__ }   # 404
curl.exe -s -o NUL -w "%{http_code}`n" "$base/api/evaluations"                                                                       # 401
Remove-Item real-eval.json
```
Acceptance of the gate: the key set of `real-eval.json` equals the committed `G-EVAL.capture-detail-baselines-only.json` produced by BE-G2, `decision` equals the capture's `decision` object byte for byte after JSON parse, and `policies` has no `ppo` row.

## Verification actually run (for this record)
- Read `reports/policy_evaluation/PREREGISTRATION.json` (keys: `config`, `metrics`, `outcome_rules` A/B/C, ...).
- Read `src/policy_evaluation.py` (`decide_outcome`, `run_evaluation`, `paired_difference`) and `scripts/eval_policies.py` (`decision` builder); parsed the repo's `results.json` and listed its keys.
- sha256: `src/policy_evaluation.py` `00d86e93bc20119a5f2147de4082ac456752bf34e65c4ecb2dc76d4d06f5c69c`; `scripts/eval_policies.py` `bcfe7711d2ce6b15a7720285b611f48b64ffbca11248bdef8f526d9dd9a15929`.
- **Not run:** any evaluation, any PPO candidate, `tests/test_policy_evaluation.py`, `tests/test_robustness_eval.py`. No endpoint was called because none exists.

## Open decisions for you
1. Approve BE-G2 as specified (read-only projection; two routes; v1 format only).
2. `outcome_definitions` and `metrics` come verbatim from `reports/policy_evaluation/PREREGISTRATION.json` (`outcome_rules` has A, B, C only; capture: `G-EVAL.capture-preregistration-v1.json`, sha256 `3339fef466ee8b30e75ddc16e6c67b6bd6bcbcb7b756a87181d0028484f5efee`). `NOT_EVALUATED` has no definition in the pre-registration; the UI shows the run's own `reason` plus "definition not provided". Decide whether to add one (it would be a pre-registration change, so not done here).
3. `ci_level` = pre-registration `config.confidence` (0.95), copied. Default: yes.
4. T30 `reports/runs/*` is not served now. Add it when a real T30 run exists, with its own capture.
5. `origin: "simulated"` is a static backend-owned label so the frontend need not infer it (otherwise the UI would have to show "Unverified source" for every evaluation). Default: yes.
