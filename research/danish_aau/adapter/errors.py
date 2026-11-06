"""Typed refusals of the Task 11 adapter. Every one means 'stop and report', never 'guess'."""

from __future__ import annotations

from ..evaluation.data_layer.errors import DataLayerError


class AdapterError(DataLayerError):
    """Base class for adapter refusals."""


class AdapterDiscoveryError(AdapterError):
    """A file is missing, ambiguous, unexpected, or disagrees with the manifest."""


class AdapterSchemaError(AdapterError):
    """A header has unexpected, missing, duplicate or unclassified columns (including an unexpected unit)."""
