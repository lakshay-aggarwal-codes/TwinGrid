"""Registry of experiments a run can execute: ``name -> fn(config, seeds, rng_factory) -> results``.

An experiment returns the results object described in ``report.py`` (everything that goes into
``results.json``). It must derive every random number from ``rng_factory(seed, *stream)``, must not
read the clock, the environment or the network, and must not write files. Later tasks register
their evaluation here (``register("eval_policies", ...)``) so that they inherit the run directory,
manifest, canonical output, report generation and ``verify`` for free.
"""

from __future__ import annotations

from typing import Any, Callable

from . import toy

ExperimentFn = Callable[[dict[str, Any], list[int], Callable[..., Any]], dict[str, Any]]

_REGISTRY: dict[str, ExperimentFn] = {"toy": toy.run}


class UnknownExperiment(KeyError):
    pass


def register(name: str, fn: ExperimentFn, *, replace: bool = False) -> None:
    if name in _REGISTRY and not replace:
        raise ValueError(f"experiment {name!r} is already registered")
    _REGISTRY[name] = fn


def get(name: str) -> ExperimentFn:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownExperiment(f"unknown experiment {name!r}; known: {', '.join(sorted(_REGISTRY))}") from None


def names() -> list[str]:
    return sorted(_REGISTRY)
