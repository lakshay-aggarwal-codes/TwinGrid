"""Fleet ranking. PURE.

Lower is better for every ranked metric (PUE, carbon, simulated alert conditions). Ties share a rank (1, 2, 2, 4).
The overall order is the sum of the three ranks, ties broken by site id so the order is always the same.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

METRICS = ("pue", "carbon_gco2_per_step", "alert_conditions")


def competition_ranks(values: Sequence[float]) -> list[int]:
    """Rank of each value (1 = lowest); equal values (to 1e-9 relative) share the lowest rank of the group."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0] * len(values)
    for pos, i in enumerate(order):
        if pos > 0 and math.isclose(values[i], values[order[pos - 1]], rel_tol=1e-9, abs_tol=1e-12):
            ranks[i] = ranks[order[pos - 1]]
        else:
            ranks[i] = pos + 1
    return ranks


def alert_conditions(state: Mapping[str, Any], *, outlet_max: float, inlet_min: float, inlet_max: float) -> list[str]:
    """Rule checks on a SIMULATED state. These are not recorded alerts; they are the conditions that would raise one."""
    found: list[str] = []
    if float(state["server_outlet_temp_C"]) > outlet_max:
        found.append("outlet_over_limit")
    if float(state["server_inlet_temp_C"]) > inlet_max:
        found.append("inlet_over_max")
    if float(state["server_inlet_temp_C"]) < inlet_min:
        found.append("inlet_under_min")
    if bool(state.get("drought_override_active")):
        found.append("drought_override")
    return found


def rank_fleet(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Add ``rank`` (per metric) and ``overall_rank`` to each row; return the rows ordered by overall rank."""
    if not rows:
        return []
    per_metric = {m: competition_ranks([float(r[m]) for r in rows]) for m in METRICS}
    out = []
    for i, r in enumerate(rows):
        total = sum(per_metric[m][i] for m in METRICS)
        out.append({**r, "rank": {m: per_metric[m][i] for m in METRICS}, "rank_sum": total})
    out.sort(key=lambda r: (r["rank_sum"], r["id"]))
    overall = competition_ranks([float(r["rank_sum"]) for r in out])
    for r, o in zip(out, overall):
        r["overall_rank"] = o
    return out
