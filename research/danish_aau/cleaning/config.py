"""Cleaning switches. Everything defaults to the behaviour that needs no owner input."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CleanConfig:
    """Optional policies. The defaults produce no flags: limits and the flatline switch are owner decisions.

    range_limits    {"temperature": ("lo", "hi"), "power": ("lo", "hi")} as decimal TEXT in the unit (degC / W).
                    Empty = range check not evaluated (no limits are established). A value outside is FLAGGED,
                    never clipped or dropped.
    flatline_min_run  None = flatline flag off. An integer N >= 2 flags every cell inside a run of >= N identical
                    canonical values at consecutive stored seconds.
    flatline_gap_step None = use the locked protocol's screening gap step; a larger step breaks a run.
    """

    range_limits: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    flatline_min_run: int | None = None
    flatline_gap_step: int | None = None

    def __post_init__(self) -> None:
        for k, v in self.range_limits.items():
            if k not in ("temperature", "power") or len(v) != 2:
                raise ValueError(f"range_limits entry {k!r} must be 'temperature' or 'power' with (lo, hi) text")
        if self.flatline_min_run is not None and (
            isinstance(self.flatline_min_run, bool)
            or not isinstance(self.flatline_min_run, int)
            or self.flatline_min_run < 2
        ):
            raise ValueError("flatline_min_run must be None or an integer >= 2")
