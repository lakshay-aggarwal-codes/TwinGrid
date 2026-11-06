"""Typed refusals for the identity mapping (Task 13)."""

from __future__ import annotations


class MappingError(Exception):
    """Base class: the mapping cannot be used as asked."""


class MappingValidationError(MappingError):
    """The mapping document failed validation; ``errors`` lists every ``CODE: message``."""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__(
            "; ".join(self.errors[:5]) + (f" (+{len(self.errors) - 5} more)" if len(self.errors) > 5 else "")
        )


class UnmappedEntityError(MappingError):
    """A source column or id has no mapping entry (never guessed)."""


class AmbiguousMappingError(MappingError):
    """More than one mapping entry matches (never resolved by similarity or position)."""


class DerivationNotApproved(MappingError):
    """A derived value was requested without an owner-approved derivation."""
