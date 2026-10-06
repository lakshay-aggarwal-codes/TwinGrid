"""Canonical JSON and hashing helpers (contract 11.2: canonical JSON, sorted keys, fixed float formatting).

Rules, applied identically when a file is written and when it is re-checked:

* object keys sorted, two-space indent, ASCII only, one trailing newline, ``\\n`` line endings;
* floats are written with Python's shortest round-trip ``repr`` (deterministic on a given
  platform); ``-0.0`` is written as ``0.0``; NaN and infinity are refused (they have no JSON form
  and silently differ between libraries);
* numpy scalars/arrays and tuples are converted to plain JSON types first;
* results may be rounded to a fixed number of significant digits (:func:`round_sig`) so that
  last-bit noise from a different BLAS does not change the text on another platform.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

DEFAULT_SIG_DIGITS = 12
_TEXT_SUFFIXES = {".json", ".lock", ".txt", ".md", ".csv", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".svg"}


class CanonicalError(ValueError):
    """The object cannot be written as canonical JSON."""


def normalise(obj: Any, path: str = "$") -> Any:
    """Plain-JSON copy of ``obj`` (dict/list/str/int/float/bool/None); raises CanonicalError otherwise."""
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise CanonicalError(f"{path}: non-finite number {obj!r} cannot be written")
        return 0.0 if obj == 0.0 else float(obj)
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if not isinstance(key, str):
                raise CanonicalError(f"{path}: object keys must be strings, got {type(key).__name__}")
            out[key] = normalise(value, f"{path}.{key}")
        return out
    if isinstance(obj, (list, tuple)):
        return [normalise(v, f"{path}[{i}]") for i, v in enumerate(obj)]
    module = type(obj).__module__
    if module == "numpy" or module.startswith("numpy."):
        if hasattr(obj, "tolist"):
            return normalise(obj.tolist(), path)
    raise CanonicalError(f"{path}: {type(obj).__name__} is not JSON-serialisable")


def canonical_dumps(obj: Any) -> str:
    """The canonical text of ``obj`` (ends with a newline)."""
    return json.dumps(normalise(obj), sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"


def canonical_bytes(obj: Any) -> bytes:
    return canonical_dumps(obj).encode("ascii")


def canonical_compact(obj: Any) -> str:
    """Single-line canonical form, for hashing structures."""
    return json.dumps(normalise(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def round_sig(obj: Any, digits: int = DEFAULT_SIG_DIGITS) -> Any:
    """Copy of ``obj`` with every float rounded to ``digits`` significant digits."""
    if not 1 <= digits <= 17:
        raise ValueError("digits must be in 1..17")
    obj = normalise(obj)

    def walk(v: Any) -> Any:
        if isinstance(v, float):
            return 0.0 if v == 0.0 else float(f"{v:.{digits}g}")
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    return walk(obj)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(obj: Any) -> str:
    return sha256_bytes(canonical_compact(obj).encode("ascii"))


def sha256_raw_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_text_bytes(data: bytes) -> bytes:
    """Line-ending / encoding-neutral form of a text file: UTF-16 (BOM) -> UTF-8, CRLF/CR -> LF."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        data = data.decode("utf-16").encode("utf-8")
    elif data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def sha256_input_file(path: Path) -> str:
    """SHA-256 of an INPUT file (config, lock file, dataset manifest, pre-registration).

    Text files (by suffix) are hashed after line endings are normalised to LF and a UTF-16/BOM
    encoding is converted to UTF-8, so a checkout with ``core.autocrlf`` (Windows) hashes the same
    as one without. Everything else is hashed byte for byte. Model artifacts always use
    :func:`sha256_raw_file`, matching the registry.
    """
    path = Path(path)
    if path.suffix.lower() in _TEXT_SUFFIXES:
        return sha256_bytes(_normalise_text_bytes(path.read_bytes()))
    return sha256_raw_file(path)
