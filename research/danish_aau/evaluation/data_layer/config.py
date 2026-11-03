"""Phase 2 data configuration (``config/data.toml``), parsed strictly like the Phase 1 config.

It holds reader settings, per-file channel declarations and the Phase 2 policy decisions. Unknown keys are errors.
The duplicate policy decision is made HERE for Phase 2 (primary: ``keep_all_ordered``); Phase 1's
``[policies].duplicate_timestamps`` is cross-checked, never silently overridden (see ``resolve_duplicate_policy``).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .. import _reuse
from .errors import DataConfigError
from .vocabulary import PolicyId, TimestampState

SCHEMA_VERSION = 1
DEFAULT_CHUNKSIZE = 50_000
_KEY = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_TZ_TOKENS = ("%z", "%Z")
REJECTED_DUPLICATE_POLICIES = frozenset(
    {"mean", "average", "avg", "first", "last", "keep_first", "keep_last", "drop", "dedupe"}
)
SENSITIVITY_POLICIES = (PolicyId.EXCLUDE_AMBIGUOUS,)
# D3 authorised exactly these four. "first"/"last" would silently pick one of several observations; they do not exist.
KNOWN_REDUCERS = ("count", "min", "max", "mean")


@dataclass(frozen=True)
class ReaderSection:
    chunksize: int = DEFAULT_CHUNKSIZE
    encoding: str = "utf-8-sig"
    delimiter: str = ""  # "" -> detect from the header with the Phase 1 detector; ambiguous -> error
    timestamp_formats: tuple[str, ...] = ("%Y-%m-%d %H:%M:%S",)
    strip_whitespace: bool = True
    na_values: tuple[str, ...] = ("",)
    non_numeric: str = "raise"  # raise | flag
    materialise_cell_limit: int = 5_000_000
    verify_stream: bool = True  # the prepare stage streams every measurement column once to prove the reader works


@dataclass(frozen=True)
class TimestampSection:
    state: str = TimestampState.NAIVE_UNSPECIFIED.value


@dataclass(frozen=True)
class PolicySection:
    duplicates: str = PolicyId.KEEP_ALL_ORDERED
    empty_rows: str = PolicyId.EXCLUDE_EMPTY_ROWS
    approved_sensitivity: tuple[str, ...] = ()  # e.g. ("exclude_ambiguous"); empty = nothing approved
    approved_bucket_reducers: tuple[str, ...] = ()  # empty = no bucket reduction allowed ("mean" is NOT approved)


@dataclass(frozen=True)
class WindowSection:
    """The 25% experiment window as naive text. Used ONLY for in-window cross-checks against recorded findings."""

    start: str = "2024-09-17 09:40:00"
    end: str = "2024-09-18 10:55:00"


@dataclass(frozen=True)
class OutputSection:
    write_time_index: bool = True
    write_duplicate_ledger: bool = True


@dataclass(frozen=True)
class FileSection:
    measurement_columns: tuple[str, ...] = ()  # empty -> every non-timestamp column of the file
    timestamp_formats: tuple[str, ...] = ()  # empty -> the [reader] formats


@dataclass(frozen=True)
class DataConfig:
    schema_version: int = SCHEMA_VERSION
    reader: ReaderSection = field(default_factory=ReaderSection)
    timestamps: TimestampSection = field(default_factory=TimestampSection)
    policies: PolicySection = field(default_factory=PolicySection)
    window: WindowSection = field(default_factory=WindowSection)
    output: OutputSection = field(default_factory=OutputSection)
    files: dict[str, FileSection] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def sha256(self) -> str:
        return str(_reuse.canonical().sha256_json(self.to_dict()))

    def file(self, key: str) -> FileSection:
        return self.files.get(key, FileSection())

    def formats_for(self, key: str) -> tuple[str, ...]:
        return self.file(key).timestamp_formats or self.reader.timestamp_formats


_SECTIONS: dict[str, tuple[type, dict[str, type]]] = {
    "reader": (
        ReaderSection,
        {
            f: t
            for f, t in [
                ("chunksize", int),
                ("encoding", str),
                ("delimiter", str),
                ("timestamp_formats", list),
                ("strip_whitespace", bool),
                ("na_values", list),
                ("non_numeric", str),
                ("materialise_cell_limit", int),
                ("verify_stream", bool),
            ]
        },
    ),
    "timestamps": (TimestampSection, {"state": str}),
    "policies": (
        PolicySection,
        {"duplicates": str, "empty_rows": str, "approved_sensitivity": list, "approved_bucket_reducers": list},
    ),
    "window": (WindowSection, {"start": str, "end": str}),
    "output": (OutputSection, {"write_time_index": bool, "write_duplicate_ledger": bool}),
}


def _strings(value: Any, where: str, problems: list[str]) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        problems.append(f"{where} must be a list of strings")
        return ()
    return tuple(value)


def _check_format(fmt: str, where: str, problems: list[str]) -> None:
    if any(tok in fmt for tok in _TZ_TOKENS):
        problems.append(
            f"{where}: format {fmt!r} contains a timezone directive; timestamps stay naive_unspecified and no "
            "conversion is allowed without an approved, documentary TimeMapping"
        )
    elif "%" not in fmt:
        problems.append(f"{where}: format {fmt!r} has no strptime directives")


def parse_data_config(raw: dict[str, Any]) -> DataConfig:
    """Validate a parsed TOML mapping. Raises DataConfigError listing EVERY problem."""
    problems: list[str] = []
    raw = {k: (dict(v) if isinstance(v, dict) else v) for k, v in raw.items()}
    version = raw.pop("schema_version", SCHEMA_VERSION)
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        problems.append(f"schema_version must be {SCHEMA_VERSION}, got {version!r}")
    built: dict[str, Any] = {}
    for name, (cls, types) in _SECTIONS.items():
        given = raw.pop(name, {})
        if not isinstance(given, dict):
            problems.append(f"[{name}] must be a table")
            given = {}
        defaults = cls()
        values: dict[str, Any] = {}
        for key, typ in types.items():
            if key not in given:
                values[key] = getattr(defaults, key)
                continue
            value = given.pop(key)
            if typ is list:
                values[key] = _strings(value, f"{name}.{key}", problems)
            elif not isinstance(value, typ) or (typ is int and isinstance(value, bool)):
                problems.append(f"{name}.{key} must be of type {typ.__name__}")
                values[key] = getattr(defaults, key)
            else:
                values[key] = value
        problems.extend(f"unknown key {name}.{extra}" for extra in given)
        built[name] = cls(**values)

    files: dict[str, FileSection] = {}
    given_files = raw.pop("files", {})
    if not isinstance(given_files, dict):
        problems.append("[files] must be a table of per-file tables")
        given_files = {}
    for key, table in given_files.items():
        if not _KEY.match(str(key)) or not isinstance(table, dict):
            problems.append(f"files.{key}: key must match [A-Za-z0-9_]+ and be a table")
            continue
        table = dict(table)
        cols = _strings(table.pop("measurement_columns", []), f"files.{key}.measurement_columns", problems)
        fmts = _strings(table.pop("timestamp_formats", []), f"files.{key}.timestamp_formats", problems)
        problems.extend(f"unknown key files.{key}.{extra}" for extra in table)
        if len(set(cols)) != len(cols):
            problems.append(f"files.{key}.measurement_columns contains duplicates")
        for f in fmts:
            _check_format(f, f"files.{key}.timestamp_formats", problems)
        files[key] = FileSection(cols, fmts)
    problems.extend(f"unknown section or key {extra!r}" for extra in raw)

    rd: ReaderSection = built["reader"]
    if rd.chunksize < 1:
        problems.append("reader.chunksize must be >= 1")
    if rd.materialise_cell_limit < 1:
        problems.append("reader.materialise_cell_limit must be >= 1")
    if rd.non_numeric not in ("raise", "flag"):
        problems.append("reader.non_numeric must be 'raise' or 'flag'")
    if not rd.timestamp_formats:
        problems.append("reader.timestamp_formats must list at least one format (no format is inferred)")
    for f in rd.timestamp_formats:
        _check_format(f, "reader.timestamp_formats", problems)
    if len(rd.delimiter) > 1:
        problems.append("reader.delimiter must be empty (detect) or a single character")
    if built["timestamps"].state != TimestampState.NAIVE_UNSPECIFIED.value:
        problems.append("timestamps.state must be 'naive_unspecified' (the only state Phase 2 supports)")
    pol: PolicySection = built["policies"]
    if pol.duplicates in REJECTED_DUPLICATE_POLICIES:
        problems.append(
            f"policies.duplicates={pol.duplicates!r} is not allowed: the duplicate pairs carry DIFFERENT values, so "
            "keep-first / keep-last / averaging would silently invent data"
        )
    elif pol.duplicates not in PolicyId.DUPLICATE_POLICIES:
        problems.append(f"policies.duplicates must be one of {PolicyId.DUPLICATE_POLICIES}")
    if pol.empty_rows not in PolicyId.EMPTY_POLICIES:
        problems.append(f"policies.empty_rows must be one of {PolicyId.EMPTY_POLICIES}")
    problems.extend(
        f"policies.approved_sensitivity: unknown policy {p!r}"
        for p in pol.approved_sensitivity
        if p not in SENSITIVITY_POLICIES
    )
    problems.extend(
        f"policies.approved_bucket_reducers: unknown reducer {r!r}"
        for r in pol.approved_bucket_reducers
        if r not in KNOWN_REDUCERS
    )
    if pol.duplicates in SENSITIVITY_POLICIES and pol.duplicates not in pol.approved_sensitivity:
        problems.append(
            f"policies.duplicates={pol.duplicates!r} is a sensitivity policy and is not listed in policies.approved_sensitivity"
        )
    for label, text in (("start", built["window"].start), ("end", built["window"].end)):
        if not re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", text):
            problems.append(f"window.{label} must look like 'YYYY-MM-DD HH:MM:SS' (naive text)")
    if problems:
        raise DataConfigError(problems)
    return DataConfig(
        schema_version=SCHEMA_VERSION,
        reader=built["reader"],
        timestamps=built["timestamps"],
        policies=built["policies"],
        window=built["window"],
        output=built["output"],
        files=files,
    )


def load_data_config(path: Path | str) -> DataConfig:
    p = Path(path)
    try:
        with p.open("rb") as fh:
            raw = tomllib.load(fh)
    except FileNotFoundError:
        raise DataConfigError(f"data config not found: {p.name}") from None
    except tomllib.TOMLDecodeError as exc:
        raise DataConfigError(f"{p.name} is not valid TOML: {exc}") from None
    return parse_data_config(raw)


def resolve_duplicate_policy(data_cfg: DataConfig, phase1_policy: str) -> tuple[str, str]:
    """(policy, note). Phase 1 config 'undeclared' defers to the data config; a conflicting declaration is an error."""
    chosen = data_cfg.policies.duplicates
    if phase1_policy == "undeclared":
        return chosen, "phase1 [policies].duplicate_timestamps is undeclared; the Phase 2 data config decision is used"
    if phase1_policy != chosen:
        raise DataConfigError(
            f"conflicting duplicate policy: Phase 1 config says {phase1_policy!r}, data config says {chosen!r}; "
            "declare the same policy in both"
        )
    return chosen, "phase1 and data config agree"
