"""Explicit ``numpy.random.Generator`` seeding (contract 11.2: no global ``np.random.seed``).

Every random draw in an experiment comes from a Generator built here from ``(seed, *stream)``.
The stream labels (``"scenario", 3``) are hashed into the SeedSequence ``spawn_key``, so adding a
new stream or drawing in a different order never changes the numbers of the existing streams.
"""

from __future__ import annotations

import hashlib
import random
from contextlib import contextmanager
from typing import Iterator

import numpy as np


class GlobalRngTouched(RuntimeError):
    """An experiment used (or reseeded) the process-global numpy / random state."""


def _label_to_ints(label: str | int) -> tuple[int, ...]:
    if isinstance(label, bool) or not isinstance(label, (str, int)):
        raise TypeError("stream labels must be str or int")
    if isinstance(label, int):
        if label < 0:
            raise ValueError("integer stream labels must be >= 0")
        return (0, label)
    digest = hashlib.sha256(label.encode("utf-8")).digest()
    return (1, int.from_bytes(digest[:8], "big"))


def make_rng(seed: int, *stream: str | int) -> np.random.Generator:
    """A fresh Generator for ``seed`` and the named stream (same inputs -> identical sequence)."""
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    key: tuple[int, ...] = ()
    for label in stream:
        key += _label_to_ints(label)
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(entropy=seed, spawn_key=key)))


class RngFactory:
    """What an experiment receives: ``rng(seed, "scenario", i)`` -> Generator. Records every stream used."""

    def __init__(self) -> None:
        self.streams: set[tuple] = set()

    def __call__(self, seed: int, *stream: str | int) -> np.random.Generator:
        self.streams.add((seed, *stream))
        return make_rng(seed, *stream)


def _global_state() -> tuple:
    return (np.random.get_state(legacy=True)[1].tobytes(), np.random.get_state(legacy=True)[2:], random.getstate())


@contextmanager
def forbid_global_rng() -> Iterator[None]:
    """Fail if the body touches ``np.random.*`` module-level functions or ``random.*``.

    Detected by comparing the global generators' state before and after. (A draw that is exactly
    undone, or from a copy of the state, is not detectable; the AST test covers the seeding calls.)
    """
    before = _global_state()
    yield
    if _global_state() != before:
        raise GlobalRngTouched("the experiment used the global numpy/random generator; use the provided rng factory")
