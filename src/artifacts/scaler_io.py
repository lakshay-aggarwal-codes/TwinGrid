"""Scaler persistence as plain JSON (no pickle).

Only the two scaler types the project uses are supported -- ``StandardScaler`` and
``MinMaxScaler``. Anything else raises :class:`UnsupportedScalerError`; it is never guessed at
or "best-effort" serialised, because a silently wrong scaler corrupts every model input.

The JSON stores each fitted array with its dtype and the exact values. Python's ``repr`` of a
float is round-trip exact, and a float32 value is exactly representable as a float64, so
``scaler_from_dict(scaler_to_dict(s))`` reproduces ``s.transform`` bit for bit (the tests assert
agreement within 1e-12 on 10 000 random rows, which is far looser than what is achieved).

Integrity is NOT this module's job: the file's SHA-256 is recorded in the registry manifest and
checked by the ArtifactGate before any loader in ``loaders.py`` hands the file to this module.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

SCALER_FORMAT = "twingrid-scaler"
SCALER_FORMAT_VERSION = 1
SUPPORTED_SCALERS = ("StandardScaler", "MinMaxScaler")
_DTYPES = ("float32", "float64")

_STANDARD_ARRAYS = ("mean_", "var_", "scale_")
_MINMAX_ARRAYS = ("scale_", "min_", "data_min_", "data_max_", "data_range_")


class ScalerFormatError(ValueError):
    """The JSON is not a well-formed twingrid-scaler document."""


class UnsupportedScalerError(ScalerFormatError):
    """A scaler type other than StandardScaler / MinMaxScaler."""


# ----------------------------------------------------------------------------- export


def _array_to_json(value: Any, name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    arr = np.asarray(value)
    if arr.dtype.name not in _DTYPES:
        raise ScalerFormatError(f"{name}: unsupported dtype {arr.dtype.name!r}")
    if arr.ndim != 1:
        raise ScalerFormatError(f"{name}: expected a 1-D array, got ndim={arr.ndim}")
    if not np.all(np.isfinite(arr)):
        raise ScalerFormatError(f"{name}: contains NaN or infinity")
    return {"dtype": arr.dtype.name, "values": arr.tolist()}


def _scalar_count(scaler: Any) -> int:
    seen = getattr(scaler, "n_samples_seen_", None)
    if seen is None or np.ndim(seen) != 0:
        raise ScalerFormatError("n_samples_seen_ must be a single integer (partial_fit with NaNs is unsupported)")
    return int(seen)


def scaler_type_name(scaler: Any) -> str:
    """Name of a supported scaler class, else :class:`UnsupportedScalerError`.

    The module is checked too, so a look-alike class defined elsewhere is not accepted.
    """
    cls = type(scaler)
    if cls.__name__ not in SUPPORTED_SCALERS or not cls.__module__.startswith("sklearn.preprocessing"):
        raise UnsupportedScalerError(
            f"unsupported scaler type {cls.__module__}.{cls.__name__}; supported: {', '.join(SUPPORTED_SCALERS)}"
        )
    return cls.__name__


def scaler_to_dict(scaler: Any) -> dict[str, Any]:
    """JSON-able description of a FITTED StandardScaler / MinMaxScaler."""
    kind = scaler_type_name(scaler)
    if not hasattr(scaler, "n_features_in_"):
        raise ScalerFormatError("scaler is not fitted")
    if kind == "StandardScaler":
        params: dict[str, Any] = {"with_mean": bool(scaler.with_mean), "with_std": bool(scaler.with_std)}
        names = _STANDARD_ARRAYS
    else:
        low, high = scaler.feature_range
        params = {"feature_range": [float(low), float(high)], "clip": bool(scaler.clip)}
        names = _MINMAX_ARRAYS
    arrays = {name: _array_to_json(getattr(scaler, name, None), name) for name in names}
    doc = {
        "format": SCALER_FORMAT,
        "format_version": SCALER_FORMAT_VERSION,
        "type": kind,
        "n_features": int(scaler.n_features_in_),
        "n_samples_seen": _scalar_count(scaler),
        "params": params,
        "arrays": arrays,
    }
    _validate(doc)
    return doc


def dumps_scaler(scaler: Any) -> str:
    return json.dumps(scaler_to_dict(scaler), indent=2, sort_keys=True, allow_nan=False) + "\n"


def dump_scaler_json(scaler: Any, path: str | Path) -> Path:
    """Atomically write ``scaler`` as JSON to ``path`` (temp file + ``os.replace``)."""
    path = Path(path)
    text = dumps_scaler(scaler)  # serialise first: a failure leaves nothing behind
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp, 0o644)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


# ----------------------------------------------------------------------------- import


def _reject_constant(token: str) -> None:
    raise ScalerFormatError(f"non-finite number {token} is not allowed")


def _validate(doc: Any) -> None:
    if not isinstance(doc, dict):
        raise ScalerFormatError("scaler document must be a JSON object")
    if doc.get("format") != SCALER_FORMAT or doc.get("format_version") != SCALER_FORMAT_VERSION:
        raise ScalerFormatError("not a twingrid-scaler v1 document")
    kind = doc.get("type")
    if kind not in SUPPORTED_SCALERS:
        raise UnsupportedScalerError(f"unsupported scaler type {kind!r}; supported: {', '.join(SUPPORTED_SCALERS)}")
    n_features = doc.get("n_features")
    if not isinstance(n_features, int) or isinstance(n_features, bool) or n_features < 1:
        raise ScalerFormatError("n_features must be a positive integer")
    seen = doc.get("n_samples_seen")
    if not isinstance(seen, int) or isinstance(seen, bool) or seen < 0:
        raise ScalerFormatError("n_samples_seen must be a non-negative integer")
    params, arrays = doc.get("params"), doc.get("arrays")
    if not isinstance(params, dict) or not isinstance(arrays, dict):
        raise ScalerFormatError("params and arrays must be objects")
    names = _STANDARD_ARRAYS if kind == "StandardScaler" else _MINMAX_ARRAYS
    if set(arrays) != set(names):
        raise ScalerFormatError(f"arrays must be exactly {sorted(names)}")
    for name, spec in arrays.items():
        if spec is None:
            if kind != "StandardScaler":  # StandardScaler(with_mean/with_std=False) legitimately has null arrays
                raise ScalerFormatError(f"{name} may not be null for {kind}")
            continue
        if not isinstance(spec, dict) or spec.get("dtype") not in _DTYPES or not isinstance(spec.get("values"), list):
            raise ScalerFormatError(f"{name}: malformed array")
        values = spec["values"]
        if len(values) != n_features:
            raise ScalerFormatError(f"{name}: expected {n_features} values, got {len(values)}")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
            raise ScalerFormatError(f"{name}: values must be numbers")
        if not np.all(np.isfinite(np.asarray(values, dtype=np.float64))):
            raise ScalerFormatError(f"{name}: contains NaN or infinity")
    if kind == "StandardScaler":
        if set(params) != {"with_mean", "with_std"} or not all(isinstance(v, bool) for v in params.values()):
            raise ScalerFormatError("StandardScaler params must be exactly with_mean/with_std booleans")
        if params["with_mean"] and arrays["mean_"] is None:
            raise ScalerFormatError("with_mean is true but mean_ is null")
        if params["with_std"] and arrays["scale_"] is None:
            raise ScalerFormatError("with_std is true but scale_ is null")
    else:
        rng = params.get("feature_range")
        if set(params) != {"feature_range", "clip"} or not isinstance(params["clip"], bool):
            raise ScalerFormatError("MinMaxScaler params must be exactly feature_range/clip")
        if not (
            isinstance(rng, list)
            and len(rng) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in rng)
            and rng[0] < rng[1]
        ):
            raise ScalerFormatError("feature_range must be [low, high] with low < high")
        if any(spec is None for spec in arrays.values()):
            raise ScalerFormatError("MinMaxScaler arrays may not be null")


def _array_from_json(spec: dict[str, Any] | None) -> np.ndarray | None:
    if spec is None:
        return None
    return np.array(spec["values"], dtype=np.dtype(spec["dtype"]))


def scaler_from_dict(doc: dict[str, Any]) -> Any:
    """A fitted sklearn scaler equal to the one that was exported."""
    _validate(doc)
    arrays = {name: _array_from_json(spec) for name, spec in doc["arrays"].items()}
    params = doc["params"]
    if doc["type"] == "StandardScaler":
        from sklearn.preprocessing import StandardScaler

        scaler: Any = StandardScaler(with_mean=params["with_mean"], with_std=params["with_std"])
    else:
        from sklearn.preprocessing import MinMaxScaler

        scaler = MinMaxScaler(feature_range=tuple(params["feature_range"]), clip=params["clip"])
    for name, value in arrays.items():
        setattr(scaler, name, value)
    scaler.n_features_in_ = doc["n_features"]
    scaler.n_samples_seen_ = doc["n_samples_seen"]
    return scaler


def loads_scaler(text: str | bytes) -> Any:
    try:
        doc = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ScalerFormatError(f"scaler JSON is not valid: {exc.msg}") from None
    return scaler_from_dict(doc)


def read_scaler_json(path: str | Path) -> Any:
    """Parse ``path``. NOTE: does no integrity check -- call it through ``loaders.load_scaler``."""
    return loads_scaler(Path(path).read_bytes())
