"""Contract-shaped helpers over the mapping, for Tasks 12, 14 and 16. Pure functions; no data, no I/O after load."""

from __future__ import annotations

import copy
from functools import lru_cache
from typing import Any

from .errors import UnmappedEntityError
from .loader import MappingRegistry, load_mapping

_MEASURANDS = ("temperature", "power", "air_speed")


@lru_cache(maxsize=1)
def default_registry() -> MappingRegistry:
    return load_mapping()


def _reg(registry: MappingRegistry | None) -> MappingRegistry:
    return registry or default_registry()


def mapping_block(sensor_external_id: str, registry: MappingRegistry | None = None) -> dict[str, Any]:
    """The exact six-key ``mapping`` object of a contract telemetry record."""
    x = _reg(registry).sensor(sensor_external_id)
    return {
        "mapping_id": x["mapping_id"],
        "mapping_version": x["mapping_version"],
        "method": x["method"],
        "label_evidence": x["label_evidence"],
        "valid_time_status": x["valid_time_status"],
        "applied_uniformly_over_window": x["applied_uniformly_over_window"],
    }


def attribution_block(sensor_external_id: str, registry: MappingRegistry | None = None) -> dict[str, Any]:
    """The exact ``attribution`` object (copy; callers cannot mutate the mapping)."""
    return copy.deepcopy(_reg(registry).sensor(sensor_external_id)["attribution"])


def sensor_list_items(registry: MappingRegistry | None = None, *, load_in_v1_only: bool = True) -> list[dict[str, Any]]:
    """Items for the contract ``sensor_list`` envelope. Deferred entities have no sensor id and never appear."""
    out = []
    for x in _reg(registry).doc["entities"]:
        if x["sensor_external_id"] is None or (load_in_v1_only and not x["load_in_v1"]):
            continue
        out.append(
            {
                "sensor_external_id": x["sensor_external_id"],
                "asset_external_id": x["asset_external_id"],
                "measurand": x["measurand"],
                "unit": x["unit"],
                "mapping_id": x["mapping_id"],
                "mapping_version": x["mapping_version"],
                "method": x["method"],
                "measurand_status": "sensor_present",
            }
        )
    return out


def _temp_sort(x: dict[str, Any]) -> tuple[int, int]:
    parts = x["source_column"].split()
    return int(parts[2]), int(parts[4])


def rack_measurand_status(
    source_rack_id: str, measurand: str, registry: MappingRegistry | None = None
) -> tuple[str, list[str]]:
    """(measurand_status, sensor ids) for one rack. A group channel is ``group_channel_only``, never a rack value."""
    reg = _reg(registry)
    if source_rack_id not in reg.racks:
        raise UnmappedEntityError(f"no rack {source_rack_id!r} in the mapping")
    if measurand not in _MEASURANDS:
        raise UnmappedEntityError(f"measurand {measurand!r} is not one of {_MEASURANDS}")
    if measurand == "temperature":
        ids = [
            x["sensor_external_id"]
            for x in sorted(
                (
                    e
                    for e in reg.entities(load_in_v1=True)
                    if e["source_rack_id"] == source_rack_id and e["measurand"] == "temperature"
                ),
                key=_temp_sort,
            )
        ]
        return ("sensor_present", ids) if ids else ("no_sensor_for_asset", [])
    if measurand == "power":
        for x in reg.entities(load_in_v1=True):
            if x["measurand"] == "power" and source_rack_id in x["attribution"]["member_source_rack_ids"]:
                return (
                    "sensor_present" if len(x["attribution"]["member_source_rack_ids"]) == 1 else "group_channel_only",
                    [x["sensor_external_id"]],
                )
        return "no_sensor_for_asset", []
    return "no_sensor_for_asset", []  # air speed has no rack attribution


def rack_view_parts(source_rack_id: str, registry: MappingRegistry | None = None) -> dict[str, Any]:
    """Identity half of a contract ``rack_view``: temperature sensor entries and the power pointer (no value, no record).

    The serving layer (Task 16) adds ``record`` values; a group channel always yields ``value: null`` and the full
    member list, and a single-rack port yields only its sensor id.
    """
    reg = _reg(registry)
    status, tids = rack_measurand_status(source_rack_id, "temperature", reg)
    temps = []
    for sid in tids:
        x = reg.sensor(sid)
        temps.append(
            {
                "sensor_external_id": sid,
                "source_label": x["source_label"],
                "source_position_word": x["source_position_word"],
                "label_evidence": x["label_evidence"],
            }
        )
    pstatus, pids = rack_measurand_status(source_rack_id, "power", reg)
    if pstatus == "group_channel_only":
        a = reg.sensor(pids[0])["attribution"]
        power: dict[str, Any] = {
            "kind": "group_pointer",
            "sensor_external_id": pids[0],
            "member_source_rack_ids": list(a["member_source_rack_ids"]),
            "value": None,
            "split_allowed": False,
        }
    elif pstatus == "sensor_present":
        power = {"kind": "single_rack_port", "sensor_external_id": pids[0]}
    else:
        power = {"kind": "not_available", "reason": "no_sensor_for_asset"}
    return {
        "source_rack_id": source_rack_id,
        "asset_external_id": reg.racks[source_rack_id]["asset_external_id"],
        "temperature_sensors": temps,
        "power": power,
    }
