"""The ArtifactGate and the ONLY place models, scalers and configs are read from disk (T19).

Every load path in the project goes through :func:`authorize` (one :class:`ArtifactGate`) and then
one of the ``load_*`` functions below. Nothing else may call ``joblib.load``, ``pickle``,
``keras.models.load_model`` or ``PPO.load``; ``tests/test_artifact_gate.py`` enforces that with an
AST scan.

The gate (contract section 10.2/10.3) runs, in this order:

0. Status     only ``promoted`` artifacts load in the API process (the training profile also accepts
               ``candidate``, so a freshly trained candidate can be evaluated before promotion).
1. Integrity  every file's SHA-256 and size equal the manifest.            ``ARTIFACT_VERIFY``
2. Compat     physics_version, physics_params_hash, environment_version, observation_schema_hash,
               action_schema_hash, action_semantics_version, reward_version,
               safety_envelope_version and input_cadence_s equal the RUNNING values defined in
               ``src/versions.py`` -- unless a named, time-boxed ``compat_waiver`` excuses that
               field.                                                            ``ARTIFACT_COMPAT``
3. Trust      the file format is on the process's allow-list: json, npz (``allow_pickle=False``)
               and keras (``safe_mode=True``). ``.joblib`` / ``.pkl`` are never loadable, and an
               SB3 ``.zip`` only in the TRAINING profile.

A failed check raises a :class:`~src.model_registry.ModelUnavailableError` subclass; the caller
reports the feature as unavailable and the process keeps running. Nothing here trains, retries or
falls back.

Profiles. ``api`` (the default, and the only one the API process may use) vs ``training``. The API
locks itself to ``api`` at import of ``api/services/optimization_service.py``; a locked profile
cannot be changed by ``ARTIFACT_PROFILE``. Training scripts opt in with ``ARTIFACT_PROFILE=training``
or :func:`enter_training_profile`.

Escape hatches (non-production only; ``ENVIRONMENT=production`` ignores them and enforces):
``ARTIFACT_VERIFY=warn|off`` (integrity) and ``ARTIFACT_COMPAT=warn`` (compatibility). The format
allow-list and the status rule are never relaxed by them, except that ``ARTIFACT_VERIFY=off``
skips the registry entirely (tests and local experiments with no registry).

Keras files are not "inherently safe": ``safe_mode=True`` blocks the known code-execution route
(Lambda layers / arbitrary deserialisation) but a hostile ``.keras`` is an accepted residual risk,
mitigated by the hash gate, not eliminated by it.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from src import model_registry as mr
from src import versions
from src.artifacts import scaler_io
from src.model_registry import (  # noqa: F401  (re-exported: callers import the errors from here)
    ArtifactFormatNotAllowed,
    ArtifactIncompatible,
    ArtifactIntegrityError,
    ArtifactLoadError,
    ArtifactManifestError,
    ArtifactNotPromoted,
    ModelUnavailableError,
)

logger = logging.getLogger(__name__)

PROFILES = ("api", "training")
ALLOWED_FORMATS: dict[str, frozenset[str]] = {
    "api": frozenset({"json", "npz", "keras"}),
    "training": frozenset({"json", "npz", "keras", "sb3_zip"}),
}
ALLOWED_STATUSES: dict[str, frozenset[str]] = {
    "api": frozenset({"promoted"}),
    "training": frozenset({"candidate", "promoted"}),
}
FAILURE_REASONS = ("manifest", "status", "integrity", "incompatible", "format", "load_error", "unavailable")
COMPAT_MODES = ("enforce", "warn")

_state_lock = threading.Lock()
_locked_profile: str | None = None
_failure_counts: dict[str, int] = {}
_unavailable: dict[str, str] = {}  # artifact label -> failure code, cleared when it next authorizes cleanly


# ----------------------------------------------------------------------------- profile & modes


def lock_profile(profile: str) -> None:
    """Pin this process to ``profile`` for good; ``ARTIFACT_PROFILE`` can no longer change it."""
    global _locked_profile
    if profile not in PROFILES:
        raise ValueError(f"profile must be one of {PROFILES}")
    with _state_lock:
        if _locked_profile not in (None, profile):
            raise RuntimeError(f"artifact profile is already locked to {_locked_profile!r}")
        _locked_profile = profile


def enter_training_profile() -> None:
    """For training / migration scripts. Refuses in a process that already locked itself to ``api``."""
    lock_profile("training")


def current_profile() -> str:
    if _locked_profile is not None:
        return _locked_profile
    raw = os.getenv("ARTIFACT_PROFILE", "").strip().lower()
    if raw in PROFILES:
        return raw
    if raw:
        logger.warning("Unknown ARTIFACT_PROFILE=%r; using 'api'", raw)
    return "api"


def compat_mode() -> str:
    """``ARTIFACT_COMPAT``: enforce (default) | warn. Production always enforces."""
    raw = os.getenv("ARTIFACT_COMPAT", "").strip().lower()
    mode = "enforce"
    if raw:
        if raw in COMPAT_MODES:
            mode = raw
        else:
            logger.warning("Unknown ARTIFACT_COMPAT=%r; treating it as 'enforce'", raw)
    if mode != "enforce" and mr.is_production():
        logger.error("ARTIFACT_COMPAT=%s is ignored when ENVIRONMENT=production; enforcing", mode)
        return "enforce"
    return mode


def reset_for_tests() -> None:
    """Forget the profile lock and all failure state. Tests only."""
    global _locked_profile
    with _state_lock:
        _locked_profile = None
        _failure_counts.clear()
        _unavailable.clear()


# ----------------------------------------------------------------------------- telemetry


def _record_failure(artifact: str, code: str) -> None:
    code = code if code in FAILURE_REASONS else "unavailable"
    with _state_lock:
        _failure_counts[code] = _failure_counts.get(code, 0) + 1
        _unavailable[artifact] = code


def _record_ok(artifact: str) -> None:
    with _state_lock:
        _unavailable.pop(artifact, None)


def record_load_failure(artifact: str, code: str) -> None:
    """For callers that refuse a model for a reason of their own (e.g. a shape mismatch)."""
    _record_failure(artifact, code)


def failure_counts() -> dict[str, int]:
    """``model_load_failures_total`` by reason; every known reason is present (0 until it happens)."""
    with _state_lock:
        return {reason: _failure_counts.get(reason, 0) for reason in FAILURE_REASONS}


def waiver_samples() -> list[tuple[tuple[str, str, str], float]]:
    """One ``(model_id, name, expires_after_task)`` per PROMOTED artifact that carries a waiver,
    read from the registry now (so it is visible before the first load and disappears the moment
    the waiver is removed)."""
    try:
        entries = mr.read_registry()
    except (OSError, ValueError):
        return []
    out = []
    for entry in entries:
        waiver = entry.get("compat_waiver")
        if entry.get("status") == "promoted" and isinstance(waiver, dict):
            out.append(
                ((str(entry.get("model_id")), str(entry.get("name")), str(waiver.get("expires_after_task"))), 1.0)
            )
    return out


def health_snapshot() -> dict[str, Any]:
    """Input for a readiness probe: ``degraded`` while any artifact that was asked for is refused.

    NOTE: ``/readyz`` itself lives in ``api/routes`` (outside T19's allowed files); this is the
    function it should call.
    """
    with _state_lock:
        unavailable = dict(_unavailable)
    return {
        "status": "degraded" if unavailable else "ok",
        "unavailable": unavailable,
        "failures": failure_counts(),
        "waivers": [list(labels) for labels, _ in waiver_samples()],
    }


class _PrometheusCollector:
    """Exposes ``model_load_failures_total{reason}`` and ``model_compat_waiver_active{...}``."""

    def collect(self):  # pragma: no cover - needs prometheus_client; covered by an importorskip test
        from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

        failures = CounterMetricFamily(
            "model_load_failures", "Model loads refused by the ArtifactGate or failed in a loader", labels=["reason"]
        )
        for reason, count in failure_counts().items():
            failures.add_metric([reason], count)
        yield failures
        waivers = GaugeMetricFamily(
            "model_compat_waiver_active",
            "1 for each promoted artifact currently loading under a compatibility waiver",
            labels=["model_id", "name", "expires_after_task"],
        )
        for labels, value in waiver_samples():
            waivers.add_metric(list(labels), value)
        yield waivers


_bound_registries: set[int] = set()


def bind_prometheus(registry: Any) -> bool:
    """Register the collector on ``registry`` once. False if prometheus_client is unavailable."""
    if id(registry) in _bound_registries:
        return True
    try:
        registry.register(_PrometheusCollector())
    except Exception:  # noqa: BLE001 - metrics must never stop the app from starting
        logger.warning("Could not register artifact metrics", exc_info=True)
        return False
    _bound_registries.add(id(registry))
    return True


# ----------------------------------------------------------------------------- the gate


@dataclass(frozen=True)
class ArtifactGrant:
    """Proof that ``paths`` passed the gate; the ``load_*`` functions accept it instead of re-checking."""

    entry: dict[str, Any] | None  # None only when ARTIFACT_VERIFY=off skipped the registry
    paths: frozenset[Path]
    profile: str
    waived_fields: tuple[str, ...] = ()


def evaluate_compat(
    entry: dict[str, Any], running: dict[str, Any] | None = None
) -> tuple[list[tuple[str, Any, Any]], list[tuple[str, Any, Any]]]:
    """Compare the manifest with the running values -> ``(blocking, waived)`` lists of
    ``(field, expected, actual)``. A field outside the kind's applicable set is compared only if
    the manifest recorded a (non-null) value for it."""
    kind = entry.get("kind")
    applicable = mr.COMPAT_FIELDS_BY_KIND.get(kind)  # type: ignore[arg-type]
    if applicable is None:
        raise ArtifactManifestError(f"unknown artifact kind {kind!r}")
    if running is None:
        try:
            running = versions.running_compat_values()
        except Exception as exc:  # noqa: BLE001 - fail closed, whatever went wrong
            raise ArtifactManifestError(f"cannot determine the running versions ({type(exc).__name__})") from None
    waiver = entry.get("compat_waiver")
    waived_fields = set(waiver.get("fields") or []) if isinstance(waiver, dict) else set()
    blocking: list[tuple[str, Any, Any]] = []
    waived: list[tuple[str, Any, Any]] = []
    for field in versions.COMPAT_FIELDS:
        expected, actual = running[field], entry.get(field)
        mismatch = actual != expected if field in applicable else (actual is not None and actual != expected)
        if mismatch:
            (waived if field in waived_fields else blocking).append((field, expected, actual))
    return blocking, waived


class ArtifactGate:
    """The single admission check for every artifact the project loads."""

    def __init__(self, profile: str | None = None) -> None:
        if profile is not None and profile not in PROFILES:
            raise ValueError(f"profile must be one of {PROFILES}")
        self._profile = profile

    @property
    def profile(self) -> str:
        return self._profile or current_profile()

    def authorize(self, paths: Iterable[str | Path], *, artifact: str) -> ArtifactGrant:
        """Run checks 0-3 on ``paths`` (all read together). Raises ModelUnavailableError."""
        path_list = [Path(p) for p in paths]
        if not path_list:
            raise ValueError("authorize() needs at least one path")
        try:
            grant = self._authorize(path_list, artifact)
        except ModelUnavailableError as exc:
            _record_failure(artifact, exc.code)
            logger.error("Refusing to load %s: %s", artifact, exc.reason)
            raise
        _record_ok(artifact)
        return grant

    def _authorize(self, paths: Sequence[Path], artifact: str) -> ArtifactGrant:
        profile = self.profile
        resolved = frozenset(p.resolve() for p in paths)
        if mr.verify_mode() == "off":
            for path in paths:
                self._check_format(path, None, profile)
            return ArtifactGrant(None, resolved, profile)

        rels = mr.to_relatives(paths)
        entry = mr.find_entry(rels)
        label = f"{entry.get('name')} {entry.get('version')}"
        if entry.get("manifest_version") != mr.MANIFEST_VERSION:
            raise ArtifactManifestError(f"{label} has a v{entry.get('manifest_version')} manifest, not v2; migrate it")
        problems = mr.validate_manifest(entry)
        if problems:
            raise ArtifactManifestError(f"{label}: invalid manifest ({'; '.join(problems[:3])})")

        # 0. status
        if entry["status"] not in ALLOWED_STATUSES[profile]:
            why = f" ({entry['status_reason']})" if entry.get("status_reason") else ""
            raise ArtifactNotPromoted(
                f"{label}: status {entry['status']!r} may not be loaded by the {profile} process{why}"
            )

        # 1. integrity
        try:
            mr.check_integrity(entry, rels)
        except ArtifactIntegrityError as exc:
            if mr.verify_mode() == "warn":
                logger.warning(
                    "ARTIFACT_VERIFY=warn: %s failed verification (%s); loading anyway", artifact, exc.reason
                )
            else:
                raise

        # 2. compatibility (+ waiver)
        blocking, waived = evaluate_compat(entry)
        if blocking:
            first = blocking[0]
            if compat_mode() == "warn":
                for field, expected, actual in blocking:
                    logger.warning(
                        "ARTIFACT_COMPAT=warn: %s %s=%r but running code has %r; loading anyway",
                        artifact,
                        field,
                        actual,
                        expected,
                    )
            else:
                raise ArtifactIncompatible(*first)
        if waived:
            waiver = entry["compat_waiver"]
            logger.warning(
                "COMPAT WAIVER %r in effect for %s (%s): fields %s are NOT compatible with the running code "
                "(%s). Must be removed by task %s.",
                waiver.get("name"),
                artifact,
                entry.get("model_id"),
                ", ".join(f"{f}: manifest {a!r} vs running {e!r}" for f, e, a in waived),
                waiver.get("reason"),
                waiver.get("expires_after_task"),
            )

        # 3. trust / safe loading
        for path, rel in zip(paths, rels):
            self._check_format(path, entry["files"][rel].get("format"), profile)
        return ArtifactGrant(entry, resolved, profile, tuple(f for f, _, _ in waived))

    @staticmethod
    def _check_format(path: Path, recorded: str | None, profile: str) -> None:
        actual = mr.format_for_path(path)
        if recorded is not None and recorded != actual:
            raise ArtifactFormatNotAllowed(f"{path.name}: manifest says format {recorded!r} but the file is {actual!r}")
        if actual not in ALLOWED_FORMATS[profile]:
            hint = " (SB3 zips are training-only)" if actual == "sb3_zip" else ""
            raise ArtifactFormatNotAllowed(
                f"{path.name}: format {actual!r} is not loadable by the {profile} process{hint}"
            )


def get_gate() -> ArtifactGate:
    return ArtifactGate()


def authorize(paths: Iterable[str | Path], *, artifact: str) -> ArtifactGrant:
    """Module-level convenience: ``ArtifactGate().authorize(paths, artifact=artifact)``."""
    return get_gate().authorize(paths, artifact=artifact)


# ----------------------------------------------------------------------------- loaders


def _grant_for(path: Path, artifact: str, grant: ArtifactGrant | None, expected_format: str) -> ArtifactGrant:
    if mr.format_for_path(path) != expected_format:
        _record_failure(artifact, "format")
        raise ArtifactFormatNotAllowed(f"{path.name}: expected a {expected_format} file")
    if grant is None:
        return authorize([path], artifact=artifact)
    if path.resolve() not in grant.paths:
        _record_failure(artifact, "manifest")
        raise ArtifactManifestError(f"{path.name} was not covered by the authorisation it was loaded with")
    return grant


def _load_failed(artifact: str, path: Path, exc: BaseException) -> ArtifactLoadError:
    _record_failure(artifact, "load_error")
    logger.error("Loading %s failed: %s: %s", artifact, type(exc).__name__, exc)
    return ArtifactLoadError(f"{path.name} could not be loaded ({type(exc).__name__})")


def load_json(path: str | Path, *, artifact: str, grant: ArtifactGrant | None = None) -> Any:
    path = Path(path)
    _grant_for(path, artifact, grant, "json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _load_failed(artifact, path, exc) from exc


def load_npz(path: str | Path, *, artifact: str, grant: ArtifactGrant | None = None) -> dict[str, np.ndarray]:
    """All arrays of an .npz, loaded with ``allow_pickle=False`` (object arrays are refused)."""
    path = Path(path)
    _grant_for(path, artifact, grant, "npz")
    try:
        with np.load(path, allow_pickle=False) as archive:
            return {name: archive[name] for name in archive.files}
    except (OSError, ValueError) as exc:
        raise _load_failed(artifact, path, exc) from exc


def load_scaler(path: str | Path, *, artifact: str, grant: ArtifactGrant | None = None) -> Any:
    """A fitted StandardScaler / MinMaxScaler from ``scaler.json`` (see scaler_io)."""
    path = Path(path)
    _grant_for(path, artifact, grant, "json")
    try:
        return scaler_io.read_scaler_json(path)
    except (OSError, scaler_io.ScalerFormatError) as exc:
        raise _load_failed(artifact, path, exc) from exc


def _get_keras() -> Any:
    try:
        import tensorflow as tf
    except ImportError as exc:
        raise ImportError("TensorFlow required. pip install tensorflow") from exc
    return tf.keras


def load_keras_model(path: str | Path, *, artifact: str, grant: ArtifactGrant | None = None) -> Any:
    """A Keras model loaded with ``safe_mode=True, compile=False``."""
    path = Path(path)
    _grant_for(path, artifact, grant, "keras")
    keras = _get_keras()
    try:
        return keras.models.load_model(str(path), compile=False, safe_mode=True)
    except Exception as exc:  # noqa: BLE001 - keras raises many types for a bad file
        raise _load_failed(artifact, path, exc) from exc


def load_sb3_zip_training_only(path: str | Path, *, artifact: str, grant: ArtifactGrant | None = None) -> Any:
    """Load a stable-baselines3 PPO zip. TRAINING PROFILE ONLY.

    An SB3 zip is a pickle container: loading one runs code chosen by whoever wrote the file. The
    API process therefore never gets here (it is locked to the ``api`` profile, where the format
    is refused), and nothing under ``api/`` may reference this function.
    """
    if current_profile() != "training":
        _record_failure(artifact, "format")
        raise ArtifactFormatNotAllowed(
            "SB3 zips are training-only; set ARTIFACT_PROFILE=training in a training process"
        )
    path = Path(path)
    _grant_for(path, artifact, grant, "sb3_zip")
    from stable_baselines3 import PPO

    try:
        return PPO.load(str(path))
    except Exception as exc:  # noqa: BLE001
        raise _load_failed(artifact, path, exc) from exc


def load_legacy_joblib_for_conversion(path: str | Path, *, expected_sha256: str) -> Any:
    """One-shot migration helper for ``scripts/convert_scalers.py``. TRAINING PROFILE ONLY.

    Unpickles ``path`` only if its SHA-256 equals ``expected_sha256`` (taken from the pre-T19
    registry or supplied by the operator who has confirmed the file). It exists so the legacy
    scalers can be converted to JSON once; after that no joblib file is loadable by anything.
    """
    if current_profile() != "training":
        raise ArtifactFormatNotAllowed("joblib files are not loadable by the API process")
    path = Path(path)
    digest = mr.sha256_file(path)
    if not hmac.compare_digest(digest, expected_sha256.strip().lower()):
        raise ArtifactIntegrityError(f"{path.name} sha256 differs from the expected value; refusing to unpickle it")
    import joblib

    return joblib.load(path)
