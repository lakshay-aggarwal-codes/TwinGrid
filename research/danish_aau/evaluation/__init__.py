"""Offline evaluation harness: TwinGrid simulated outputs vs the Danish AAU v5 server-room measurements.

ISOLATION CONTRACT (enforced by tests/evaluation/test_eval_isolation.py):
  * nothing in production (src/, api/, models/, ...) imports this package;
  * this package's core modules never import ``src``, ``api``, ``models``, ``database`` or any DB/web library
    (``import src`` reconfigures the root logger and writes ``logs/``). The one future exception is the Phase 3
    ``twin_adapter`` module, which must import ``src`` lazily and is the only allow-listed file;
  * raw dataset files are opened read-only and fingerprinted before/after every run.

PHASE 1: harness foundation (config, path anchoring, inventory, manifest, CLI).
PHASE 2: ``data_layer`` (L1 reader/TimeIndex, L2 policies, alignment engine). Still no comparison, metrics, calibration
or training, and no ``src`` import.
"""

HARNESS_VERSION = "0.2.0-phase2"
HARNESS_PHASE = 2
