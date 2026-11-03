"""Stage ``preflight``: can the harness run here, and does the local dataset look like the one the context
document describes? Header-level facts only; no data values are read or interpreted.

Status: failed -> raw directory missing/unreadable; warn -> directory present but a registered file is missing,
ambiguous or differs from the REPORTED (unverified) expectations; ok -> everything registered matches.
"""

from __future__ import annotations

from typing import Any

from ..inventory import inventory_raw
from ..runner import RunContext, register_stage


class PreflightStage:
    name = "preflight"

    def run(self, ctx: RunContext) -> dict[str, Any]:
        inv = inventory_raw(
            ctx.raw_dir,
            ctx.registry,
            count_rows=ctx.count_rows,
            hash_files=ctx.config.integrity.hash_inputs,
        )
        readiness = ctx.config.readiness()
        problems: list[str] = []
        if not inv["raw_dir_exists"]:
            status = "failed"
            problems.append("raw dataset directory does not exist (set --raw-dir or TWINGRID_AAU_RAW_DIR)")
        elif inv["summary"]["all_registered_match"]:
            status = "ok"
        else:
            status = "warn"
            s = inv["summary"]
            problems.append(
                f"registered files: match={s['n_match']} mismatch={s['n_mismatch']} missing={s['n_missing']} "
                f"ambiguous={s['n_ambiguous']} (expectations are reported by the context document, unverified)"
            )
        return {
            "status": status,
            "problems": problems,
            "inventory": inv,
            "readiness": readiness,
            "data_kind": "synthetic_fixture" if ctx.config.dataset.is_synthetic_fixture else "reported_real_dataset",
        }


register_stage(PreflightStage())
