"""Task 12: deterministic cleaning and time handling for Danish AAU v5 (read-only; uses the Task 11 adapter reader)."""

from .catalogue import CATALOGUE, ROW_DISPOSITIONS, validate_catalogue
from .config import CleanConfig
from .errors import CleaningError
from .flags import apply_flags, flatline_report
from .l1 import verify_l1, write_l1
from .ledger import ledger_entries, ledger_summary, reconcile
from .resolve import CleanResult, RawRowIn, clean_file, clean_rows
from .tier1 import RACK_PROBE_COLUMNS, TIER1_COLUMNS, column_slug

__all__ = [
    "CATALOGUE",
    "RACK_PROBE_COLUMNS",
    "ROW_DISPOSITIONS",
    "TIER1_COLUMNS",
    "CleanConfig",
    "CleanResult",
    "CleaningError",
    "RawRowIn",
    "apply_flags",
    "clean_file",
    "clean_rows",
    "column_slug",
    "flatline_report",
    "ledger_entries",
    "ledger_summary",
    "reconcile",
    "validate_catalogue",
    "verify_l1",
    "write_l1",
]
