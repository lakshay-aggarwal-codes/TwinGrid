"""Owner-approved derivations only (Task 13). v5 has none: the approved list is empty, so every request is refused.

A definition is accepted for the registry only when it cites an owner approval and keeps lineage. Hard rules (Task 6
verdict A, contract section 9): temperatures are never summed; a group channel is never split, divided or equal-split
across its member racks; an additive power derivation uses only measured power channels with disjoint member sets and
its output is attributed to the union of those members (never to one rack); a derived value is named ``derived.*`` and
carries provenance ``derived``. Nothing here computes a value or reads data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import DerivationNotApproved, MappingValidationError

REGISTRY_PATH = Path(__file__).with_name("derivations_v1.json")
DEFINITION_KEYS = {
    "derived_name", "provenance", "operation", "inputs", "output_measurand", "output_unit", "output_scope",
    "output_member_source_rack_ids", "formula_id", "formula_text", "code_version", "mapping_version",
    "method_approval_ref", "approved_on",
}  # fmt: skip
SPLITTING_OPERATIONS = {"split", "divide", "equal_split", "allocate", "apportion", "share"}
SUMMING_OPERATIONS = {"sum", "add", "total"}


def validate_derivation_definition(defn: Any, registry: Any | None = None) -> list[str]:
    """``CODE: message`` errors for one derivation definition; empty list = acceptable shape (approval still the owner's)."""
    e: list[str] = []

    def add(code: str, msg: str) -> None:
        e.append(f"{code}: {msg}")

    if not isinstance(defn, dict) or set(defn) != DEFINITION_KEYS:
        add("D_KEYS", f"a derivation requires exactly {sorted(DEFINITION_KEYS)}")
        return e
    if registry is None:
        from .loader import load_mapping

        registry = load_mapping()
    if defn["provenance"] != "derived":
        add("D_PROVENANCE", "provenance must be 'derived'")
    name = defn["derived_name"]
    if not (isinstance(name, str) and name.startswith("derived.") and name not in registry.by_sensor):
        add("D_NAME", "derived_name must start with 'derived.' and never reuse a measured sensor id")
    for k in ("formula_id", "formula_text", "code_version", "method_approval_ref", "approved_on"):
        if not (isinstance(defn[k], str) and defn[k].strip()):
            add(
                "D_APPROVAL" if k in ("method_approval_ref", "approved_on") else "D_LINEAGE",
                f"{k} must be a non-empty string",
            )
    if defn["mapping_version"] != registry.mapping_version:
        add("D_LINEAGE", f"mapping_version must equal the loaded mapping version {registry.mapping_version}")
    ins = defn["inputs"]
    if not (isinstance(ins, list) and ins and all(isinstance(i, str) for i in ins)) or len(set(ins)) != len(ins):
        add("D_INPUT", "inputs must be a non-empty list of distinct sensor ids")
        return e
    ents = []
    for sid in ins:
        ent = registry.by_sensor.get(sid)
        if ent is None or ent["tier"] != "tier1" or not ent["load_in_v1"]:
            add("D_INPUT", f"{sid!r} is not a mapped tier1 measured sensor")
        else:
            ents.append(ent)
    if len(ents) != len(ins):
        return e
    measurands = {x["measurand"] for x in ents}
    if len(measurands) != 1:
        add("D_MIX", f"inputs mix measurands {sorted(measurands)}")
        return e
    m = next(iter(measurands))
    op = str(defn["operation"]).lower()
    group_inputs = [x for x in ents if x["attribution"]["scope"] == "rack_group"]
    if op in SPLITTING_OPERATIONS and group_inputs:
        add("D_GROUP_SPLIT", "a group channel is never split, divided or allocated across its member racks")
    if m == "temperature" and (op in SUMMING_OPERATIONS or len(ents) > 1 and op not in ("mean", "min", "max")):
        add("D_TEMP_SUM", "temperatures are never summed")
    if group_inputs and defn["output_scope"] != "rack_group":
        add("D_GROUP_SPLIT", "a value derived from a group input stays rack_group; it never becomes per-rack")
    if op in SUMMING_OPERATIONS and m == "power":
        sets = [set(x["attribution"]["member_source_rack_ids"]) for x in ents]
        union = set().union(*sets)
        if sum(len(s) for s in sets) != len(union):
            add("D_POWER_ADD", "additive power needs input channels with disjoint member sets (no double counting)")
        want = sorted(union, key=int)
        if defn["output_member_source_rack_ids"] != want:
            add("D_POWER_ADD", f"output members must be the union {want}")
        if defn["output_scope"] != ("rack_group" if len(want) > 1 else "rack") or defn["output_unit"] != "W":
            add("D_POWER_ADD", "output scope must reflect the union and the unit must be W")
    elif op in SUMMING_OPERATIONS and m != "power":
        add("D_TEMP_SUM", f"only measured power may be added; {m} is not additive")
    if defn["output_measurand"] != m and op in SUMMING_OPERATIONS:
        add("D_LINEAGE", "output_measurand must equal the input measurand for a sum")
    return e


def load_derivation_registry(path: Path | None = None, registry: Any | None = None) -> dict[str, Any]:
    doc = json.loads((path or REGISTRY_PATH).read_text(encoding="utf-8"))
    if not (
        isinstance(doc, dict) and isinstance(doc.get("approved"), list) and isinstance(doc.get("registry_version"), int)
    ):
        raise MappingValidationError(["D_KEYS: registry requires registry_version and an approved list"])
    errs: list[str] = []
    seen: set[str] = set()
    for d in doc["approved"]:
        errs += validate_derivation_definition(d, registry)
        n = d.get("derived_name") if isinstance(d, dict) else None
        if n in seen:
            errs.append(f"D_NAME: duplicate derivation {n!r}")
        seen.add(n)
    if errs:
        raise MappingValidationError(errs)
    return doc


def approved_derivation_ids(path: Path | None = None) -> list[str]:
    return [d["derived_name"] for d in load_derivation_registry(path)["approved"]]


def require_approved(derived_name: str, path: Path | None = None) -> dict[str, Any]:
    """The approved definition, or DerivationNotApproved. The only door to a derived value."""
    for d in load_derivation_registry(path)["approved"]:
        if d["derived_name"] == derived_name:
            return d
    raise DerivationNotApproved(f"derived value {derived_name!r} has no owner-approved derivation (approved: none)")
