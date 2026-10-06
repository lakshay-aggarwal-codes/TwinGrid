"""Deterministic baselines v2 (T28, contract 13.8): Rule, Constant, Lookup, PID.

    policies.py    the four policies (pure, same actuator limits)
    config.py      configs/baselines/<name>.json: parameters, tuning scenario ids, tuner version, lineage
    tuning.py      validation-only tuners (exhaustive grids, lexicographic ties, envelope never loosened)
    evaluation.py  held-out evaluation + the T24 experiment ``baselines``
    cli.py         ``python -m src.baselines.cli tune | run | verify``

This package imports nothing heavy at package level: ``src.policy_evaluation`` imports
``src.baselines.policies`` and the tuners import ``src.policy_evaluation``, so only ``policies`` may be
imported from there.
"""
