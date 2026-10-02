"""Local model registry + artifact manifest.

An append-only JSON log of every training run (what was trained, when, on what
data, with what metrics) that doubles as the artifact MANIFEST: each entry also
records the SHA-256 and size of every file a loader will read, plus provenance
metadata (physics_version, dataset id/hash, git sha, python/package versions).

Loaders call :func:`ensure_verified` before reading an artifact. Behaviour is
set by ``ARTIFACT_VERIFY`` (read on every call):

* ``enforce`` (default) -- refuse with :class:`ModelUnavailableError` when the
  artifact has no manifest entry, a file is missing, a hash/size differs, or the
  manifest's ``physics_version`` is not the active one.
* ``warn``    -- log the problem and load anyway (rollback / migration aid).
* ``off``     -- no checks (tests, local experiments).

What this does and does not protect against: hashes detect an artifact that was
changed after it was logged (tampering, corruption, a stray overwrite). They do
NOT protect against a malicious or compromised build/training pipeline, and a
legacy artifact adopted with ``scripts/artifact_manifest.py adopt`` is trusted
on first use. There is a small window between hashing and loading (TOCTOU); the
API container mounts ``models/`` read-only to close it in deployment.

All paths stored in the registry are relative to the project root, in POSIX
form. Registry writes are atomic (temp file + ``os.replace``). Old registries
stay readable: new fields are additive and readers ignore unknown keys.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import platform
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable, Sequence

from src.versions import PHYSICS_VERSION

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = PROJECT_ROOT / "models" / "registry.json"

MANIFEST_VERSION = 1
VERIFY_MODES = ("enforce", "warn", "off")
_KEY_PACKAGES = ("numpy", "tensorflow", "keras", "torch", "stable-baselines3", "gymnasium", "scikit-learn", "joblib")
_LEGACY_ANCHORS = ("models", "data")  # top-level repo dirs, used to relativise old absolute paths
_HASH_CHUNK = 1024 * 1024
_registry_lock = threading.Lock()


class ModelUnavailableError(RuntimeError):
    """An artifact could not be verified, so it must not be loaded.

    ``reason`` is safe to log; it never contains an absolute filesystem path.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON so a reader never sees a partial file: temp file in the same
    directory, fsync, then ``os.replace`` (atomic on POSIX and Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp_name, 0o644)  # mkstemp creates 0600; keep the registry readable by other users
        except OSError:
            pass
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_registry(entries: list[dict[str, Any]]) -> None:
    """Atomically replace the registry file with ``entries``."""
    with _registry_lock:
        _atomic_write_json(REGISTRY_PATH, entries)


def read_registry() -> list[dict[str, Any]]:
    """All entries, oldest first. Raises FileNotFoundError / ValueError if absent or malformed."""
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
        raise ValueError("registry is not a JSON list of objects")
    return data


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
    plus a sibling ``scaler.joblib`` when present (the forecaster's scaler).
    """
    target = _resolve_in_root(relative_path)
    if target.is_dir():
        found = sorted(p.name for p in target.iterdir() if p.is_file() and not p.name.startswith("."))
        return [f"{relative_path.rstrip('/')}/{name}" for name in found]
    if target.is_file():
        files = [relative_path]
        sibling = target.with_name("scaler.joblib")
        if sibling.is_file() and sibling.name != target.name:
            files.append(to_relative(sibling))
        return files
    raise FileNotFoundError(f"artifact not found: {relative_path}")


def file_digests(relative_files: Iterable[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for rel in relative_files:
        path = _resolve_in_root(rel)
        out[rel] = {"sha256": sha256_file(path), "size": path.stat().st_size}
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
    """The manifest part of an entry, computed from the artifact on disk."""
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
        "physics_version": physics_version or PHYSICS_VERSION,
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
) -> dict[str, Any]:
    """Append one entry, including the artifact manifest (hashes of the files on
    disk NOW -- call after the artifact is saved). Never overwrites prior
    entries; newest last. ``artifact_path`` / ``data_source`` are stored
    relative to the project root. Raises FileNotFoundError if the artifact is
    missing and ValueError if it lies outside the project root.
    """
    if dataset_id is None and dataset_sha256 is None:
        dataset_id, dataset_sha256 = _dataset_from_source(data_source)
    data_source = _relative_data_source(data_source)
    manifest = build_manifest_fields(
        artifact_path, physics_version=physics_version, dataset_id=dataset_id, dataset_sha256=dataset_sha256
    )
    entry = {
        "name": name,
        "version": version or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "data_source": data_source,
        "params": params or {},
        "python": platform.python_version(),
        **manifest,
    }
    with _registry_lock:
        entries = _read_for_append()
        entries.append(entry)
        _atomic_write_json(REGISTRY_PATH, entries)
    return entry


# ----------------------------------------------------------------------------- verification


def verify_mode() -> str:
    raw = os.getenv("ARTIFACT_VERIFY", "").strip().lower()
    if not raw:
        return "enforce"
    if raw not in VERIFY_MODES:
        logger.warning("Unknown ARTIFACT_VERIFY=%r; treating it as 'enforce'", raw)
        return "enforce"
    return raw


def _check(paths: Sequence[str | Path]) -> dict[str, Any]:
    """Verify ``paths`` against the newest registry entry that lists all of them.
    Returns that entry; raises ModelUnavailableError otherwise."""
    rels: list[str] = []
    for p in paths:
        try:
            rels.append(to_relative(p))
        except (ValueError, OSError):
            raise ModelUnavailableError(f"{Path(str(p)).name} is outside the project root") from None
    try:
        entries = read_registry()
    except FileNotFoundError:
        raise ModelUnavailableError("model registry not found") from None
    except (OSError, ValueError):
        raise ModelUnavailableError("model registry unreadable") from None

    entry = next(
        (e for e in reversed(entries) if isinstance(e.get("files"), dict) and all(r in e["files"] for r in rels)),
        None,
    )
    if entry is None:
        raise ModelUnavailableError(f"no manifest entry covers {', '.join(rels)}")
    if entry.get("physics_version") != PHYSICS_VERSION:
        raise ModelUnavailableError(
            f"{entry.get('name')} {entry.get('version')}: physics_version {entry.get('physics_version')!r} "
            f"!= active {PHYSICS_VERSION!r}"
        )
    for rel in rels:
        expected = entry["files"][rel]
        path = _resolve_in_root(rel)
        if not path.is_file():
            raise ModelUnavailableError(f"{rel} is missing")
        if not isinstance(expected, dict) or not expected.get("sha256"):
            raise ModelUnavailableError(f"{rel} has no recorded sha256")
        if expected.get("size") is not None and path.stat().st_size != expected["size"]:
            raise ModelUnavailableError(f"{rel} size differs from the manifest")
        if not hmac.compare_digest(sha256_file(path), str(expected["sha256"])):
            raise ModelUnavailableError(f"{rel} sha256 differs from the manifest")
    return entry


def ensure_verified(paths: Sequence[str | Path], *, artifact: str) -> None:
    """Loader hook: call BEFORE reading any of ``paths``. See the module docstring
    for the three ARTIFACT_VERIFY modes."""
    mode = verify_mode()
    if mode == "off":
        return
    try:
        _check(paths)
    except ModelUnavailableError as exc:
        if mode == "warn":
            logger.warning("ARTIFACT_VERIFY=warn: %s failed verification (%s); loading anyway", artifact, exc.reason)
            return
        logger.error("Refusing to load %s: %s", artifact, exc.reason)
        raise
