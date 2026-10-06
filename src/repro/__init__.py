"""Reproducibility run framework (T24, contract section 11).

    scripts/run_experiment.py   run an experiment -> reports/runs/<run_id>/
    scripts/repro.py verify     recompute input hashes, regenerate tables/figures/REPORT.md, diff

The guarantee, stated precisely: *reported results can be re-derived in the same environment
from recorded code, configuration, data hashes and seeds* (determinism level L1). Results on
other platforms are expected to agree numerically within tolerance; they are NOT claimed to be
bit-identical (level L2).
"""

RUN_MANIFEST_VERSION = 1
RESULTS_SCHEMA = "twingrid-results/1"
DETERMINISM_LEVEL = "L1"
