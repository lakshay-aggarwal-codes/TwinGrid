#!/usr/bin/env python3
"""Validate data/external/REGISTER.json (T22, roadmap section 14).

Standard library only, so the CI ``lint`` job can run it without installing the project.

    python scripts/check_register.py            # exit 0 = register is valid, 1 = findings printed to stdout

Rules (each finding is printed as ``ERROR [rule] message``):

  schema         every entry has the section 14.1 fields with the right types; ids are unique;
                 license_status in {verified, unverified, restricted}; redistribution in {permitted, not_permitted}
  manifest       every data/external/<dir>/provenance.json is registered by exactly one entry, and every entry's
                 ``manifest`` points at an existing file
  unregistered   code that references a dataset (``realData/<name>`` or a known remote API) which has no entry
  used_by        every ``used_by`` path exists in the repository
  claim_verb     a supported claim containing calibrates / validates / drives (any inflection) needs a non-empty
                 ``used_by``: a claim about code that does not exist is not allowed
  license        license_status != verified while redistribution != not_permitted (unknown counts as not_permitted)
  frontier       no entry for Frontier / HPC data, and no code that references it

Rules that go beyond the section 14.1 list, added to enforce its stated intent (documented in T22_evidence.md):

  license_evidence   license_status == verified requires terms_url, terms_retrieved_at and a 64-hex terms_sha256
  source             an entry that code uses (non-empty used_by) must have a source_url: a dataset with no
                     identifiable source must not be consumed (T22 stop condition)
  reference_only     a ``reference_only`` entry must have an empty used_by

License evidence fields are filled by a person (roadmap A-4). Nothing in this script, or anywhere else in the
repository, may set license_status to ``verified`` on its own.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTER_RELPATH = "data/external/REGISTER.json"
MANIFEST_DIR_RELPATH = "data/external"

LICENSE_STATUSES = ("verified", "unverified", "restricted")
REDISTRIBUTIONS = ("permitted", "not_permitted")
REFERENCE_ONLY = "reference_only"

# Section 14.1 fields, in order, with the JSON type each must have. ``None`` in a nullable field means "not recorded".
STRING_FIELDS = ("id", "source_name", "version_or_date", "spatial_resolution", "temporal_resolution", "permitted_use")
NULLABLE_STRING_FIELDS = ("source_url", "retrieved_at", "terms_url", "terms_retrieved_at", "terms_sha256")
LIST_FIELDS = ("variables", "preprocessing", "used_by", "supported_claims", "prohibited_claims")
ENUM_FIELDS = ("license_status", "redistribution")
# T22 addition to 14.1: where the provenance manifest of this dataset lives (null when none exists).
EXTRA_FIELDS = ("manifest",)

# Claim verbs from section 14.1 (calibrates, validates, drives), with their inflections.
CLAIM_VERB = re.compile(
    r"\b(calibrat(?:e|es|ed|ing)|validat(?:e|es|ed|ing)|driv(?:e|es|en|ing)|drove)\b", re.IGNORECASE
)

SCAN_SUFFIXES = (".py", ".sh", ".yml", ".yaml", ".toml", ".cfg", ".ini")
SKIP_DIRS = {
    ".git",
    ".github_cache",
    "__pycache__",
    "node_modules",
    "realData",  # the data itself
    "data",  # data/ holds manifests, the register and outputs, not code
    "tests",  # tests name datasets on purpose (negative tests)
    "reports",
    "docs",
    ".venv",
    "venv",
    "build",
    "dist",
    ".ruff_cache",
    ".pytest_cache",
}
SKIP_DIR_PREFIXES = ("twin-stream",)  # the separate frontend project

# ``realData/<name>`` in a string, comment or docstring ...
REAL_DATA_TEXT = re.compile(r"""realData/([^/\s"'`)\]},;:]+)""")
# ... and the pathlib forms:  "realData" / "name"   |   real_data_dir / "name"   |   REAL_DATA_DIR / "name"
REAL_DATA_JOIN = re.compile(
    r"""(?:["']realData["']|\breal_data_dir\b|\bREAL_DATA_DIR\b|\bget_real_data_dir\([^)]*\))\s*/\s*["']([^"'/]+)["']"""
)
# Names that are patterns or placeholders, not datasets.
PLACEHOLDER_START = ("<", "{", "*", "$", "%", ".")

# Remote datasets that are fetched by API rather than stored under realData/. marker regex -> registered dataset id.
REMOTE_MARKERS: dict[str, str] = {
    r"developer\.nrel\.gov|\bNSRDB_API_KEY\b": "nrel-nsrdb-psm3",
}

# Frontier / HPC data must never be referenced (T22). "Pareto frontier" and the C-MAPSS "HPC" (high-pressure
# compressor) are not datasets and are deliberately not matched.
FORBIDDEN_CODE = re.compile(
    r"(?<!pareto )(?<!efficient )(?<!efficiency )\bfrontier\b|\bolcf\b|oak ridge|\bhpc[ _-]?(?:trace|dataset|telemetry|job|power|cluster)",
    re.IGNORECASE,
)
FORBIDDEN_ENTRY = re.compile(r"\bfrontier\b|\bolcf\b|oak ridge|\bhpc\b", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    rule: str
    message: str

    def __str__(self) -> str:
        return f"ERROR [{self.rule}] {self.message}"


# --------------------------------------------------------------------------- loading


def load_register(root: Path = REPO_ROOT, register_path: Path | None = None) -> dict[str, Any]:
    path = register_path or (root / REGISTER_RELPATH)
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _datasets(register: Any) -> list[Any]:
    if isinstance(register, dict) and isinstance(register.get("datasets"), list):
        return register["datasets"]
    return []


def effective_redistribution(entry: dict[str, Any]) -> str:
    """Section 14.1: an unknown or missing value is treated as ``not_permitted``."""
    value = entry.get("redistribution")
    return value if value == "permitted" else "not_permitted"


# --------------------------------------------------------------------------- individual rules


def check_schema(register: Any) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(register, dict) or not isinstance(register.get("datasets"), list):
        return [Finding("schema", "REGISTER.json must be an object with a 'datasets' list")]
    seen: set[str] = set()
    for index, entry in enumerate(register["datasets"]):
        label = f"datasets[{index}]"
        if not isinstance(entry, dict):
            findings.append(Finding("schema", f"{label} is not an object"))
            continue
        entry_id = entry.get("id")
        if isinstance(entry_id, str) and entry_id:
            label = f"'{entry_id}'"
            if entry_id in seen:
                findings.append(Finding("schema", f"duplicate id {label}"))
            seen.add(entry_id)
        for name in STRING_FIELDS:
            if not isinstance(entry.get(name), str) or not entry[name].strip():
                findings.append(Finding("schema", f"{label}: '{name}' must be a non-empty string"))
        for name in NULLABLE_STRING_FIELDS + EXTRA_FIELDS:
            if name not in entry:
                findings.append(Finding("schema", f"{label}: missing field '{name}' (use null when not recorded)"))
            elif entry[name] is not None and (not isinstance(entry[name], str) or not entry[name].strip()):
                findings.append(Finding("schema", f"{label}: '{name}' must be null or a non-empty string"))
        for name in LIST_FIELDS:
            value = entry.get(name)
            if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
                findings.append(Finding("schema", f"{label}: '{name}' must be a list of non-empty strings"))
        for name, allowed in (("license_status", LICENSE_STATUSES), ("redistribution", REDISTRIBUTIONS)):
            if entry.get(name) not in allowed:
                note = " (unknown is treated as not_permitted)" if name == "redistribution" else ""
                findings.append(Finding("schema", f"{label}: '{name}' must be one of {list(allowed)}{note}"))
        if isinstance(entry.get("prohibited_claims"), list) and not entry["prohibited_claims"]:
            findings.append(Finding("schema", f"{label}: 'prohibited_claims' must name the claim boundary (not empty)"))
        if isinstance(entry.get("supported_claims"), list) and not entry["supported_claims"]:
            findings.append(
                Finding("schema", f"{label}: 'supported_claims' must not be empty (use ['{REFERENCE_ONLY}', ...])")
            )
    return findings


def check_manifests(register: Any, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    claimed: dict[str, str] = {}
    for entry in _datasets(register):
        if not isinstance(entry, dict):
            continue
        manifest = entry.get("manifest")
        if manifest is None:
            continue
        label = f"'{entry.get('id')}'"
        if not isinstance(manifest, str):
            continue
        if manifest in claimed:
            findings.append(Finding("manifest", f"{label} and '{claimed[manifest]}' both claim {manifest}"))
        claimed[manifest] = str(entry.get("id"))
        if not (root / manifest).is_file():
            findings.append(Finding("manifest", f"{label}: manifest {manifest} does not exist"))
    external = root / MANIFEST_DIR_RELPATH
    if external.is_dir():
        for child in sorted(external.iterdir()):
            candidate = child / "provenance.json"
            if child.is_dir() and candidate.is_file():
                relpath = f"{MANIFEST_DIR_RELPATH}/{child.name}/provenance.json"
                if relpath not in claimed:
                    findings.append(Finding("manifest", f"{relpath} is not registered in REGISTER.json"))
    return findings


def check_used_by(register: Any, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for entry in _datasets(register):
        if not isinstance(entry, dict) or not isinstance(entry.get("used_by"), list):
            continue
        for path in entry["used_by"]:
            if not isinstance(path, str):
                continue
            label = f"'{entry.get('id')}'"
            relative = Path(path)
            if relative.is_absolute() or ".." in relative.parts or "\\" in path:
                findings.append(Finding("used_by", f"{label}: '{path}' must be a repository-relative path with '/'"))
            elif not (root / relative).exists():
                findings.append(Finding("used_by", f"{label}: used_by path '{path}' does not exist"))
    return findings


def check_claims(register: Any) -> list[Finding]:
    findings: list[Finding] = []
    for entry in _datasets(register):
        if not isinstance(entry, dict):
            continue
        label = f"'{entry.get('id')}'"
        used_by = entry.get("used_by") if isinstance(entry.get("used_by"), list) else []
        supported = [c for c in entry.get("supported_claims", []) if isinstance(c, str)]
        if not used_by:
            for claim in supported:
                match = CLAIM_VERB.search(claim)
                if match:
                    findings.append(
                        Finding(
                            "claim_verb",
                            f"{label}: supported claim uses '{match.group(0)}' but used_by is empty "
                            f"(mark the entry '{REFERENCE_ONLY}' or remove the claim): {claim!r}",
                        )
                    )
        if REFERENCE_ONLY in supported and used_by:
            findings.append(Finding("reference_only", f"{label}: marked '{REFERENCE_ONLY}' but used_by is not empty"))
        if used_by and not (isinstance(entry.get("source_url"), str) and entry["source_url"].strip()):
            findings.append(
                Finding(
                    "source",
                    f"{label}: code uses this dataset but no source_url is recorded; stop and identify the source",
                )
            )
    return findings


def check_license(register: Any) -> list[Finding]:
    findings: list[Finding] = []
    for entry in _datasets(register):
        if not isinstance(entry, dict):
            continue
        label = f"'{entry.get('id')}'"
        status = entry.get("license_status")
        if status != "verified" and effective_redistribution(entry) != "not_permitted":
            findings.append(
                Finding("license", f"{label}: license_status is '{status}' but redistribution is not 'not_permitted'")
            )
        if status == "verified":
            sha = entry.get("terms_sha256")
            missing = [
                name
                for name in ("terms_url", "terms_retrieved_at")
                if not (isinstance(entry.get(name), str) and entry[name].strip())
            ]
            if not (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)):
                missing.append("terms_sha256 (64 lowercase hex characters)")
            if missing:
                findings.append(
                    Finding(
                        "license_evidence", f"{label}: license_status 'verified' without evidence: {', '.join(missing)}"
                    )
                )
    return findings


def check_frontier_entries(register: Any) -> list[Finding]:
    findings: list[Finding] = []
    for entry in _datasets(register):
        if not isinstance(entry, dict):
            continue
        text = " ".join(str(entry.get(name, "")) for name in ("id", "source_name", "source_url", "manifest"))
        if FORBIDDEN_ENTRY.search(text):
            findings.append(
                Finding("frontier", f"'{entry.get('id')}': Frontier/HPC data must not have a register entry")
            )
    return findings


# --------------------------------------------------------------------------- code scan


def iter_code_files(root: Path) -> Iterable[Path]:
    this_file = Path(__file__).resolve()
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(SKIP_DIR_PREFIXES))
        for name in sorted(files):
            path = Path(current) / name
            if path.suffix.lower() in SCAN_SUFFIXES and path.resolve() != this_file:
                yield path


def registered_names(register: Any) -> set[str]:
    """Local directory/file names under realData/ that the register covers (taken from each entry's manifest)."""
    names: set[str] = set()
    for entry in _datasets(register):
        manifest = entry.get("manifest") if isinstance(entry, dict) else None
        if isinstance(manifest, str):
            parts = manifest.split("/")
            if len(parts) >= 3:
                names.add(parts[-2])
    return names


def referenced_datasets(text: str) -> set[str]:
    found: set[str] = set()
    for pattern in (REAL_DATA_TEXT, REAL_DATA_JOIN):
        for match in pattern.finditer(text):
            name = match.group(1).strip()
            if name and not name.startswith(PLACEHOLDER_START) and name not in {"data"}:
                found.add(name)
    return found


def check_code_references(register: Any, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    names = registered_names(register)
    ids = {e.get("id") for e in _datasets(register) if isinstance(e, dict)}
    for path in iter_code_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(root).as_posix()
        for name in sorted(referenced_datasets(text) - names):
            findings.append(
                Finding("unregistered", f"{rel} references dataset 'realData/{name}' which has no register entry")
            )
        for marker, dataset_id in REMOTE_MARKERS.items():
            if re.search(marker, text) and dataset_id not in ids:
                findings.append(
                    Finding(
                        "unregistered", f"{rel} references remote dataset '{dataset_id}' which has no register entry"
                    )
                )
        match = FORBIDDEN_CODE.search(text)
        if match:
            findings.append(
                Finding(
                    "frontier",
                    f"{rel} references Frontier/HPC data ('{match.group(0)}'); there must be no such dataset",
                )
            )
    return findings


# --------------------------------------------------------------------------- entry point


def check_register(root: Path = REPO_ROOT, register: Any = None, *, scan_code: bool = True) -> list[Finding]:
    """All findings for the register at ``root`` (``register`` overrides the file, for tests)."""
    if register is None:
        try:
            register = load_register(root)
        except FileNotFoundError:
            return [Finding("schema", f"{REGISTER_RELPATH} not found")]
        except json.JSONDecodeError as exc:
            return [Finding("schema", f"{REGISTER_RELPATH} is not valid JSON: {exc}")]
    findings = check_schema(register)
    if not _datasets(register):
        return findings  # structurally unusable (not an object with a datasets list): nothing else can be judged
    findings += check_manifests(register, root)
    findings += check_used_by(register, root)
    findings += check_claims(register)
    findings += check_license(register)
    findings += check_frontier_entries(register)
    if scan_code:
        findings += check_code_references(register, root)
    return findings


def main() -> int:
    findings = check_register()
    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} problem(s) in {REGISTER_RELPATH}")
        return 1
    count = len(_datasets(load_register()))
    print(f"{REGISTER_RELPATH}: OK ({count} datasets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
