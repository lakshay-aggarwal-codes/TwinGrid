"""Stage ``prepare`` (Phase 2): L1 TimeIndex, declared L2 policies, streaming proof, auditable sidecars.

The implementation lives in ``data_layer.prepare`` and is imported lazily, so the Phase 1 commands (doctor, inventory,
preflight) keep working without pandas.
"""

from __future__ import annotations

from typing import Any

from ..runner import RunContext, register_stage


class PrepareStage:
    name = "prepare"

    def run(self, ctx: RunContext) -> dict[str, Any]:
        from ..data_layer.prepare import run_prepare

        return run_prepare(ctx)


register_stage(PrepareStage())
