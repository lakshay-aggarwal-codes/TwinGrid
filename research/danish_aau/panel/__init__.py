"""Task 14: reproducible source-to-clean-panel command for Danish AAU v5 (read-only on the raw files).

Integrates the Task 11 adapter, the Task 12 cleaning/L1 writer and the Task 13 mapping and approved derivation into one
deterministic build: measured Tier 1 observations (L1), a separate derived series, per-channel provenance and quality, and
a manifest of hashes, counts and dispositions. Outputs are local-only (licence/redistribution not approved).
"""

from .build import PANEL_FORMAT, build_panel, compare_trees, rerun_check, verify_panel
from .errors import PanelError

__all__ = ["PANEL_FORMAT", "PanelError", "build_panel", "compare_trees", "rerun_check", "verify_panel"]
