"""Typed refusals of the dataset bundle. A refusal never leaves a partial bundle in place."""

from __future__ import annotations


class BundleError(Exception):
    """The bundle cannot be built, verified or read; the message says why."""


class BundleNotFound(BundleError):
    """No bundle file at the configured path (dataset routes must answer 404, identical to an unknown route)."""
