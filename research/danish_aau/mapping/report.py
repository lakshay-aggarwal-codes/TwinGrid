"""Data-free summary of the mapping: counts, unmapped and deferred entities, evidence provenance."""

from __future__ import annotations

from typing import Any

from .loader import MappingRegistry


def build_report(reg: MappingRegistry) -> dict[str, Any]:
    ents = reg.doc["entities"]
    label: dict[str, int] = {}
    status: dict[str, int] = {}
    for e in ents:
        label[e["label_evidence"]] = label.get(e["label_evidence"], 0) + 1
        status[e["evidence_status"]] = status.get(e["evidence_status"], 0) + 1
    by_tier: dict[str, int] = {}
    for e in ents:
        by_tier[e["tier"]] = by_tier.get(e["tier"], 0) + 1
    mf = reg.doc["mapping_file"]
    return {
        "tool": "danish_aau.mapping report 1",
        "mapping_file_sha256_lf_normalised": reg.sha256,
        "mapping_version": reg.mapping_version,
        "mapping_status": mf["status"],
        "decided_by": mf["decided_by"],
        "protocol_sha256": mf["protocol_sha256"],
        "task7_adr_sha256_lf_normalised": mf["task7_adr_sha256_lf_normalised"],
        "counts": reg.counts(),
        "by_tier": dict(sorted(by_tier.items())),
        "label_evidence": dict(sorted(label.items())),
        "evidence_status": dict(sorted(status.items())),
        "racks": len(reg.doc["racks"]),
        "power_ports": len(reg.doc["power_ports"]),
        "unmapped_entities": [e["entity_id"] for e in ents if e["mapping_state"] == "unmapped"],
        "deferred_entities": [e["entity_id"] for e in ents if e["tier"] == "deferred"],
        "excluded_items": [i["item"] for i in reg.doc["excluded_items"]],
        "derivations_approved": 0,
        "time": reg.doc["time"],
    }
