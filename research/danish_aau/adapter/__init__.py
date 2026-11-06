"""Task 11: read-only source adapter for the 16 Danish AAU v5 CSV files (L0 -> parsed cells with stable references).

Thin layer over ``evaluation.data_layer`` (it reuses the two-pass reader and the read-only guard; no second reader).
It adds: the explicit 16-file/column schema, deterministic discovery with manifest checks, contract-shaped source
references, and rejection of unexpected files, columns or units. It cleans nothing (Task 12) and maps nothing to racks
(Task 13).
"""

from .errors import AdapterDiscoveryError, AdapterError, AdapterSchemaError
from .reader import AdapterReader, ParsedCell, make_source_ref
from .schema import FILE_SPECS, FileSpec, spec_for_key
from .source import AdapterSource, discover_all

__all__ = [
    "AdapterDiscoveryError",
    "AdapterError",
    "AdapterSchemaError",
    "AdapterReader",
    "ParsedCell",
    "make_source_ref",
    "FILE_SPECS",
    "FileSpec",
    "spec_for_key",
    "AdapterSource",
    "discover_all",
]
