"""Task 13: source identity mapping for Danish AAU v5 (data-free; no raw data is read).

The versioned mapping file attaches every source channel to a stable identity with evidence, counts unmapped
entities, and carries the rules that stop a group channel from becoming a per-rack value. It assigns no value,
resolves no duplicate (Task 12) and creates no database row (Task 15).
"""

from .derivations import (
    approved_derivation_ids,
    load_derivation_registry,
    require_approved,
    validate_derivation_definition,
)
from .errors import (
    AmbiguousMappingError,
    DerivationNotApproved,
    MappingError,
    MappingValidationError,
    UnmappedEntityError,
)
from .loader import MappingRegistry, load_mapping, mapping_file_sha256
from .validate import validate_mapping
from .views import (
    attribution_block,
    mapping_block,
    rack_measurand_status,
    rack_view_parts,
    sensor_list_items,
)

__all__ = [
    "AmbiguousMappingError",
    "DerivationNotApproved",
    "MappingError",
    "MappingRegistry",
    "MappingValidationError",
    "UnmappedEntityError",
    "approved_derivation_ids",
    "attribution_block",
    "load_derivation_registry",
    "load_mapping",
    "mapping_block",
    "mapping_file_sha256",
    "rack_measurand_status",
    "rack_view_parts",
    "require_approved",
    "sensor_list_items",
    "validate_derivation_definition",
    "validate_mapping",
]
