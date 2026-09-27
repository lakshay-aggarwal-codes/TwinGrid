"""Benchmark a PUE/WUE reading against published industry figures, instead
of an arbitrary hand-picked threshold.

Reference: Uptime Institute Global Data Center Survey 2024 (published July
2024) reports an industry-average PUE of 1.56, essentially flat since 2020
(range 1.55-1.59); capacity-weighted (by IT MW) average is 1.47, reflecting
that larger/newer facilities skew more efficient.
https://datacenter.uptimeinstitute.com/rs/711-RIA-145/images/2024.GlobalDataCenterSurvey.Report.pdf

This is an ANNUAL survey -- PUE_INDUSTRY_AVERAGE_2024 below will go stale;
check for a newer Uptime survey figure before relying on this for anything
published externally (ESG report, marketing claim, etc.).
"""

from __future__ import annotations

PUE_INDUSTRY_AVERAGE_2024 = 1.56
PUE_INDUSTRY_CAPACITY_WEIGHTED_2024 = 1.47

# Qualitative bands. "Elite" reflects commonly-cited modern hyperscale fleet
# PUE (~1.1-1.2, e.g. major hyperscalers' published sustainability reports);
# the rest are derived directly from the Uptime figures above, not a
# separate source.
PUE_BANDS = [
    (1.2, "elite", "Hyperscale-competitive efficiency"),
    (1.4, "efficient", "Better than the capacity-weighted industry average (1.47)"),
    (1.6, "average", "In line with the 2024 industry average (1.56)"),
    (float("inf"), "below_average", "Worse than the 2024 industry average (1.56)"),
]


def benchmark_pue(pue: float) -> dict[str, object]:
    """Classify a PUE reading against the Uptime Institute 2024 industry
    figures. Returns the band, a human-readable note, and both reference
    numbers for the caller to cite directly (e.g. in an ESG report)."""
    for ceiling, band, note in PUE_BANDS:
        if pue <= ceiling:
            return {
                "pue": pue,
                "band": band,
                "note": note,
                "industry_average_2024": PUE_INDUSTRY_AVERAGE_2024,
                "industry_capacity_weighted_2024": PUE_INDUSTRY_CAPACITY_WEIGHTED_2024,
                "source": "Uptime Institute Global Data Center Survey 2024",
            }
    # Unreachable (last band ceiling is inf) but keeps type-checkers happy.
    raise AssertionError("unreachable")
