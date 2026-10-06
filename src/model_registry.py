"""Local model registry + artifact manifest, version 2 (T19, contract section 10).

``models/registry.json`` is a JSON object ``{"registry_version": 2, "artifacts": [...]}``. Each
artifact is a manifest-v2 entry (section 10.1): lineage (code revision, physics / environment /
reward / safety-envelope versions, schema hashes, dataset and split ids), the SHA-256, size and
format of every file a loader reads, a lifecycle ``status`` and an append-only ``history[]``.

This module owns the registry FILE and the manifest building blocks. It does not decide whether
an artifact may be loaded -- that is the ArtifactGate in ``src/artifacts/loaders.py``, which uses
:func:`find_entry` and :func:`check_integrity` from here and the version constants from
``src/versions.py``. Status transitions (promote / reject / quarantine) are made only by
``scripts/registry_cli.py``; nothing in this module changes an existing ``history[]`` entry or an
existing entry's status.

Registry writes are atomic (temp file + ``os.replace``) and keep the previous file as
``registry.json.bak``. A bare JSON list (the pre-T19 format) is still READABLE so that a
migration can be run, but its entries are manifest v1 and the gate refuses them.

What hashes do and do not protect against: they detect an artifact changed after it was logged
(tampering, corruption, a stray overwrite). They do NOT protect against a malicious or
compromised training pipeline, and there is a small window between hashing and loading (TOCTOU);
the API container mounts ``models/`` read-only to close it in deployment.

All paths stored in the registry are relative to the project root, in POSIX form.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable, Sequence

from src import versions

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = PROJECT_ROOT / "models" / "registry.json"

REGISTRY_VERSION = 2
MANIFEST_VERSION = 2
STATUSES = ("candidate", "promoted", "quarantined", "rejected", "retired")
KINDS = ("ppo", "anomaly", "forecaster")
VERIFY_MODES = ("enforce", "warn", "off")

# File formats the registry knows by suffix. Which of them a process may LOAD is decided by the
# gate (loaders.ALLOWED_FORMATS); "joblib" and "pkl" are never loadable by the API process.
FORMAT_BY_SUFFIX = {
    ".json": "json",
    ".npz": "npz",
    ".keras": "keras",
    ".zip": "sb3_zip",
    ".joblib": "joblib",
    ".pkl": "pkl",
    ".pickle": "pkl",
    ".h5": "h5",
}

# Contract 10.2 check 2 is applied to the fields that are meaningful for the model kind. A
# data-driven model (anomaly detector, forecaster) never sees the RL environment, so the
# environment / schema / reward / safety-envelope fields are recorded as null for it and are not
# compared -- but a NON-null value that differs from the running one is still a mismatch. A PPO
# policy is built against all nine, and null is a mismatch for it.
COMPAT_FIELDS_BY_KIND: dict[str, tuple[str, ...]] = {
    "ppo": versions.COMPAT_FIELDS,
    "anomaly": ("physics_version", "physics_params_hash", "input_cadence_s"),
    "forecaster": ("physics_version", "physics_params_hash", "input_cadence_s"),
}

_KEY_PACKAGES = ("numpy", "tensorflow", "keras", "torch", "stable-baselines3", "gymnasium", "scikit-learn")
_LEGACY_ANCHORS = ("models", "data")  # top-level repo dirs, used to relativise old absolute paths
_HASH_CHUNK = 1024 * 1024
_CODE_REVISION_RE = re.compile(r"^([0-9a-f]{40}|dirty:[0-9a-f]{7,64})$")
_registry_lock = threading.Lock()


class ModelUnavailableError(RuntimeError):
    """An artifact could not be loaded, so it must not be.

    ``reason`` is safe to log; it never contains an absolute filesystem path. ``code`` is the
    low-cardinality label used for ``model_load_failures_total{reason}``.
    """

    code = "unavailable"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ArtifactManifestError(ModelUnavailableError):
    """No usable manifest: registry missing/unreadable, no covering entry, or not manifest v2."""

    code = "manifest"


class ArtifactNotPromoted(ModelUnavailableError):
    """The registry status does not allow this process to load the artifact."""

    code = "status"


class ArtifactIntegrityError(ModelUnavailableError):
    """A file is missing, or its size / SHA-256 differs from the manifest (contract check 1)."""

    code = "integrity"


class ArtifactIncompatible(ModelUnavailableError):
    """A recorded dependency version differs from the running one (contract check 2)."""

    code = "incompatible"

    def __init__(self, field: str, expected: Any, actual: Any) -> None:
        super().__init__(f"{field}: manifest has {actual!r}, running code has {expected!r}")
        self.field = field
        self.expected = expected
        self.actual = actual


class ArtifactFormatNotAllowed(ModelUnavailableError):
    """The file format is not on this process's allow-list (contract check 3)."""

    code = "format"


class ArtifactLoadError(ModelUnavailableError):
    """The artifact passed the gate but the underlying loader failed."""

    code = "load_error"


# ----------------------------------------------------------------------------- paths & hashing


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_absolute_text(text: str) -> bool:
    return bool(PureWindowsPath(text).drive) or text.startswith(("/", "\\"))


def to_relative(path: str | Path) -> str:
    """Project-root-relative POSIX path of an existing-or-not path.

    ValueError if the path is outside the project root. Symlinks are resolved
    first, so a link pointing out of the root is "outside".
    """
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        raise ValueError("path is outside the project root") from None


def relativise(text: str, *, anchor_legacy: bool = False) -> str:
    """Normalise a path string from a caller or an old registry to a project-relative POSIX path.

    * relative input: returned in POSIX form; ``..`` is rejected;
    * absolute input inside the project root: made relative;
    * any other absolute input: ValueError -- unless ``anchor_legacy`` (used only
      by the operator's ``adopt`` command), which re-anchors a legacy absolute
      path (typically a Windows path from another machine) at its first
      ``models``/``data`` component.
    """
    text = text.strip()
    if not _is_absolute_text(text):
        parts = PureWindowsPath(text).parts if "\\" in text else Path(text).parts
        if ".." in parts:
            raise ValueError("path must not contain '..'")
        return "/".join(parts)
    foreign_windows_path = bool(PureWindowsPath(text).drive) and os.name != "nt"
    if not foreign_windows_path:  # on POSIX, Path("C:\\x") would be mistaken for a relative name
        try:
            return to_relative(text)
        except ValueError:
            pass
    if not anchor_legacy:
        raise ValueError("path is outside the project root")
    parts = PureWindowsPath(text).parts if ("\\" in text or PureWindowsPath(text).drive) else Path(text).parts
    for index, part in enumerate(parts):
        if part in _LEGACY_ANCHORS:
            return "/".join(parts[index:])
    raise ValueError("cannot relativise legacy path (no models/ or data/ component)")


def _resolve_in_root(relative: str) -> Path:
    return PROJECT_ROOT / Path(*relative.split("/"))


# ----------------------------------------------------------------------------- registry I/O


def _atomic_write_json(path: Path, data: Any, *, backup: bool = False) -> None:
    """Write JSON so a reader never sees a partial file: temp file in the same directory, fsync,
    then ``os.replace`` (atomic on POSIX and Windows). With ``backup`` the previous file is first
    copied to ``<name>.bak`` (the rollback point); the copy happens only after ``data`` has been
    serialised, so a serialisation failure touches nothing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp_name, 0o644)  # mkstemp creates 0600; keep the registry readable by other users
        except OSError:
            pass
        if backup and path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def registry_document(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    return {"registry_version": REGISTRY_VERSION, "artifacts": artifacts}


def write_registry(entries: list[dict[str, Any]]) -> None:
    """Atomically replace the registry file with a v2 document holding ``entries``; the previous
    file is kept as ``registry.json.bak``."""
    with _registry_lock:
        _atomic_write_json(REGISTRY_PATH, registry_document(entries), backup=True)


def read_registry_document() -> dict[str, Any]:
    """The registry as a ``{"registry_version", "artifacts"}`` document.

    A bare JSON list (pre-T19) is returned as ``registry_version`` 1. Raises FileNotFoundError /
    ValueError if absent or malformed.
    """
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if isinstance(data, list):
        document = {"registry_version": 1, "artifacts": data}
    elif isinstance(data, dict) and isinstance(data.get("artifacts"), list):
        document = data
    else:
        raise ValueError("registry is neither a JSON list nor an object with an 'artifacts' list")
    if not all(isinstance(e, dict) for e in document["artifacts"]):
        raise ValueError("registry artifacts must be JSON objects")
    return document


def read_registry() -> list[dict[str, Any]]:
    """All artifact entries, oldest first. Raises FileNotFoundError / ValueError if absent or malformed."""
    return read_registry_document()["artifacts"]


def _read_for_append() -> list[dict[str, Any]]:
    if not REGISTRY_PATH.exists():
        return []
    try:
        return read_registry()
    except (ValueError, OSError):  # includes json.JSONDecodeError
        backup = REGISTRY_PATH.with_name(f"{REGISTRY_PATH.name}.corrupt-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
        os.replace(REGISTRY_PATH, backup)  # keep the evidence; never silently discard lineage
        logger.error("Unreadable model registry moved to %s; starting a new one", backup.name)
        return []


def latest(name: str) -> dict[str, Any] | None:
    """Most recent registry entry for a model name, or None if never logged / unreadable."""
    try:
        entries = read_registry()
    except (OSError, ValueError):
        return None
    matches = [e for e in entries if e.get("name") == name]
    return matches[-1] if matches else None


# ----------------------------------------------------------------------------- manifest building


def artifact_files(relative_path: str) -> list[str]:
    """Relative paths of the files a loader reads for the artifact at ``relative_path``.

    A directory covers its regular files (non-recursive); a file covers itself
    plus a sibling ``scaler.json`` when present (the forecaster's scaler).
    """
    target = _resolve_in_root(relative_path)
    if target.is_dir():
        found = sorted(p.name for p in target.iterdir() if p.is_file() and not p.name.startswith("."))
        return [f"{relative_path.rstrip('/')}/{name}" for name in found]
    if target.is_file():
        files = [relative_path]
        sibling = target.with_name("scaler.json")
        if sibling.is_file() and sibling.name != target.name:
            files.append(to_relative(sibling))
        return files
    raise FileNotFoundError(f"artifact not found: {relative_path}")


def format_for_path(path: str | Path) -> str:
    """Registry format label of a file, from its suffix; ``"unknown"`` if not recognised."""
    return FORMAT_BY_SUFFIX.get(Path(str(path)).suffix.lower(), "unknown")


def file_digests(relative_files: Iterable[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for rel in relative_files:
        path = _resolve_in_root(rel)
        out[rel] = {"sha256": sha256_file(path), "size": path.stat().st_size, "format": format_for_path(rel)}
    return out


def aggregate_sha256(files: dict[str, dict[str, Any]]) -> str:
    """One digest for the whole artifact: sha256 over sorted ``path sha256`` lines."""
    listing = "\n".join(f"{rel} {files[rel]['sha256']}" for rel in sorted(files))
    return hashlib.sha256(listing.encode("utf-8")).hexdigest()


def package_versions() -> dict[str, str]:
    found: dict[str, str] = {}
    for pkg in _KEY_PACKAGES:
        try:
            found[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            continue
    return found


def current_git_sha() -> str:
    env = os.getenv("GIT_SHA", "").strip()
    if env:
        return env
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=2, check=True
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def current_code_revision() -> str | None:
    """Manifest ``code_revision``: the 40-hex commit, ``dirty:<sha>`` when the working tree has
    uncommitted changes to tracked files, or None when it cannot be determined (never guessed)."""
    sha = current_git_sha()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return None
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
        if status.strip():
            diff = subprocess.run(
                ["git", "diff", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, timeout=10, check=True
            ).stdout
            return "dirty:" + hashlib.sha256(sha.encode() + diff).hexdigest()[:40]
    except (OSError, subprocess.SubprocessError):
        pass  # not a checkout (or no git): the commit id from GIT_SHA stands as given
    return sha


def _dataset_from_source(data_source: str) -> tuple[str | None, str | None]:
    """(dataset_id, sha256) when ``data_source`` names an existing file under the root."""
    candidate = data_source.split(" (", 1)[0].strip()
    try:
        rel = relativise(candidate)
    except ValueError:
        return None, None
    path = _resolve_in_root(rel)
    if path.is_file():
        return path.name, sha256_file(path)
    return None, None


def build_manifest_fields(
    artifact_path: str | Path,
    *,
    physics_version: str | None = None,
    dataset_id: str | None = None,
    dataset_sha256: str | None = None,
    git_sha: str | None = None,
    key_package_versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The file-manifest part of an entry, computed from the artifact on disk."""
    rel = relativise(str(artifact_path))
    files = file_digests(artifact_files(rel))
    return {
        "manifest_version": MANIFEST_VERSION,
        "relative_path": rel,
        "artifact_path": rel,  # legacy key kept (now relative) so older readers still work
        "sha256": aggregate_sha256(files),
        "size": sum(f["size"] for f in files.values()),
        "files": files,
        "git_sha": git_sha or current_git_sha(),
        "physics_version": physics_version or versions.active_physics_version(),
        "dataset_id": dataset_id,
        "dataset_sha256": dataset_sha256,
        "key_package_versions": key_package_versions if key_package_versions is not None else package_versions(),
    }


def _relative_data_source(data_source: str, *, anchor_legacy: bool = False) -> str:
    """``data_source`` with its leading file path made project-relative; an
    absolute path outside the root is reduced to its file name (never stored)."""
    head, sep, tail = data_source.partition(" (")
    head = head.strip()
    if _is_absolute_text(head):
        try:
            head = relativise(head, anchor_legacy=anchor_legacy)
        except ValueError:
            head = PureWindowsPath(head).name
    return head + (sep + tail if sep else "")


# ----------------------------------------------------------------------------- manifest v2


def infer_kind(name: str) -> str:
    lowered = name.lower()
    if "ppo" in lowered or "optimizer" in lowered:
        return "ppo"
    if "anomaly" in lowered:
        return "anomaly"
    if "forecast" in lowered or "thermal" in lowered:
        return "forecaster"
    raise ValueError(f"cannot infer the model kind from the name {name!r}; pass kind= one of {KINDS}")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def history_entry(seq: int, action: str, from_status: str | None, to_status: str, actor: str, reason: str) -> dict:
    return {
        "seq": seq,
        "at_utc": now_utc(),
        "action": action,
        "from": from_status,
        "to": to_status,
        "actor": actor,
        "reason": reason,
    }


def running_lineage_fields(kind: str) -> dict[str, Any]:
    """The compatibility fields a NEW artifact of ``kind`` records: the running values for the
    fields that apply to the kind, null for the rest."""
    running = versions.running_compat_values()
    applicable = COMPAT_FIELDS_BY_KIND[kind]
    return {field: (running[field] if field in applicable else None) for field in versions.COMPAT_FIELDS}


def training_config_block(params: dict[str, Any]) -> dict[str, Any]:
    return {"json": params, "sha256": versions.sha256_json(params)}


def _unique_model_id(entries: list[dict[str, Any]], base: str) -> str:
    taken = {e.get("model_id") for e in entries}
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def validate_manifest(entry: dict[str, Any]) -> list[str]:
    """Structural problems of a manifest-v2 entry (empty list = well-formed). Pure; no I/O."""
    problems: list[str] = []
    required = (
        "model_id", "name", "kind", "status", "created_at_utc", "code_revision", "physics_version",
        "physics_params_hash", "environment_version", "observation_schema_hash", "action_schema_hash",
        "action_semantics_version", "reward_version", "safety_envelope_version", "training_config", "seed(s)",
        "dataset_id", "dataset_manifest_sha256", "scenario_set_id", "split_id", "input_cadence_s",
        "package_versions", "files", "evaluation_ref", "compat_waiver", "history",
    )  # fmt: skip
    for key in required:
        # the contract's "seed(s)" is stored under the key "seeds"
        if (key if key != "seed(s)" else "seeds") not in entry:
            problems.append(f"missing field {key}")
    if problems:
        return problems
    if entry["status"] not in STATUSES:
        problems.append(f"status {entry['status']!r} is not one of {STATUSES}")
    if entry["kind"] not in KINDS:
        problems.append(f"kind {entry['kind']!r} is not one of {KINDS}")
    revision = entry["code_revision"]
    waiver = entry["compat_waiver"]
    if revision is None:
        if entry["status"] == "promoted" and not waiver:
            problems.append("a promoted artifact without a waiver must record a code_revision")
    elif not (isinstance(revision, str) and _CODE_REVISION_RE.match(revision)):
        problems.append("code_revision must be a 40-hex commit, 'dirty:<sha>' or null")
    files = entry["files"]
    if not isinstance(files, dict) or not files:
        problems.append("files must be a non-empty object")
    else:
        for rel, info in files.items():
            if not (isinstance(info, dict) and info.get("sha256") and isinstance(info.get("size"), int)):
                problems.append(f"files[{rel}] needs sha256 and size")
            elif not info.get("format"):
                problems.append(f"files[{rel}] needs a format")
    if not isinstance(entry["history"], list) or not entry["history"]:
        problems.append("history must be a non-empty list")
    if waiver is not None:
        if not isinstance(waiver, dict):
            problems.append("compat_waiver must be an object or null")
        else:
            fields = waiver.get("fields")
            if not (isinstance(fields, list) and fields and all(f in versions.COMPAT_FIELDS for f in fields)):
                problems.append("compat_waiver.fields must be a non-empty list of compatibility fields")
            if not str(waiver.get("reason", "")).strip():
                problems.append("compat_waiver.reason is required")
            if not re.fullmatch(r"T\d+", str(waiver.get("expires_after_task", ""))):
                problems.append("compat_waiver.expires_after_task must look like 'T26'")
            if not str(waiver.get("name", "")).strip():
                problems.append("compat_waiver.name is required (a waiver is always named)")
    return problems


def log_model(
    name: str,
    *,
    metrics: dict[str, Any],
    data_source: str,
    artifact_path: str,
    params: dict[str, Any] | None = None,
    version: str | None = None,
    dataset_id: str | None = None,
    dataset_sha256: str | None = None,
    physics_version: str | None = None,
    kind: str | None = None,
    status: str = "candidate",
    seeds: list[int] | None = None,
    scenario_set_id: str | None = None,
    split_id: str | None = None,
    dataset_manifest_sha256: str | None = None,
    evaluation_ref: str | None = None,
) -> dict[str, Any]:
    """Append one manifest-v2 entry (``status`` ``candidate`` unless told otherwise), including the
    hashes of the files on disk NOW -- call after the artifact is saved. Never overwrites prior
    entries; newest last. The compatibility fields are stamped with the values the RUNNING code
    defines, which is what makes a later change to ``src/versions.py`` invalidate the artifact.

    ``artifact_path`` / ``data_source`` are stored relative to the project root. Raises
    FileNotFoundError if the artifact is missing and ValueError if it lies outside the project root.
    A new entry is never ``promoted`` here; promotion is ``scripts/registry_cli.py promote``.
    """
    if status not in ("candidate", "quarantined"):
        raise ValueError("log_model can only create candidate or quarantined entries; promote with registry_cli")
    if dataset_id is None and dataset_sha256 is None:
        dataset_id, dataset_sha256 = _dataset_from_source(data_source)
    data_source = _relative_data_source(data_source)
    manifest = build_manifest_fields(
        artifact_path, physics_version=physics_version, dataset_id=dataset_id, dataset_sha256=dataset_sha256
    )
    chosen_kind = kind or infer_kind(name)
    if chosen_kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    params = params or {}
    created = now_utc()
    chosen_version = version or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lineage = running_lineage_fields(chosen_kind)
    if physics_version is not None:
        lineage["physics_version"] = physics_version
    revision = current_code_revision()
    with _registry_lock:
        entries = _read_for_append()
        entry = {
            "model_id": _unique_model_id(entries, f"{name}-{chosen_version}"),
            "name": name,
            "kind": chosen_kind,
            "status": status,
            "created_at_utc": created,
            "code_revision": revision,
            **lineage,
            "training_config": training_config_block(params),
            "seeds": seeds
            if seeds is not None
            else (params.get("seeds") or ([params["seed"]] if "seed" in params else None)),
            "dataset_id": manifest["dataset_id"],
            "dataset_manifest_sha256": dataset_manifest_sha256,
            "scenario_set_id": scenario_set_id,
            "split_id": split_id,
            "package_versions": manifest["key_package_versions"],
            "files": manifest["files"],
            "evaluation_ref": evaluation_ref,
            "compat_waiver": None,
            "history": [history_entry(0, "logged", None, status, "log_model", "artifact logged after training")],
            # additive, human-oriented and legacy keys
            "version": chosen_version,
            "trained_at": created,
            "metrics": metrics,
            "data_source": data_source,
            "params": params,
            "python": platform.python_version(),
            "manifest_version": MANIFEST_VERSION,
            "relative_path": manifest["relative_path"],
            "artifact_path": manifest["artifact_path"],
            "sha256": manifest["sha256"],
            "size": manifest["size"],
            "git_sha": manifest["git_sha"],
            "dataset_sha256": manifest["dataset_sha256"],
        }
        entries.append(entry)
        _atomic_write_json(REGISTRY_PATH, registry_document(entries), backup=True)
    return entry


# ----------------------------------------------------------------------------- lookup & integrity


def verify_mode() -> str:
    """``ARTIFACT_VERIFY``: enforce (default) | warn | off. Production (``ENVIRONMENT=production``)
    always enforces, whatever is configured."""
    raw = os.getenv("ARTIFACT_VERIFY", "").strip().lower()
    mode = "enforce"
    if raw:
        if raw in VERIFY_MODES:
            mode = raw
        else:
            logger.warning("Unknown ARTIFACT_VERIFY=%r; treating it as 'enforce'", raw)
    if mode != "enforce" and is_production():
        logger.error("ARTIFACT_VERIFY=%s is ignored when ENVIRONMENT=production; enforcing", mode)
        return "enforce"
    return mode


def is_production() -> bool:
    return os.getenv("ENVIRONMENT", "").strip().lower() in ("production", "prod")


def to_relatives(paths: Sequence[str | Path]) -> list[str]:
    rels: list[str] = []
    for p in paths:
        try:
            rels.append(to_relative(p))
        except (ValueError, OSError):
            raise ArtifactManifestError(f"{Path(str(p)).name} is outside the project root") from None
    return rels


def find_entry(rels: Sequence[str]) -> dict[str, Any]:
    """The newest registry entry whose manifest lists ALL of ``rels``."""
    try:
        entries = read_registry()
    except FileNotFoundError:
        raise ArtifactManifestError("model registry not found") from None
    except (OSError, ValueError):
        raise ArtifactManifestError("model registry unreadable") from None
    entry = next(
        (e for e in reversed(entries) if isinstance(e.get("files"), dict) and all(r in e["files"] for r in rels)),
        None,
    )
    if entry is None:
        raise ArtifactManifestError(f"no manifest entry covers {', '.join(rels)}")
    return entry


def check_integrity(entry: dict[str, Any], rels: Sequence[str]) -> None:
    """Contract 10.2 check 1: every file in ``rels`` exists and its size and SHA-256 equal the manifest."""
    for rel in rels:
        expected = entry["files"][rel]
        path = _resolve_in_root(rel)
        if not path.is_file():
            raise ArtifactIntegrityError(f"{rel} is missing")
        if not isinstance(expected, dict) or not expected.get("sha256"):
            raise ArtifactIntegrityError(f"{rel} has no recorded sha256")
        if expected.get("size") is not None and path.stat().st_size != expected["size"]:
            raise ArtifactIntegrityError(f"{rel} size differs from the manifest")
        if not hmac.compare_digest(sha256_file(path), str(expected["sha256"])):
            raise ArtifactIntegrityError(f"{rel} sha256 differs from the manifest")


def _check(paths: Sequence[str | Path]) -> dict[str, Any]:
    """Integrity-only check of ``paths`` against their newest covering entry (used by
    ``scripts/artifact_manifest.py verify``). Returns the entry; raises ModelUnavailableError."""
    rels = to_relatives(paths)
    entry = find_entry(rels)
    check_integrity(entry, rels)
    return entry


def ensure_verified(paths: Sequence[str | Path], *, artifact: str) -> None:
    """Deprecated shim kept for older callers: runs the full ArtifactGate on ``paths``.

    New code uses ``src.artifacts.loaders``. Imported lazily to avoid an import cycle.
    """
    from src.artifacts import loaders

    loaders.authorize(paths, artifact=artifact)
