"""Task 15: read-only dataset bundle for the Danish AAU v5 import (Task 9 ADR r4, option D).

Runtime side (``reader``): stdlib ``sqlite3`` only, opened read-only. Build side (``loader``, ``verify``): reads a Task 14
panel and writes the bundle; needs numpy and pandas; imports nothing from ``research``. Nothing here writes ``telemetry_sample`` or any shared
table, and nothing converts a timestamp to UTC.
"""

from .errors import BundleError, BundleNotFound
from .reader import dataset_version, derived_history, entities, format_ticks, history, open_readonly

__all__ = [
    "BundleError",
    "BundleNotFound",
    "dataset_version",
    "derived_history",
    "entities",
    "format_ticks",
    "history",
    "open_readonly",
]
