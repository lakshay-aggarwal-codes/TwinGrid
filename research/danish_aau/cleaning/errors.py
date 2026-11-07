"""Typed errors of the cleaning stage. A refusal is always preferred to a silent coercion."""

from __future__ import annotations


class CleaningError(RuntimeError):
    """The input breaks a cleaning precondition (duplicate row ordinal, malformed timestamp text, ...)."""
