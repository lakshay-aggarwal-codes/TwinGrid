"""Load the versioned mapping file and index it. Loading validates; an invalid mapping never loads."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import AmbiguousMappingError, MappingValidationError, UnmappedEntityError
from .validate import validate_mapping

MAPPING_PATH = Path(__file__).with_name("danish_aau_v5_mapping_v1.json")


def mapping_file_sha256(path: Path | None = None) -> str:
    """SHA-256 of the file with CR removed (LF-normalised, the convention used in every task report)."""
    raw = (path or MAPPING_PATH).read_bytes().replace(b"\r", b"")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class MappingRegistry:
    doc: dict[str, Any]
    sha256: str
    by_entity: dict[str, dict[str, Any]]
    by_sensor: dict[str, dict[str, Any]]
    by_column: dict[tuple[str, str], dict[str, Any]]
    racks: dict[str, dict[str, Any]]

    @property
    def mapping_version(self) -> int:
        return int(self.doc["mapping_file"]["mapping_version"])

    def entity(self, entity_id: str) -> dict[str, Any]:
        try:
            return self.by_entity[entity_id]
        except KeyError:
            raise UnmappedEntityError(f"no mapping entry for entity id {entity_id!r}") from None

    def sensor(self, sensor_external_id: str) -> dict[str, Any]:
        try:
            return self.by_sensor[sensor_external_id]
        except KeyError:
            raise UnmappedEntityError(f"no mapping entry for sensor {sensor_external_id!r}") from None

    def for_column(self, file_family: str, column: str) -> dict[str, Any]:
        """The identity of one CSV column. Raises (never guesses) when the column is unknown."""
        try:
            return self.by_column[(file_family, column)]
        except KeyError:
            raise UnmappedEntityError(
                f"column {column!r} of file family {file_family!r} has no mapping entry"
            ) from None

    def entities(self, *, tier: str | None = None, load_in_v1: bool | None = None) -> list[dict[str, Any]]:
        out = list(self.doc["entities"])
        if tier is not None:
            out = [e for e in out if e["tier"] == tier]
        if load_in_v1 is not None:
            out = [e for e in out if e["load_in_v1"] is load_in_v1]
        return out

    def counts(self) -> dict[str, Any]:
        ents = self.doc["entities"]
        by_state: dict[str, int] = {}
        by_class: dict[str, int] = {}
        for e in ents:
            by_state[e["mapping_state"]] = by_state.get(e["mapping_state"], 0) + 1
            by_class[e["source_entity_class"]] = by_class.get(e["source_entity_class"], 0) + 1
        return {
            "entities": len(ents),
            "by_mapping_state": dict(sorted(by_state.items())),
            "by_class": dict(sorted(by_class.items())),
            "unmapped": by_state.get("unmapped", 0),
            "tier1_unmapped": sum(1 for e in ents if e["tier"] == "tier1" and e["mapping_state"] != "mapped"),
            "excluded_items": len(self.doc["excluded_items"]),
        }


def build_registry(doc: dict[str, Any], sha256: str) -> MappingRegistry:
    by_entity: dict[str, dict[str, Any]] = {}
    by_sensor: dict[str, dict[str, Any]] = {}
    by_column: dict[tuple[str, str], dict[str, Any]] = {}
    for e in doc["entities"]:
        if e["entity_id"] in by_entity:
            raise AmbiguousMappingError(f"duplicate entity id {e['entity_id']!r}")
        by_entity[e["entity_id"]] = e
        if e["sensor_external_id"] is not None:
            by_sensor[e["sensor_external_id"]] = e
        key = (e["source_file_family"], e["source_column"])
        if key in by_column:
            raise AmbiguousMappingError(f"column {key!r} maps to more than one entity")
        by_column[key] = e
    racks = {r["source_rack_id"]: r for r in doc["racks"]}
    return MappingRegistry(doc, sha256, by_entity, by_sensor, by_column, racks)


def load_mapping(path: Path | None = None, *, doc: dict[str, Any] | None = None) -> MappingRegistry:
    """Load and validate. ``doc`` lets tests pass an in-memory document; production code passes nothing."""
    p = path or MAPPING_PATH
    if doc is None:
        doc = json.loads(p.read_text(encoding="utf-8"))
        sha = mapping_file_sha256(p)
    else:
        sha = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()
    errors = validate_mapping(doc)
    if errors:
        raise MappingValidationError(errors)
    return build_registry(doc, sha)
