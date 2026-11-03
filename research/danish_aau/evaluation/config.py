"""Evaluation configuration (TOML), parsed strictly.

Design rules:
  * unknown sections/keys are ERRORS (a typo must not silently fall back to a default);
  * scientific choices that the context document says are NOT yet established -- the timezone of the naive CSV
    timestamps and the duplicate-timestamp policy -- default to ``"undeclared"``. The harness runs with them
    undeclared in Phase 1, but ``readiness()`` reports that comparisons (Phase 3+) are blocked until the user
    declares them, and records the declaration (and its stated basis) in every manifest;
  * silent averaging / keep-first / keep-last of duplicate timestamps and any interpolation or filling are not
    selectable values at all.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import _reuse

SCHEMA_VERSION = 1

DUPLICATE_POLICIES = ("undeclared", "keep_all_ordered", "exclude_ambiguous")
REJECTED_DUPLICATE_POLICIES = frozenset(
    {"mean", "average", "avg", "first", "last", "keep_first", "keep_last", "drop", "dedupe", "drop_duplicates"}
)
VENTILATION_POLICIES = ("populated_only",)
INTERPOLATION_POLICIES = ("none",)
LOAD_PERIODS = ("25_percent",)  # the only period audited so far (context doc section 2)

# Settings that say WHERE things live on this machine, not WHAT the experiment is: excluded from the config hash.
LOCATION_KEYS: tuple[tuple[str, str], ...] = (("dataset", "raw_dir"), ("output", "root"))

_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_IANA = re.compile(r"^[A-Za-z_]+(?:/[A-Za-z0-9_+\-]+)+$")
_OFFSET = re.compile(r"^[+-](?:[01]\d|2[0-3]):[0-5]\d$")


class ConfigError(ValueError):
    """The configuration file is malformed or selects a value the harness does not allow."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


# section -> key -> (python type, default)
_SCHEMA: dict[str, dict[str, tuple[type, Any]]] = {
    "run": {"name": (str, "aau_eval"), "seed": (int, 0)},
    "dataset": {
        "raw_dir": (str, ""),
        "load_period": (str, "25_percent"),
        "is_synthetic_fixture": (bool, False),
    },
    "timestamps": {"timezone": (str, "undeclared"), "timezone_basis": (str, "")},
    "policies": {
        "duplicate_timestamps": (str, "undeclared"),
        "ventilation_missing": (str, "populated_only"),
        "interpolation": (str, "none"),
    },
    "output": {"root": (str, "research/danish_aau/outputs")},
    "integrity": {"hash_inputs": (bool, False)},
}


@dataclass(frozen=True)
class RunSection:
    name: str = "aau_eval"
    seed: int = 0


@dataclass(frozen=True)
class DatasetSection:
    raw_dir: str = ""
    load_period: str = "25_percent"
    is_synthetic_fixture: bool = False


@dataclass(frozen=True)
class TimestampSection:
    timezone: str = "undeclared"
    timezone_basis: str = ""


@dataclass(frozen=True)
class PolicySection:
    duplicate_timestamps: str = "undeclared"
    ventilation_missing: str = "populated_only"
    interpolation: str = "none"


@dataclass(frozen=True)
class OutputSection:
    root: str = "research/danish_aau/outputs"


@dataclass(frozen=True)
class IntegritySection:
    hash_inputs: bool = False


@dataclass(frozen=True)
class EvalConfig:
    schema_version: int = SCHEMA_VERSION
    run: RunSection = field(default_factory=RunSection)
    dataset: DatasetSection = field(default_factory=DatasetSection)
    timestamps: TimestampSection = field(default_factory=TimestampSection)
    policies: PolicySection = field(default_factory=PolicySection)
    output: OutputSection = field(default_factory=OutputSection)
    integrity: IntegritySection = field(default_factory=IntegritySection)

    def to_dict(self) -> dict[str, Any]:
        """Everything, including machine-specific locations. Use ``portable_dict`` for hashing/recording."""
        return asdict(self)

    def portable_dict(self) -> dict[str, Any]:
        """The scientific configuration WITHOUT machine-specific locations (``LOCATION_KEYS``).

        This is what is hashed and what the manifest records, so the same experiment has the same config hash on
        every machine and no absolute path (e.g. ``C:\\Users\\...``) leaks into a manifest. Where the data was read
        from is recorded separately, scrubbed, under the manifest's ``dataset`` section.
        """
        d = asdict(self)
        for section, key in LOCATION_KEYS:
            d[section].pop(key, None)
        return d

    @property
    def sha256(self) -> str:
        return str(_reuse.canonical().sha256_json(self.portable_dict()))

    def readiness(self) -> dict[str, Any]:
        """Which scientific declarations are still missing before comparisons (Phase 3+) may run."""
        blocking: list[str] = []
        if self.timestamps.timezone == "undeclared":
            blocking.append("timestamps.timezone is undeclared (CSV timestamps are naive; timezone not established)")
        if self.policies.duplicate_timestamps == "undeclared":
            blocking.append(
                "policies.duplicate_timestamps is undeclared (46 differing duplicate pairs in the 25% file)"
            )
        return {"ready_for_comparisons": not blocking, "blocking": blocking}


def _validate_values(values: dict[str, dict[str, Any]], problems: list[str]) -> None:
    if not _NAME.match(values["run"]["name"]):
        problems.append("run.name must match [A-Za-z0-9_.-]{1,64}")
    if values["run"]["seed"] < 0:
        problems.append("run.seed must be >= 0")
    if values["dataset"]["load_period"] not in LOAD_PERIODS:
        problems.append(
            f"dataset.load_period must be one of {LOAD_PERIODS}: only the 25% period has been audited "
            "(other periods are added after they are audited)"
        )
    tz = values["timestamps"]["timezone"]
    if not (tz in ("undeclared", "UTC") or _IANA.match(tz) or _OFFSET.match(tz)):
        problems.append("timestamps.timezone must be 'undeclared', 'UTC', an IANA name (Area/City) or a +HH:MM offset")
    if tz != "undeclared" and not values["timestamps"]["timezone_basis"].strip():
        problems.append(
            "timestamps.timezone_basis must say WHY the declared timezone is believed (it is recorded in every manifest)"
        )
    dup = values["policies"]["duplicate_timestamps"]
    if dup in REJECTED_DUPLICATE_POLICIES:
        problems.append(
            f"policies.duplicate_timestamps={dup!r} is not allowed: the 46 duplicate pairs all carry DIFFERENT "
            f"values, so averaging / keep-first / keep-last would silently invent data. Choose one of {DUPLICATE_POLICIES}"
        )
    elif dup not in DUPLICATE_POLICIES:
        problems.append(f"policies.duplicate_timestamps must be one of {DUPLICATE_POLICIES}")
    if values["policies"]["ventilation_missing"] not in VENTILATION_POLICIES:
        problems.append(
            f"policies.ventilation_missing must be one of {VENTILATION_POLICIES} (never fill missing values)"
        )
    if values["policies"]["interpolation"] not in INTERPOLATION_POLICIES:
        problems.append(f"policies.interpolation must be one of {INTERPOLATION_POLICIES}")
    root = values["output"]["root"]
    if not root.strip():
        problems.append("output.root must not be empty")


def parse_config(raw: dict[str, Any]) -> EvalConfig:
    """Validate a parsed TOML mapping. Raises ConfigError listing EVERY problem found."""
    problems: list[str] = []
    raw = dict(raw)
    version = raw.pop("schema_version", SCHEMA_VERSION)
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        problems.append(f"schema_version must be {SCHEMA_VERSION}, got {version!r}")
    values: dict[str, dict[str, Any]] = {}
    for section, keys in _SCHEMA.items():
        given = raw.pop(section, {})
        if not isinstance(given, dict):
            problems.append(f"[{section}] must be a table")
            given = {}
        values[section] = {}
        for key, (typ, default) in keys.items():
            value = given.pop(key, default)
            ok = isinstance(value, typ) and not (typ is int and isinstance(value, bool))
            if not ok:
                problems.append(f"{section}.{key} must be of type {typ.__name__}, got {type(value).__name__}")
                value = default
            values[section][key] = value
        for extra in given:
            problems.append(f"unknown key {section}.{extra}")
    for extra in raw:
        problems.append(f"unknown section or key {extra!r}")
    _validate_values(values, problems)  # always runs: defaults replace wrongly-typed values, so this is safe
    if problems:
        raise ConfigError(problems)
    return EvalConfig(
        schema_version=SCHEMA_VERSION,
        run=RunSection(**values["run"]),
        dataset=DatasetSection(**values["dataset"]),
        timestamps=TimestampSection(**values["timestamps"]),
        policies=PolicySection(**values["policies"]),
        output=OutputSection(**values["output"]),
        integrity=IntegritySection(**values["integrity"]),
    )


def load_config(path: Path | str) -> EvalConfig:
    p = Path(path)
    try:
        with p.open("rb") as fh:
            raw = tomllib.load(fh)
    except FileNotFoundError:
        raise ConfigError([f"config file not found: {p.name}"]) from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError([f"{p.name} is not valid TOML: {exc}"]) from None
    return parse_config(raw)
