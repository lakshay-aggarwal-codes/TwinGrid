"""Load and validate protocol_v1.toml. Thresholds live ONLY in the TOML; code never hard-codes them."""

from __future__ import annotations

import fnmatch
import hashlib
import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

PROTOCOL_PATH = Path(__file__).with_name("protocol_v1.toml")
LOCK_PATH = Path(__file__).with_name("protocol_v1.lock.json")

REQUIRED_SECTIONS = (
    "status",
    "inputs",
    "time",
    "rounding",
    "resolution",
    "duplicates",
    "dispositions",
    "screening",
    "groups",
)
FORBIDDEN_TIE_RULES = ("first", "last", "mean", "median", "min", "max", "nearest", "hash")


class ProtocolError(ValueError):
    """The protocol file is malformed or breaks a Master Handoff rule."""


class ProtocolIncomplete(ProtocolError):
    """A value the source does not document has not been supplied yet (e.g. a measurement resolution)."""


def normalised_bytes(path: Path) -> bytes:
    """File bytes with BOM removed and CRLF/CR -> LF, so the hash is identical on Windows and Linux checkouts."""
    data = Path(path).read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def protocol_sha256(path: Path = PROTOCOL_PATH) -> str:
    return hashlib.sha256(normalised_bytes(path)).hexdigest()


@dataclass(frozen=True)
class Protocol:
    data: dict[str, Any]
    path: Path | None = None

    # ---- access -------------------------------------------------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    @property
    def thresholds(self) -> dict[str, Any]:
        return self.data["screening"]["thresholds"]

    def family(self, name: str = "power_temperature") -> dict[str, Any]:
        return self.data["screening"]["family"][name]

    # ---- resolution ---------------------------------------------------------------------------------------------
    def resolution_class(self, column: str, file: str | None = None) -> str:
        """Name of the resolution class for a CSV column (and optionally file); unmatched columns are an error."""
        hits = []
        for name, spec in self.data["resolution"].items():
            if any(fnmatch.fnmatchcase(column, pat) for pat in spec.get("match_columns", [])) or (
                file is not None and file in spec.get("match_files", [])
            ):
                hits.append(name)
        if len(hits) != 1:
            raise ProtocolError(f"column {column!r} (file {file!r}) matches {len(hits)} resolution classes: {hits}")
        return hits[0]

    def resolution(self, column: str, file: str | None = None) -> Decimal:
        name = self.resolution_class(column, file)
        spec = self.data["resolution"][name]
        if "decimals" not in spec:
            raise ProtocolIncomplete(f"resolution.{name}.decimals is not supplied (the source does not document it)")
        decimals = spec["decimals"]
        if isinstance(decimals, bool) or not isinstance(decimals, int) or decimals < -6 or decimals > 12:
            raise ProtocolError(f"resolution.{name}.decimals must be an integer in [-6, 12], got {decimals!r}")
        return Decimal(1).scaleb(-decimals)

    def with_overrides(self, **sections: dict[str, Any]) -> Protocol:
        """Copy with nested dict overrides (tests use this for SYNTHETIC resolutions; it never touches the file)."""
        merged = _deep_merge(self.data, sections)
        return Protocol(merged, self.path)

    # ---- review state -------------------------------------------------------------------------------------------
    def open_items(self) -> list[str]:
        items = []
        for name, spec in self.data["resolution"].items():
            if "decimals" not in spec:
                items.append(f"resolution.{name}.decimals not supplied")
            if not spec.get("basis"):
                items.append(f"resolution.{name}.basis (source document) not supplied")
        if not self.data["inputs"].get("task4b_reviewed"):
            items.append("inputs.task4b_reviewed is false (repeated-timestamp structure report not reviewed)")
        st = self.data["status"]
        if st.get("approval_ck1") != "approved":
            items.append("status.approval_ck1 is not 'approved' (owner CK-1)")
        else:
            for key in ("approved_by", "approved_on"):
                if not st.get(key):
                    items.append(f"status.{key} is empty")
        return items


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def validate(data: dict[str, Any]) -> None:
    """Structural checks plus the non-negotiable Master Handoff rules (never disabled by configuration)."""
    for sec in REQUIRED_SECTIONS:
        if sec not in data:
            raise ProtocolError(f"missing section [{sec}]")
    if data["time"]["timezone"] != "undeclared" and not data["time"].get("timezone_basis"):
        raise ProtocolError("time.timezone declared without time.timezone_basis")
    if data["time"]["interpolation"] != "none" or data["time"]["imputation"] != "none":
        raise ProtocolError("interpolation/imputation must be 'none' until the owner approves a policy")
    if data["rounding"]["mode"] != "ROUND_HALF_EVEN":
        raise ProtocolError("rounding.mode must be ROUND_HALF_EVEN")
    dup = data["duplicates"]
    if dup["tie_policy"] != "missing" or dup["tie_reason"] != "conflict_unresolved_tie":
        raise ProtocolError("a full tie must become missing with reason conflict_unresolved_tie")
    allowed = {"quality_rank", "source_version", "ingestion_timestamp_tz_aware"}
    for f in dup["authority_fields"]:
        if f.get("name") not in allowed or f.get("direction") not in {"lower_wins", "higher_wins"}:
            raise ProtocolError(f"authority field not allowed or direction missing: {f!r}")
    names = [f["name"] for f in dup["authority_fields"]]
    order = ["quality_rank", "source_version", "ingestion_timestamp_tz_aware"]
    if names != sorted(names, key=order.index):
        raise ProtocolError("authority_fields must follow quality rank -> source version -> ingestion timestamp")
    if data["screening"]["cross_cadence"] != "not_comparable":
        raise ProtocolError("series of different cadence must not be resampled")
    if set(data["groups"]["merge_dispositions"]) != {
        "confirmed_duplicate_broadcast",
        "documented_shared_sensor",
        "unresolved",
    }:
        raise ProtocolError("unresolved pairs must stay clustered conservatively")
    th = data["screening"]["thresholds"]
    if not (th["l1_level_correlation"] <= th["l2_diff_correlation"] <= th["l3_equal_fraction"] <= 1.0):
        raise ProtocolError("threshold levels must be ordered l1 <= l2 <= l3")
    if data["screening"]["min_overlap_samples"] < 2:
        raise ProtocolError("min_overlap_samples must be >= 2")


def load_protocol(path: Path = PROTOCOL_PATH) -> Protocol:
    path = Path(path)
    data = tomllib.loads(normalised_bytes(path).decode("utf-8"))
    validate(data)
    return Protocol(data, path)
