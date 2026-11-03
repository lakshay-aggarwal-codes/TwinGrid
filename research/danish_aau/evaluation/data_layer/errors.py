"""Exception hierarchy for the Phase 2 data layer. Every refusal is a typed error with a plain-language reason."""

from __future__ import annotations


class DataLayerError(RuntimeError):
    """Base class for every Phase 2 error."""


class DataConfigError(DataLayerError, ValueError):
    """The data configuration is malformed or selects something the data layer does not allow."""

    def __init__(self, problems: list[str] | str):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("; ".join(self.problems))


class DiscoveryError(DataLayerError):
    """A registered source file is missing/ambiguous, or an unregistered file was requested."""


class ReaderError(DataLayerError):
    """The CSV could not be read consistently (header problem, file changed between passes, bad structure)."""


class TimestampFormatError(DataLayerError, ValueError):
    """A timestamp format that would infer or convert a timezone was configured."""


class NumericParseError(ReaderError):
    """A non-missing measurement cell is not a finite number (and ``non_numeric = "raise"``)."""


class MaterialisationError(DataLayerError):
    """A full in-memory copy of an observation set was requested without the explicit confirmation/limits."""


class PolicyNotApproved(DataLayerError):
    """A sensitivity policy or reducer was requested that has not been approved in the data configuration."""


class AlignmentError(DataLayerError, ValueError):
    """An alignment request is invalid (missing tolerance, bad columns, layer/provenance mismatch, ...)."""


class ClockMismatchError(AlignmentError):
    """The two series do not share a declared clock/time basis; no silent assumption is made."""


class UnsafeDerivedPath(DataLayerError, ValueError):
    """A derived output path would overlap the raw dataset or a production location."""
