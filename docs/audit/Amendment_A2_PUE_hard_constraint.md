# Amendment A2 — the PUE limit is a counted, absolute hard constraint (TG-A-12)

Companion to amendment A1 (all temperature limits absolute; see `TwinGrid_Issue_Register.md`, TG-A-02).

## What changed
* `src/policy_evaluation.py`: new metric `pue_over_max_steps` = steps with `not pue <= SAFETY_ENVELOPE.pue_max` (2.0).
  The comparison is negated, exactly like `SafetyEnvelope.violations`, so a NaN PUE counts as a violation and a PUE
  exactly at the limit does not. It is the fourth member of `HARD_CONSTRAINT_METRICS`, so it enters
  `hard_constraint_total`, the selected candidate's envelope check (outcome A needs 0), the baseline-replacement check
  (outcome C needs 0), the report table and the pre-registered metric list.
* `OUTCOME_RULES["A"]` and `["C"]` now name "PUE-over-limit" steps and amendments A1 and A2.
* `src/baselines/tuning.py`: feasibility = zero steps on all four hard metrics (`FEASIBILITY_RULE` text changed).
* `src/baselines/evaluation.py::load_baselines`: a config whose recorded `tuning.feasibility_rule` differs from the
  running one is refused as stale (`tuning.feasibility_rule`), so no baseline is run that was never checked against PUE.
* Schema: `policy_evaluation.SCHEMA_VERSION` 1 -> 2 for newly written `results.json` / `PREREGISTRATION.json`.
  `API evaluation_service` accepts 1 and 2 and adds the additive key `hard_constraints`
  (`counted`, `not_measured`, `note`). A schema-1 file is served unchanged; its PUE limit is `not_measured`,
  which is NOT "zero violations". Nothing back-fills a zero.

## Disclosure (same standard as A1)
A2 changes a pre-registered decision rule. No PPO candidate has been scored under any rule (decision `NOT_EVALUATED`),
so the amendment cannot have been fitted to a PPO result. It was made after the physics-1 baselines (`baselines-v3`)
had been run; the baselines are comparators, and the sandbox measurement below was taken after the change was decided.
The registered `config` (and therefore `preregistration_sha256`) is unchanged: the hash covers `config` only. The
metric list and `outcome_rules` stored beside it in `PREREGISTRATION.json` are outside the hash and are rewritten on
re-registration.

## Frozen legacy-0 report
`reports/policy_evaluation/baselines_only_0fcafef9d28fd539/` is untouched (SHA-256 of `results.json` pinned in
`tests/test_pue_hard_constraint.py`). It is schema 1: it never counted PUE, its recorded outcome rule predates A1/A2, and
re-running the legacy protocol with this code would write schema 2 (a different file). It stays a frozen historical
artifact; its original nine metrics still reproduce (`tests/test_audit_regressions.py`).

## Not covered
`scripts/eval_policies.py` has its own robustness criterion (`ENVELOPE_METRICS`: outlet and inlet-over only). That is a
separate pre-registered protocol and was not changed here.
