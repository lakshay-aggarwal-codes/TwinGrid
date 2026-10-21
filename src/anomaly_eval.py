"""Anomaly evaluation per roadmap 13.4 (T26) -- the ONLY place anomaly metrics are computed.

The metric core (everything down to ``render_report``) is pure NumPy: no TensorFlow/scikit-learn, no I/O, deterministic.
The T18 section at the end (``T18: protocol-first held-out evaluation``) adds the rolling z-score baseline, cluster-bootstrap
intervals, event-level F1, a paired comparison, the protocol hash lock and the run driver; it reads files, imports pandas
lazily, and imports TensorFlow only inside ``AutoencoderScorer``.

A split is a set of independent SEGMENTS (T25: one segment per scenario). Alerts, episodes and detection windows
never cross a segment boundary, and every figure below is aggregated over segments. A single series is one segment.

DEFINITIONS (row index = one 5-minute sample WITHIN ITS SEGMENT; all index ranges are inclusive)
  event            one injection ``[start, end]`` from the generator's event table (never inferred runs)
  alert            scorer output at a row ``>= threshold``. NaN scores (window warming up) are NOT alerts.
  alert episode    maximal run of alert rows in which consecutive alerts are separated by FEWER than ``K``
                   non-alert rows (``b - a - 1 < K``; K = 1 merges only adjacent alerts)
  detection window ``[start, end + tolerance_rows]`` of an event (default tolerance 6 rows = 30 min, always reported)
  event detected   some alert row ``t`` in its detection window (an alert BEFORE ``start`` does not count)
  event recall     detected events / events                                      (PRIMARY, Wilson 95 % CI)
  detection delay  first alert in the detection window - start, over detected events (median, IQR)
  false positive   an alert episode that overlaps NO detection window
  false-alarm rate false-positive episodes per simulated day (rows x cadence / 86 400 s)
  event precision  episodes overlapping some detection window / all episodes    (Wilson 95 % CI)
  row-level        recall / precision / F1 over individual rows vs the event rows ``[start, end]``;
                   DIAGNOSTIC ONLY and always labelled "row-level"

RULES ENFORCED IN CODE
  * at least ``MIN_EVENTS`` (30) events, else ``InsufficientEventsError`` (a stop condition, not a warning);
    per-type figures are reported only for types with at least ``MIN_EVENTS_PER_TYPE`` (5) events
  * the threshold is chosen on the VALIDATION split only (``select_threshold`` refuses any other split id),
    by the rule "maximise event recall subject to a pre-registered false-alarm cap AND a pre-registered cap on
    the fraction of rows that alert"; if no threshold meets both the function raises -- caps are never loosened.
    The second cap is not optional: with false-alarm EPISODES as the only constraint, a threshold that alerts on
    every row forms one episode that overlaps the events, scoring full event recall with zero false alarms.
  * the TEST split is evaluated at most once per run (``OneShotEvaluator``) and only with a threshold fitted
    on validation
  * detector input cadence must equal the telemetry stream cadence (``check_cadence``)
  * report text may not contain a bare "recall" (``find_bare_recall`` / ``render_report``)

Everything reported is about SYNTHETIC injected anomalies; nothing here says anything about real faults.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Protocol, Sequence

import numpy as np

MIN_EVENTS = 30
MIN_EVENTS_PER_TYPE = 5
DEFAULT_TOLERANCE_ROWS = 6  # 30 minutes at 5-minute cadence
WILSON_Z_95 = 1.959963984540054
SECONDS_PER_DAY = 86_400.0
VALIDATION_SPLIT = "validation"
TEST_SPLIT = "test"


class AnomalyEvalError(ValueError):
    """Base class for evaluation contract violations."""


class InsufficientEventsError(AnomalyEvalError):
    """Fewer events than the contract requires (stop condition: raise injection counts, not metric thresholds)."""


class CadenceMismatchError(AnomalyEvalError):
    """The detector's input cadence differs from the telemetry stream's cadence."""


class LeakageError(AnomalyEvalError):
    """A threshold was requested from, or applied with, the wrong split."""


class NoFeasibleThresholdError(AnomalyEvalError):
    """No candidate threshold satisfies the false-alarm cap on validation."""


class SplitReuseError(AnomalyEvalError):
    """The test split was already evaluated in this run."""


@dataclass(frozen=True)
class Event:
    """One injected anomaly: inclusive row indices ``[start, end]``."""

    event_id: str
    type: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if int(self.start) != self.start or int(self.end) != self.end or self.start < 0 or self.end < self.start:
            raise AnomalyEvalError(
                f"event {self.event_id!r}: need integer 0 <= start <= end, got {self.start}, {self.end}"
            )


@dataclass(frozen=True)
class EvalConfig:
    cadence_s: float  # seconds per row (the stream cadence the detector was fitted for)
    k_gap: int  # K: episodes merge when fewer than K non-alert rows separate two alerts
    tolerance_rows: int = DEFAULT_TOLERANCE_ROWS
    min_events: int = MIN_EVENTS
    min_events_per_type: int = MIN_EVENTS_PER_TYPE

    def __post_init__(self) -> None:
        if not (math.isfinite(self.cadence_s) and self.cadence_s > 0):
            raise AnomalyEvalError(f"cadence_s must be finite and > 0, got {self.cadence_s!r}")
        if int(self.k_gap) != self.k_gap or self.k_gap < 1:
            raise AnomalyEvalError(f"k_gap must be an integer >= 1, got {self.k_gap!r}")
        if int(self.tolerance_rows) != self.tolerance_rows or self.tolerance_rows < 0:
            raise AnomalyEvalError(f"tolerance_rows must be an integer >= 0, got {self.tolerance_rows!r}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "cadence_s": self.cadence_s,
            "k_gap": self.k_gap,
            "tolerance_rows": self.tolerance_rows,
            "min_events": self.min_events,
            "min_events_per_type": self.min_events_per_type,
        }


# ------------------------------------------------------------------------------------------------ statistics
def wilson_interval(successes: int, n: int, z: float = WILSON_Z_95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (default 95 %). ``n == 0`` -> the uninformative (0, 1)."""
    if n < 0 or successes < 0 or successes > n:
        raise AnomalyEvalError(f"need 0 <= successes <= n, got {successes}/{n}")
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    # The Wilson interval always contains p mathematically; clamp away floating-point round-off at the edges.
    return min(p, max(0.0, centre - half)), max(p, min(1.0, centre + half))


def _ratio(num: int, den: int) -> Optional[float]:
    return None if den == 0 else num / den


def _proportion(successes: int, n: int) -> dict[str, Any]:
    lo, hi = wilson_interval(successes, n)
    return {"value": _ratio(successes, n), "successes": int(successes), "n": int(n), "ci95": [lo, hi]}


def check_cadence(detector_cadence_s: float, stream_cadence_s: float) -> None:
    """Stop condition: the detector must be fed at the cadence it was fitted for."""
    if detector_cadence_s != stream_cadence_s:
        raise CadenceMismatchError(
            f"detector input cadence {detector_cadence_s!r} s != telemetry stream cadence {stream_cadence_s!r} s"
        )


# ----------------------------------------------------------------------------------------------- core metrics
@dataclass(frozen=True)
class Segment:
    """One independent series (T25: one scenario): its scores and the events injected into it."""

    segment_id: str
    scores: Any  # 1-D array-like of floats, one per row; NaN = not scored
    events: tuple = ()


def _validate(scores: np.ndarray, events: Sequence[Event]) -> np.ndarray:
    scores = np.asarray(scores, dtype=float)
    if scores.ndim != 1 or scores.size == 0:
        raise AnomalyEvalError("scores must be a non-empty 1-D array (one value per row)")
    if np.any(np.isinf(scores)):
        raise AnomalyEvalError("scores must not contain +/-inf (NaN means 'not scored')")
    for e in events:
        if e.end >= scores.size:
            raise AnomalyEvalError(f"event {e.event_id!r} ends at row {e.end}, beyond the {scores.size} scored rows")
    return scores


def _validate_segments(segments: Sequence[Segment]) -> list[tuple[str, np.ndarray, tuple]]:
    if not segments:
        raise AnomalyEvalError("at least one segment is required")
    seen: set[str] = set()
    out = []
    for seg in segments:
        if seg.segment_id in seen:
            raise AnomalyEvalError(f"duplicate segment id {seg.segment_id!r}")
        seen.add(seg.segment_id)
        events = tuple(seg.events)
        out.append((seg.segment_id, _validate(np.asarray(seg.scores, dtype=float), events), events))
    ids = [e.event_id for _, _, evs in out for e in evs]
    if len(ids) != len(set(ids)):
        raise AnomalyEvalError("event ids must be unique across segments")
    return out


def alert_episodes(alert_rows: np.ndarray, k_gap: int) -> list[tuple[int, int]]:
    """Group sorted alert row indices into episodes (first_row, last_row); a gap is ``b - a - 1`` non-alert rows."""
    if alert_rows.size == 0:
        return []
    breaks = np.flatnonzero(np.diff(alert_rows) - 1 >= k_gap) + 1
    starts = np.concatenate(([0], breaks))
    ends = np.concatenate((breaks - 1, [alert_rows.size - 1]))
    return [(int(alert_rows[s]), int(alert_rows[e])) for s, e in zip(starts, ends)]


def _event_level(
    alert_rows: np.ndarray, events: Sequence[Event], cfg: EvalConfig
) -> tuple[list[bool], list[Optional[int]], list[tuple[int, int]], list[bool]]:
    """(detected per event, delay-in-rows per event or None, episodes, episode overlaps-some-event)."""
    detected: list[bool] = []
    delays: list[Optional[int]] = []
    for e in events:
        i = int(np.searchsorted(alert_rows, e.start, side="left"))
        if i < alert_rows.size and alert_rows[i] <= e.end + cfg.tolerance_rows:
            detected.append(True)
            delays.append(int(alert_rows[i]) - e.start)
        else:
            detected.append(False)
            delays.append(None)
    episodes = alert_episodes(alert_rows, cfg.k_gap)
    if episodes and events:
        ev_start = np.array([e.start for e in events])
        ev_end = np.array([e.end + cfg.tolerance_rows for e in events])
        ep_start = np.array([a for a, _ in episodes])
        ep_end = np.array([b for _, b in episodes])
        overlaps = np.any((ep_start[:, None] <= ev_end[None, :]) & (ep_end[:, None] >= ev_start[None, :]), axis=1)
        overlap_flags = [bool(x) for x in overlaps]
    else:
        overlap_flags = [False] * len(episodes)
    return detected, delays, episodes, overlap_flags


def _delay_summary(delays: Iterable[Optional[int]], cadence_s: float) -> dict[str, Any]:
    got = np.array([d for d in delays if d is not None], dtype=float)
    if got.size == 0:
        return {"n_detected": 0, "median_rows": None, "iqr_rows": None, "median_minutes": None, "iqr_minutes": None}
    q1, med, q3 = (float(x) for x in np.percentile(got, [25, 50, 75]))
    to_min = cadence_s / 60.0
    return {
        "n_detected": int(got.size),
        "median_rows": med,
        "iqr_rows": [q1, q3],
        "median_minutes": med * to_min,
        "iqr_minutes": [q1 * to_min, q3 * to_min],
    }


def _alerts_for(scores: np.ndarray, threshold: float) -> np.ndarray:
    alerts = np.zeros(scores.size, dtype=bool)
    scored = ~np.isnan(scores)
    alerts[scored] = scores[scored] >= threshold
    return alerts


@dataclass
class _Counts:
    """Per-segment tallies; summed across segments (episodes never span segments)."""

    n_rows: int = 0
    n_unscored: int = 0
    alert_rows: int = 0
    label_rows: int = 0
    tp_rows: int = 0
    episodes: int = 0
    fp_episodes: int = 0


def _segment_counts(scores: np.ndarray, events: Sequence[Event], threshold: float, cfg: EvalConfig):
    alerts = _alerts_for(scores, threshold)
    alert_rows = np.flatnonzero(alerts)
    detected, delays, episodes, overlap = _event_level(alert_rows, events, cfg)
    label = np.zeros(scores.size, dtype=bool)
    for e in events:
        label[e.start : e.end + 1] = True
    counts = _Counts(
        n_rows=int(scores.size),
        n_unscored=int(np.sum(np.isnan(scores))),
        alert_rows=int(alerts.sum()),
        label_rows=int(label.sum()),
        tp_rows=int(np.sum(alerts & label)),
        episodes=len(episodes),
        fp_episodes=sum(1 for o in overlap if not o),
    )
    return counts, detected, delays


def _row_level(c: _Counts) -> dict[str, Any]:
    recall = _ratio(c.tp_rows, c.label_rows)
    precision = _ratio(c.tp_rows, c.alert_rows)
    if recall is None or precision is None:
        f1 = None
    elif recall + precision == 0.0:
        f1 = 0.0
    else:
        f1 = 2.0 * precision * recall / (precision + recall)
    return {
        "label": "row-level (diagnostic only)",
        "row_recall": _proportion(c.tp_rows, c.label_rows),
        "row_precision": _proportion(c.tp_rows, c.alert_rows),
        "row_f1": f1,
        "alert_rows": c.alert_rows,
        "label_rows": c.label_rows,
    }


def evaluate_segments(
    segments: Sequence[Segment],
    threshold: float,
    cfg: EvalConfig,
    *,
    split_id: str,
    enforce_minimum: bool = True,
) -> dict[str, Any]:
    """All 13.4 metrics for one split (a set of independent segments) at one threshold. Deterministic.

    ``enforce_minimum=False`` exists only for hand-built unit tests; reports must use the default (the >= 30
    events rule is a stop condition).
    """
    segs = _validate_segments(segments)
    all_events = [e for _, _, evs in segs for e in evs]
    if enforce_minimum and len(all_events) < cfg.min_events:
        raise InsufficientEventsError(
            f"{len(all_events)} events in split {split_id!r}; at least {cfg.min_events} are required"
        )
    total = _Counts()
    detected_all: list[bool] = []
    delays_all: list[Optional[int]] = []
    for _, scores, events in segs:
        c, detected, delays = _segment_counts(scores, events, threshold, cfg)
        for f in total.__dataclass_fields__:
            setattr(total, f, getattr(total, f) + getattr(c, f))
        detected_all += detected
        delays_all += delays

    days = total.n_rows * cfg.cadence_s / SECONDS_PER_DAY
    tp_ep = total.episodes - total.fp_episodes
    by_type: dict[str, Any] = {}
    for t in sorted({e.type for e in all_events}):
        idx = [i for i, e in enumerate(all_events) if e.type == t]
        if len(idx) < cfg.min_events_per_type:
            by_type[t] = {
                "reported": False,
                "n_events": len(idx),
                "reason": f"fewer than {cfg.min_events_per_type} events",
            }
        else:
            by_type[t] = {
                "reported": True,
                "n_events": len(idx),
                "event_recall": _proportion(sum(detected_all[i] for i in idx), len(idx)),
                "detection_delay": _delay_summary([delays_all[i] for i in idx], cfg.cadence_s),
            }
    return {
        "split_id": split_id,
        "scope": "synthetic injected anomalies only",
        "config": cfg.as_dict(),
        "threshold": float(threshold),
        "n_segments": len(segs),
        "n_rows": total.n_rows,
        "n_unscored_rows": total.n_unscored,
        "simulated_days": days,
        "n_events": len(all_events),
        "event_recall": _proportion(sum(detected_all), len(all_events)),
        "detection_delay": _delay_summary(delays_all, cfg.cadence_s),
        "alert_episodes": total.episodes,
        "false_positive_episodes": total.fp_episodes,
        "false_alarm_episodes_per_simulated_day": total.fp_episodes / days,
        "event_precision": _proportion(tp_ep, total.episodes),
        "row_level": _row_level(total),
        "per_type": by_type,
    }


def evaluate(
    scores: Sequence[float] | np.ndarray,
    events: Sequence[Event],
    threshold: float,
    cfg: EvalConfig,
    *,
    split_id: str,
    enforce_minimum: bool = True,
) -> dict[str, Any]:
    """``evaluate_segments`` for a single continuous series (one segment)."""
    return evaluate_segments(
        [Segment("series", np.asarray(scores, dtype=float), tuple(events))],
        threshold,
        cfg,
        split_id=split_id,
        enforce_minimum=enforce_minimum,
    )


# ----------------------------------------------------------------------------- T25 event table adapter
REQUIRED_EVENT_COLUMNS: tuple[str, ...] = ("event_id", "scenario_id", "split", "type", "start_idx", "end_idx")


def events_from_records(records: Iterable[Mapping[str, Any]], *, split: Optional[str] = None) -> dict[str, list[Event]]:
    """Group T25 event-table rows by ``scenario_id``.

    T25 indices are PER SCENARIO and HALF-OPEN: ``[start_idx, end_idx)``. ``Event`` is inclusive, so
    ``end = end_idx - 1``. ``split`` keeps only that split's rows.
    """
    out: dict[str, list[Event]] = {}
    seen: set[str] = set()
    for rec in records:
        missing = [c for c in REQUIRED_EVENT_COLUMNS if c not in rec]
        if missing:
            raise AnomalyEvalError(f"event table is missing column(s) {missing}")
        if split is not None and rec["split"] != split:
            continue
        eid = str(rec["event_id"])
        if eid in seen:
            raise AnomalyEvalError(f"duplicate event id {eid!r}")
        seen.add(eid)
        try:
            start, end_excl = int(rec["start_idx"]), int(rec["end_idx"])
        except (TypeError, ValueError):
            raise AnomalyEvalError(f"event {eid!r}: start_idx/end_idx must be integers") from None
        if end_excl <= start:
            raise AnomalyEvalError(f"event {eid!r}: need start_idx < end_idx (half-open), got [{start}, {end_excl})")
        out.setdefault(str(rec["scenario_id"]), []).append(Event(eid, str(rec["type"]), start, end_excl - 1))
    return out


def load_events_csv(path: str | Path, *, split: Optional[str] = None) -> dict[str, list[Event]]:
    """Read a T25 ``events.csv`` (stdlib csv; no pandas) -> ``{scenario_id: [Event, ...]}``."""
    with open(path, newline="", encoding="utf-8") as fh:
        return events_from_records(csv.DictReader(fh), split=split)


def segments_from_scores(
    scores_by_scenario: Mapping[str, Sequence[float] | np.ndarray],
    events_by_scenario: Mapping[str, Sequence[Event]],
) -> list[Segment]:
    """One Segment per scored scenario (sorted by id). A scenario with no events is a valid, event-free segment;
    an event for a scenario that was not scored is an error (it would silently vanish from recall)."""
    unknown = sorted(set(events_by_scenario) - set(scores_by_scenario))
    if unknown:
        raise AnomalyEvalError(f"events refer to scenarios without scores: {unknown[:5]}")
    return [
        Segment(sid, scores_by_scenario[sid], tuple(events_by_scenario.get(sid, ())))
        for sid in sorted(scores_by_scenario)
    ]


# --------------------------------------------------------------------------------------- threshold selection
@dataclass(frozen=True)
class ThresholdChoice:
    threshold: float
    fit_split_id: str
    rule: str
    false_alarm_cap_per_day: float
    max_alert_row_fraction: float
    validation_event_recall: float
    validation_false_alarms_per_day: float
    validation_alert_row_fraction: float
    candidates_considered: int

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def select_threshold_segments(
    val_segments: Sequence[Segment],
    cfg: EvalConfig,
    *,
    split_id: str,
    false_alarm_cap_per_day: float,
    max_alert_row_fraction: float,
    max_candidates: int = 2000,
) -> ThresholdChoice:
    """Pre-registered rule: MAXIMISE event recall subject to false-alarm episodes/day <= cap AND the fraction of
    rows that alert <= ``max_alert_row_fraction`` (both required, both from the pre-registration), on validation only.

    Candidates are the distinct finite validation scores pooled over segments (evenly thinned to
    ``max_candidates``). Ties in recall go to the HIGHER threshold (fewer alerts). If no candidate meets both caps,
    ``NoFeasibleThresholdError`` is raised -- the caps are never relaxed here. The function has no parameter
    through which held-out rows could arrive, and it refuses any split id other than "validation".
    """
    if split_id != VALIDATION_SPLIT:
        raise LeakageError(f"thresholds are fitted on the {VALIDATION_SPLIT!r} split only, got {split_id!r}")
    if not (math.isfinite(false_alarm_cap_per_day) and false_alarm_cap_per_day >= 0):
        raise AnomalyEvalError("false_alarm_cap_per_day must be finite and >= 0")
    if not (math.isfinite(max_alert_row_fraction) and 0.0 < max_alert_row_fraction < 1.0):
        raise AnomalyEvalError(
            "max_alert_row_fraction must be in (0, 1): a detector that alerts on every row is not a detector"
        )
    segs = _validate_segments(val_segments)
    n_events = sum(len(evs) for _, _, evs in segs)
    if n_events < cfg.min_events:
        raise InsufficientEventsError(f"{n_events} validation events; at least {cfg.min_events} are required")
    pooled = np.concatenate([sc for _, sc, _ in segs])
    finite = np.unique(pooled[~np.isnan(pooled)])
    if finite.size == 0:
        raise NoFeasibleThresholdError("no finite validation scores")
    if finite.size > max_candidates:
        finite = finite[np.unique(np.linspace(0, finite.size - 1, max_candidates).round().astype(int))]
    total_rows = int(pooled.size)
    days = total_rows * cfg.cadence_s / SECONDS_PER_DAY

    best: Optional[tuple[float, float, float, float]] = None  # (recall, threshold, fp_per_day, alert_fraction)
    for thr in finite[::-1]:  # high -> low, so a tie keeps the higher threshold
        alert_rows = 0
        fp = 0
        hit = 0
        for _, sc, evs in segs:
            alerts = _alerts_for(sc, float(thr))
            alert_rows += int(alerts.sum())
        if alert_rows / total_rows > max_alert_row_fraction:
            continue
        for _, sc, evs in segs:
            rows = np.flatnonzero(_alerts_for(sc, float(thr)))
            detected, _, _, overlap = _event_level(rows, evs, cfg)
            hit += sum(detected)
            fp += sum(1 for o in overlap if not o)
        fp_per_day = fp / days
        if fp_per_day > false_alarm_cap_per_day:
            continue
        recall = hit / n_events
        if best is None or recall > best[0]:
            best = (recall, float(thr), fp_per_day, alert_rows / total_rows)
    if best is None:
        raise NoFeasibleThresholdError(
            f"no threshold keeps false alarms <= {false_alarm_cap_per_day} episodes/day and alert rows <= "
            f"{max_alert_row_fraction:.0%} on validation; the caps are pre-registered and are not relaxed"
        )
    return ThresholdChoice(
        threshold=best[1],
        fit_split_id=VALIDATION_SPLIT,
        rule="max event recall subject to false-alarm cap and alert-row-fraction cap (validation only)",
        false_alarm_cap_per_day=float(false_alarm_cap_per_day),
        max_alert_row_fraction=float(max_alert_row_fraction),
        validation_event_recall=best[0],
        validation_false_alarms_per_day=best[2],
        validation_alert_row_fraction=best[3],
        candidates_considered=int(finite.size),
    )


def select_threshold(
    val_scores: Sequence[float] | np.ndarray,
    val_events: Sequence[Event],
    cfg: EvalConfig,
    *,
    split_id: str,
    false_alarm_cap_per_day: float,
    max_alert_row_fraction: float,
    max_candidates: int = 2000,
) -> ThresholdChoice:
    """``select_threshold_segments`` for a single continuous validation series (one segment)."""
    return select_threshold_segments(
        [Segment("series", np.asarray(val_scores, dtype=float), tuple(val_events))],
        cfg,
        split_id=split_id,
        false_alarm_cap_per_day=false_alarm_cap_per_day,
        max_alert_row_fraction=max_alert_row_fraction,
        max_candidates=max_candidates,
    )


class OneShotEvaluator:
    """Evaluates the test split at most once per run, and only with a threshold fitted on validation."""

    def __init__(self, run_id: str) -> None:
        if not run_id:
            raise AnomalyEvalError("run_id is required")
        self.run_id = run_id
        self._used = False

    def _consume(self, choice: ThresholdChoice) -> None:
        if choice.fit_split_id != VALIDATION_SPLIT:
            raise LeakageError(f"threshold was fitted on {choice.fit_split_id!r}, not {VALIDATION_SPLIT!r}")
        if self._used:
            raise SplitReuseError(f"test split already evaluated in run {self.run_id!r}")
        self._used = True  # consumed even if the evaluation raises: a failed look is still a look

    def evaluate_test_segments(
        self, test_segments: Sequence[Segment], choice: ThresholdChoice, cfg: EvalConfig
    ) -> dict[str, Any]:
        self._consume(choice)
        result = evaluate_segments(test_segments, choice.threshold, cfg, split_id=TEST_SPLIT)
        result["run_id"] = self.run_id
        result["threshold_choice"] = choice.as_dict()
        return result

    def evaluate_test(
        self,
        test_scores: Sequence[float] | np.ndarray,
        test_events: Sequence[Event],
        choice: ThresholdChoice,
        cfg: EvalConfig,
    ) -> dict[str, Any]:
        return self.evaluate_test_segments(
            [Segment("series", np.asarray(test_scores, dtype=float), tuple(test_events))], choice, cfg
        )


# ------------------------------------------------------------------------------------------------ reporting
_QUALIFIERS = ("event ", "event-level ", "row-level ", "row ", "event-level\u00a0")


def find_bare_recall(text: str) -> list[int]:
    """Character offsets of every "recall" not directly qualified as event/event-level/row-level/row recall."""
    bad = []
    for m in re.finditer(r"recall", text, flags=re.IGNORECASE):
        before = text[max(0, m.start() - 12) : m.start()].lower()
        if not any(before.endswith(q) for q in _QUALIFIERS):
            bad.append(m.start())
    return bad


def claim_sentence(result: dict[str, Any]) -> str:
    """The only claim the evidence supports, with its numbers filled in."""
    r = result["event_recall"]
    d = result["detection_delay"]["median_minutes"]
    delay = "n/a" if d is None else f"{d:g} min"
    return (
        "On synthetic injected anomalies of the listed types: "
        f"event recall {r['value']:.3f} [{r['ci95'][0]:.3f}, {r['ci95'][1]:.3f}], "
        f"{result['false_alarm_episodes_per_simulated_day']:.3f} false-alarm episodes per simulated day, "
        f"median detection delay {delay}."
    )


def _fmt_prop(p: dict[str, Any]) -> str:
    if p["value"] is None:
        return f"n/a (0/{p['n']})"
    return f"{p['value']:.3f} [{p['ci95'][0]:.3f}, {p['ci95'][1]:.3f}] ({p['successes']}/{p['n']})"


def render_report(result: dict[str, Any]) -> str:
    """Markdown run report. Raises if the text would contain a bare "recall"."""
    d = result["detection_delay"]
    rl = result["row_level"]
    lines = [
        f"# Anomaly evaluation — split `{result['split_id']}`",
        "",
        "Scope: **synthetic injected anomalies only**; nothing here concerns real faults.",
        "",
        f"* Events: {result['n_events']}; rows: {result['n_rows']} ({result['n_unscored_rows']} not scored); "
        f"simulated days: {result['simulated_days']:.3f}",
        f"* Config: cadence {result['config']['cadence_s']:g} s, K = {result['config']['k_gap']}, "
        f"tolerance {result['config']['tolerance_rows']} rows, threshold {result['threshold']:.6g}",
        "",
        "## Event-level (primary)",
        "",
        f"* Event recall: {_fmt_prop(result['event_recall'])}",
        f"* Event precision: {_fmt_prop(result['event_precision'])}",
        f"* False-alarm episodes per simulated day: {result['false_alarm_episodes_per_simulated_day']:.3f} "
        f"({result['false_positive_episodes']} of {result['alert_episodes']} episodes)",
        "* Detection delay: "
        + (
            "n/a (no event detected)"
            if d["median_minutes"] is None
            else f"median {d['median_minutes']:g} min, IQR [{d['iqr_minutes'][0]:g}, {d['iqr_minutes'][1]:g}] min "
            f"over {d['n_detected']} detected events"
        ),
        "",
        "## Row-level (diagnostic only)",
        "",
        f"* Row-level recall: {_fmt_prop(rl['row_recall'])}",
        f"* Row-level precision: {_fmt_prop(rl['row_precision'])}",
        f"* Row-level F1: {'n/a' if rl['row_f1'] is None else format(rl['row_f1'], '.3f')}",
        "",
        "## Per event type",
        "",
    ]
    for t, v in result["per_type"].items():
        if v["reported"]:
            lines.append(f"* `{t}` ({v['n_events']} events): event recall {_fmt_prop(v['event_recall'])}")
        else:
            lines.append(f"* `{t}` ({v['n_events']} events): not reported — {v['reason']}")
    lines += ["", "## Claim supported by this run", "", claim_sentence(result), ""]
    text = "\n".join(lines)
    bad = find_bare_recall(text)
    if bad:
        raise AnomalyEvalError(f"report text contains a bare 'recall' at offsets {bad[:5]}")
    return text


def canonical_json(result: dict[str, Any]) -> str:
    """Stable encoding for results.json (sorted keys, no NaN)."""
    return json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)


# ======================================================================================================================
# T18: protocol-first held-out evaluation (rolling z-score baseline, bootstrap intervals, event F1, run driver)
# ======================================================================================================================
# Order of events, enforced in code by ``run_final``:
#   1. ``PROTOCOL.md`` is written and its SHA-256 recorded in ``PROTOCOL.sha256.json`` (``lock_protocol``) BEFORE any scoring.
#   2. Every scorer is fitted on the train split and its threshold chosen on VALIDATION only (same rule, same caps).
#   3. ``TEST_SPLIT_USED.json`` is written, THEN the test split is read and each scorer is scored exactly once.
#   4. Intervals (cluster bootstrap over scenarios), the paired comparison and the report are computed from those scores.
# A second run is refused while the marker exists: the one-shot rule survives restarts, not only the process.

FEATURES: tuple[str, ...] = (
    "water_flow_lpm",
    "water_pressure_bar",
    "server_outlet_temp_C",
    "it_power_kw",
    "humidity_pct",
)
BASELINE_WINDOW_ROWS = 24  # 2 hours at 5-minute cadence; fixed by the protocol, never tuned
BOOTSTRAP_REPS = 2000
BOOTSTRAP_SEED = 20261018
BOOTSTRAP_LEVEL = 0.95
PROTOCOL_DIR = Path("reports") / "anomaly_eval"
PROTOCOL_FILE = "PROTOCOL.md"
PROTOCOL_HASH_FILE = "PROTOCOL.sha256.json"
TEST_USED_FILE = "TEST_SPLIT_USED.json"
PREREG_BEGIN, PREREG_END = "<!-- PREREG:BEGIN -->", "<!-- PREREG:END -->"
_SPLIT_FILES = {"train": "train.csv", "validation": "val.csv", "test": "test.csv"}
_EVENT_SPLIT = {"train": "train", "validation": "val", "test": "test"}


class ProtocolError(AnomalyEvalError):
    """The protocol was changed, is unlocked, does not match the config or dataset, or the test split was already used."""


# ----------------------------------------------------------------------------------------- protocol hash and lock
def protocol_sha256(path: str | Path) -> str:
    """SHA-256 of the protocol text with line endings normalised to LF (a Windows checkout must hash the same)."""
    raw = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


def read_prereg_block(path: str | Path) -> dict[str, Any]:
    """The machine-readable JSON between the PREREG markers of the protocol text."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        body = text.split(PREREG_BEGIN, 1)[1].split(PREREG_END, 1)[0]
        return json.loads(body.replace("```json", "").replace("```", ""))
    except (IndexError, ValueError) as exc:
        raise ProtocolError(f"{path}: missing or unreadable PREREG block ({type(exc).__name__})") from None


def lock_protocol(directory: str | Path = PROTOCOL_DIR, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Record the protocol hash. Refuses once the test split has been used (a lock after the fact proves nothing)."""
    directory = Path(directory)
    if (directory / TEST_USED_FILE).exists():
        raise ProtocolError("the test split was already used; the protocol can no longer be (re)locked")
    path = directory / PROTOCOL_FILE
    record = {
        "schema": 1,
        "protocol_file": PROTOCOL_FILE,
        "protocol_sha256": protocol_sha256(path),
        "locked_at_utc": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "test_split_read_before_lock": False,  # enforced: lock_protocol refuses once TEST_SPLIT_USED.json exists
    }
    (directory / PROTOCOL_HASH_FILE).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def verify_protocol(directory: str | Path, cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Raise ``ProtocolError`` unless the recorded hash matches the text AND the text's PREREG block matches ``cfg``."""
    directory = Path(directory)
    lock_path = directory / PROTOCOL_HASH_FILE
    if not lock_path.is_file():
        raise ProtocolError(
            f"{lock_path} is missing: lock the protocol before scoring (python -m src.anomaly_eval lock)"
        )
    record = json.loads(lock_path.read_text(encoding="utf-8"))
    actual = protocol_sha256(directory / PROTOCOL_FILE)
    if record.get("protocol_sha256") != actual:
        raise ProtocolError(
            "PROTOCOL.md changed after it was locked (hash mismatch); results would not be pre-registered"
        )
    block = read_prereg_block(directory / PROTOCOL_FILE)
    for key in (
        "k_gap",
        "tolerance_rows",
        "false_alarm_cap_per_day",
        "max_alert_row_fraction",
        "cadence_s",
        "seq_len",
        "seed",
    ):
        if block.get(key) != cfg.get(key):
            raise ProtocolError(f"config {key}={cfg.get(key)!r} differs from the locked protocol ({block.get(key)!r})")
    if cfg.get("caps_status") != "preregistered":
        raise ProtocolError(
            f"caps_status is {cfg.get('caps_status')!r}; the owner must set it to 'preregistered' first"
        )
    return block


# ------------------------------------------------------------------------------------------------ baseline scorer
def rolling_zscore_scores(values: Any, window: int = BASELINE_WINDOW_ROWS) -> np.ndarray:
    """Per-row score of the simple baseline: the largest feature z-score against the PRECEDING ``window`` rows.

    ``z_j(t) = |x_j(t) - mean_j| / max(std_j, floor_j)`` with mean/std over rows ``t-window .. t-1`` (the current row is
    never part of its own reference, so a spike cannot hide itself); ``floor_j = 1e-3 * max(|mean_j|, 1)`` stops a
    constant feature from producing an infinite score. The first ``window`` rows are NaN (not scored). Nothing is fitted.
    """
    x = np.asarray(values, dtype=float)
    if x.ndim == 1:
        x = x[:, None]
    n = x.shape[0]
    if int(window) != window or window < 2:
        raise AnomalyEvalError("window must be an integer >= 2")
    scores = np.full(n, np.nan)
    if n <= window:
        return scores
    csum = np.vstack([np.zeros((1, x.shape[1])), np.cumsum(x, axis=0)])
    csq = np.vstack([np.zeros((1, x.shape[1])), np.cumsum(x * x, axis=0)])
    idx = np.arange(window, n)
    total = csum[idx] - csum[idx - window]
    total_sq = csq[idx] - csq[idx - window]
    mean = total / window
    var = np.maximum(total_sq / window - mean * mean, 0.0)
    std = np.sqrt(var)
    floor = 1e-3 * np.maximum(np.abs(mean), 1.0)
    z = np.abs(x[idx] - mean) / np.maximum(std, floor)
    scores[idx] = z.max(axis=1)
    return scores


class Scorer(Protocol):
    """What the runner needs from a detector: fit on normal train data, then a per-row score for one scenario."""

    name: str

    def fit(self, train_scenarios: Mapping[str, Any]) -> dict[str, Any]: ...

    def score(self, frame: Any) -> np.ndarray: ...


class RollingZScoreScorer:
    """The pre-registered baseline. ``fit`` learns nothing."""

    name = "rolling_zscore"

    def __init__(self, window: int = BASELINE_WINDOW_ROWS, features: Sequence[str] = FEATURES) -> None:
        self.window, self.features = int(window), tuple(features)

    def fit(self, train_scenarios: Mapping[str, Any]) -> dict[str, Any]:
        return {"fitted": False, "window_rows": self.window}

    def score(self, frame: Any) -> np.ndarray:
        return rolling_zscore_scores(frame[list(self.features)].to_numpy(dtype=float), self.window)


class AutoencoderScorer:
    """Adapter for ``src.anomaly_detector.AnomalyDetector`` (TensorFlow, imported only here and only when used).

    Trains on the NORMAL windows of the train split (windows never cross a scenario boundary); the score of a row is the
    reconstruction error of the window ENDING at it, so the first ``seq_len - 1`` rows are NaN.
    """

    name = "autoencoder"

    def __init__(self, cfg: Mapping[str, Any], features: Sequence[str] = FEATURES) -> None:
        self.cfg, self.features = cfg, tuple(features)
        self.seq_len = int(cfg["seq_len"])
        self.detector: Any = None

    def _windows(self, frame: Any) -> tuple[np.ndarray, np.ndarray]:
        from numpy.lib.stride_tricks import sliding_window_view

        data = frame[list(self.features)].to_numpy(dtype=np.float32)
        if len(data) < self.seq_len:
            return np.empty((0, self.seq_len, len(self.features)), dtype=np.float32), np.empty(0, dtype=bool)
        win = sliding_window_view(data, (self.seq_len, len(self.features)))[:, 0]
        bad = sliding_window_view(frame["anomaly"].to_numpy(), self.seq_len).max(axis=1) > 0
        return np.ascontiguousarray(win), bad

    def fit(self, train_scenarios: Mapping[str, Any]) -> dict[str, Any]:
        from src.anomaly_detector import AnomalyDetector  # TensorFlow lives behind this import

        parts = []
        for frame in train_scenarios.values():
            win, bad = self._windows(frame)
            if len(win):
                parts.append(win[~bad])
        windows = np.concatenate(parts) if parts else np.empty((0,))
        if windows.size == 0:
            raise AnomalyEvalError("no normal training windows")
        train = self.cfg["training"]
        self.detector = AnomalyDetector(seq_len=self.seq_len, feature_columns=list(self.features), verbose=0)
        history = self.detector.train_sequences(
            windows,
            epochs=int(train["epochs"]),
            batch_size=int(train["batch_size"]),
            validation_split=float(train["validation_split"]),
            patience=int(train["patience"]),
            seed=int(self.cfg["seed"]),
        )
        return {
            "n_train_windows": int(len(windows)),
            "epochs_run": len(history.get("loss", [])) if isinstance(history, Mapping) else None,
        }

    def score(self, frame: Any) -> np.ndarray:
        scores = np.full(len(frame), np.nan)
        win, _ = self._windows(frame)
        if len(win):
            scores[self.seq_len - 1 :] = np.asarray(self.detector.score_sequences(win), dtype=float)
        return scores


# ------------------------------------------------------------------------------- event-level F1 and cluster bootstrap
def event_f1(recall: Optional[float], precision: Optional[float]) -> Optional[float]:
    """Harmonic mean of event recall and event precision; None when either is undefined, 0 when both are 0."""
    if recall is None or precision is None:
        return None
    return 0.0 if recall + precision == 0.0 else 2.0 * precision * recall / (precision + recall)


@dataclass(frozen=True)
class _SegStat:
    counts: _Counts
    detected: tuple
    delays: tuple
    types: tuple


def _stats(segments: Sequence[Segment], threshold: float, cfg: EvalConfig) -> list[_SegStat]:
    out = []
    for _, scores, events in _validate_segments(segments):
        counts, detected, delays = _segment_counts(scores, events, threshold, cfg)
        out.append(_SegStat(counts, tuple(detected), tuple(delays), tuple(e.type for e in events)))
    return out


def _metrics(stats: Sequence[_SegStat], cfg: EvalConfig) -> dict[str, Any]:
    """Event-level figures for a set of per-segment tallies. Same definitions as ``evaluate_segments``."""
    rows = sum(s.counts.n_rows for s in stats)
    episodes = sum(s.counts.episodes for s in stats)
    fp = sum(s.counts.fp_episodes for s in stats)
    detected = [d for s in stats for d in s.detected]
    delays = [d for s in stats for d in s.delays if d is not None]
    days = rows * cfg.cadence_s / SECONDS_PER_DAY
    recall = sum(detected) / len(detected) if detected else None
    precision = (episodes - fp) / episodes if episodes else None
    by_type: dict[str, Optional[float]] = {}
    for t in sorted({t for s in stats for t in s.types}):
        flags = [d for s in stats for d, ty in zip(s.detected, s.types) if ty == t]
        by_type[t] = sum(flags) / len(flags) if flags else None
    return {
        "event_recall": recall,
        "event_precision": precision,
        "event_f1": event_f1(recall, precision),
        "false_alarm_episodes_per_day": fp / days if days > 0 else None,
        "median_delay_minutes": float(np.median(delays)) * cfg.cadence_s / 60.0 if delays else None,
        "recall_by_type": by_type,
    }


def _percentile_ci(values: Sequence[Optional[float]], level: float) -> Optional[list[float]]:
    got = np.array([v for v in values if v is not None], dtype=float)
    if got.size < 2:
        return None
    lo, hi = np.percentile(got, [(1 - level) / 2 * 100, (1 + level) / 2 * 100])
    return [float(lo), float(hi)]


def bootstrap_metrics(
    segments: Sequence[Segment],
    threshold: float,
    cfg: EvalConfig,
    *,
    reps: int = BOOTSTRAP_REPS,
    seed: int = BOOTSTRAP_SEED,
    level: float = BOOTSTRAP_LEVEL,
) -> dict[str, Any]:
    """Point estimates plus percentile intervals from a CLUSTER bootstrap: whole scenarios are resampled with
    replacement, because the rows and the two events inside one scenario are not independent. Deterministic in ``seed``.
    A replicate in which a figure is undefined (no episodes, no detection) is skipped for that figure and counted."""
    stats = _stats(segments, threshold, cfg)
    point = _metrics(stats, cfg)
    rng = np.random.default_rng(seed)
    draws = [_metrics([stats[i] for i in rng.integers(0, len(stats), len(stats))], cfg) for _ in range(reps)]
    out: dict[str, Any] = {
        "method": "cluster bootstrap over scenarios (percentile)",
        "reps": reps,
        "seed": seed,
        "level": level,
    }
    for key in ("event_recall", "event_precision", "event_f1", "false_alarm_episodes_per_day", "median_delay_minutes"):
        vals = [d[key] for d in draws]
        out[key] = {
            "value": point[key],
            "ci95": _percentile_ci(vals, level),
            "n_valid_reps": sum(v is not None for v in vals),
        }
    out["recall_by_type"] = {
        t: {
            "value": point["recall_by_type"][t],
            "ci95": _percentile_ci([d["recall_by_type"].get(t) for d in draws], level),
            "n_events": sum(ty == t for s in stats for ty in s.types),
        }
        for t in point["recall_by_type"]
    }
    return out


def paired_bootstrap_difference(
    a: Sequence[Segment],
    threshold_a: float,
    b: Sequence[Segment],
    threshold_b: float,
    cfg: EvalConfig,
    *,
    metric: str = "event_f1",
    reps: int = BOOTSTRAP_REPS,
    seed: int = BOOTSTRAP_SEED,
    level: float = BOOTSTRAP_LEVEL,
) -> dict[str, Any]:
    """``metric(a) - metric(b)`` with an interval from resampling the SAME scenarios for both scorers (paired)."""
    ids_a = [sid for sid, _, _ in _validate_segments(a)]
    ids_b = [sid for sid, _, _ in _validate_segments(b)]
    if ids_a != ids_b:
        raise AnomalyEvalError("both scorers must be evaluated on the same scenarios, in the same order")
    sa, sb = _stats(a, threshold_a, cfg), _stats(b, threshold_b, cfg)
    pa, pb = _metrics(sa, cfg)[metric], _metrics(sb, cfg)[metric]
    rng = np.random.default_rng(seed)
    diffs: list[Optional[float]] = []
    for _ in range(reps):
        idx = rng.integers(0, len(sa), len(sa))
        ma, mb = _metrics([sa[i] for i in idx], cfg)[metric], _metrics([sb[i] for i in idx], cfg)[metric]
        diffs.append(None if ma is None or mb is None else ma - mb)
    ci = _percentile_ci(diffs, level)
    return {
        "metric": metric,
        "a_minus_b": None if pa is None or pb is None else pa - pb,
        "ci95": ci,
        "n_valid_reps": sum(d is not None for d in diffs),
        "a_clearly_better": bool(ci is not None and ci[0] > 0),
        "b_clearly_better": bool(ci is not None and ci[1] < 0),
    }


def conclusion(detector: str, baseline: str, diff: Mapping[str, Any]) -> str:
    """The pre-registered decision rule in words: only an interval that excludes 0 counts as a difference."""
    d = diff["a_minus_b"]
    if d is None or diff["ci95"] is None:
        return f"INSUFFICIENT: the event-level F1 difference between {detector} and {baseline} could not be estimated."
    lo, hi = diff["ci95"]
    span = f"event F1 difference {d:+.3f} (95% CI [{lo:+.3f}, {hi:+.3f}])"
    if diff["a_clearly_better"]:
        return f"{detector} beat {baseline}: {span}. Scope: synthetic injected anomalies only."
    if diff["b_clearly_better"]:
        return f"{baseline} beat {detector}: {span}. The learned detector is WORSE than the simple baseline on this protocol."
    return f"NO DEMONSTRATED ADVANTAGE: {span} includes 0, so {detector} is not shown to beat {baseline}."


# ----------------------------------------------------------------------------------------------- run driver
@dataclass
class Dataset:
    directory: Path
    manifest: dict[str, Any]
    frames: dict[str, Any]
    events: dict[str, dict[str, list[Event]]]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_dataset(directory: str | Path, *, allow_synthetic_inputs: bool = False) -> dict[str, Any]:
    directory = Path(directory)
    mpath = directory / "manifest.json"
    if not mpath.is_file():
        raise ProtocolError(f"{mpath} does not exist (run scripts/make_datasets.py first)")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != directory.name:
        raise ProtocolError("manifest dataset_id does not match the directory name")
    for name, meta in manifest.get("files", {}).items():
        if not (directory / name).is_file() or _sha256_file(directory / name) != meta["sha256"]:
            raise ProtocolError(f"dataset file {name} is missing or does not match its manifest sha256")
    if manifest.get("synthetic_inputs") and not allow_synthetic_inputs:
        raise ProtocolError(
            f"the dataset contains synthetic inputs {manifest['synthetic_inputs']}; pass --allow-synthetic-inputs (recorded)"
        )
    return manifest


def _read_scenarios(directory: Path, split: str, cadence_s: float) -> dict[str, Any]:
    import pandas as pd

    df = pd.read_csv(directory / _SPLIT_FILES[split], dtype={"scenario_id": str, "event_id": str})
    out = {}
    for sid, frame in df.groupby("scenario_id", sort=True):
        frame = frame.reset_index(drop=True)
        steps = pd.to_datetime(frame["timestamp"]).diff().dropna().dt.total_seconds()
        if len(steps):
            if not (steps == steps.iloc[0]).all():
                raise AnomalyEvalError(f"scenario {sid}: timestamps are not a regular series")
            check_cadence(cadence_s, float(steps.iloc[0]))
        out[str(sid)] = frame
    return out


def _events(directory: Path, split: str) -> dict[str, list[Event]]:
    import pandas as pd

    records = pd.read_csv(directory / "events.csv", dtype={"scenario_id": str}).to_dict("records")
    return events_from_records(records, split=_EVENT_SPLIT[split])


def _segments(scorer: Scorer, scenarios: Mapping[str, Any], events: Mapping[str, Sequence[Event]]) -> list[Segment]:
    return segments_from_scores({sid: scorer.score(frame) for sid, frame in scenarios.items()}, events)


def check_dataset_matches_protocol(manifest: Mapping[str, Any], block: Mapping[str, Any]) -> None:
    for key in ("split_id", "scenario_set_id"):
        if manifest.get(key) != block.get(f"dataset_{key}"):
            raise ProtocolError(f"dataset {key} {manifest.get(key)!r} is not the one named in the protocol")


def run_validation(
    scorers: Sequence[Scorer], dataset_dir: str | Path, cfg: Mapping[str, Any], *, allow_synthetic_inputs: bool = False
) -> dict[str, Any]:
    """Fit every scorer and choose its threshold on validation. NEVER reads the test split; safe to run any time."""
    directory = Path(dataset_dir)
    manifest = verify_dataset(directory, allow_synthetic_inputs=allow_synthetic_inputs)
    ecfg = EvalConfig(
        cadence_s=float(cfg["cadence_s"]), k_gap=int(cfg["k_gap"]), tolerance_rows=int(cfg["tolerance_rows"])
    )
    train = _read_scenarios(directory, "train", ecfg.cadence_s)
    val = _read_scenarios(directory, "validation", ecfg.cadence_s)
    val_events = _events(directory, "validation")
    out: dict[str, Any] = {"dataset_id": manifest["dataset_id"], "scorers": {}}
    for scorer in scorers:
        fit = scorer.fit(train)
        segs = _segments(scorer, val, val_events)
        entry: dict[str, Any] = {"fit": fit}
        try:
            choice = select_threshold_segments(
                segs, ecfg, split_id=VALIDATION_SPLIT,
                false_alarm_cap_per_day=float(cfg["false_alarm_cap_per_day"]),
                max_alert_row_fraction=float(cfg["max_alert_row_fraction"]),
            )  # fmt: skip
            entry["threshold_choice"] = choice.as_dict()
            entry["validation"] = evaluate_segments(segs, choice.threshold, ecfg, split_id=VALIDATION_SPLIT)
        except NoFeasibleThresholdError as exc:
            entry["threshold_choice"] = None
            entry["no_feasible_threshold"] = str(exc)
        out["scorers"][scorer.name] = entry
    return out


def run_final(
    scorers: Sequence[Scorer],
    dataset_dir: str | Path,
    cfg: Mapping[str, Any],
    *,
    run_id: str,
    protocol_dir: str | Path = PROTOCOL_DIR,
    out_dir: Optional[str | Path] = None,
    primary: str = "autoencoder",
    baseline: str = "rolling_zscore",
    allow_synthetic_inputs: bool = False,
    reps: int = BOOTSTRAP_REPS,
) -> dict[str, Any]:
    """The one held-out run. Verifies the lock, fits and thresholds on train/validation, marks the test split used, then
    scores it once per scorer. Raises ``ProtocolError`` on any deviation; never relaxes a cap."""
    protocol_dir = Path(protocol_dir)
    block = verify_protocol(protocol_dir, cfg)
    if (protocol_dir / TEST_USED_FILE).exists():
        raise ProtocolError("the test split was already scored (TEST_SPLIT_USED.json exists); it is scored once, ever")
    names = [s.name for s in scorers]
    if primary not in names or baseline not in names:
        raise AnomalyEvalError(f"scorers must include {primary!r} and {baseline!r}, got {names}")
    directory = Path(dataset_dir)
    manifest = verify_dataset(directory, allow_synthetic_inputs=allow_synthetic_inputs)
    check_dataset_matches_protocol(manifest, block)
    ecfg = EvalConfig(
        cadence_s=float(cfg["cadence_s"]), k_gap=int(cfg["k_gap"]), tolerance_rows=int(cfg["tolerance_rows"])
    )

    validation = run_validation(scorers, directory, cfg, allow_synthetic_inputs=allow_synthetic_inputs)
    # The marker is written BEFORE the test split is read: a crash after this point still counts as a look.
    used = {"run_id": run_id, "protocol_sha256": protocol_sha256(protocol_dir / PROTOCOL_FILE), "dataset_id": manifest["dataset_id"],
            "marked_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}  # fmt: skip
    (protocol_dir / TEST_USED_FILE).write_text(json.dumps(used, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    test = _read_scenarios(directory, "test", ecfg.cadence_s)
    test_events = _events(directory, "test")
    results: dict[str, Any] = {}
    test_segments: dict[str, list[Segment]] = {}
    for scorer in scorers:
        entry = validation["scorers"][scorer.name]
        if entry.get("threshold_choice") is None:
            results[scorer.name] = {"scored": False, "reason": entry["no_feasible_threshold"]}
            continue
        choice = ThresholdChoice(**entry["threshold_choice"])
        segs = _segments(scorer, test, test_events)
        res = OneShotEvaluator(f"{run_id}:{scorer.name}").evaluate_test_segments(segs, choice, ecfg)
        res["bootstrap"] = bootstrap_metrics(segs, choice.threshold, ecfg, reps=reps)
        res["event_f1"] = res["bootstrap"]["event_f1"]
        results[scorer.name] = {"scored": True, **res}
        test_segments[scorer.name] = segs

    if primary in test_segments and baseline in test_segments:
        diff = paired_bootstrap_difference(
            test_segments[primary],
            results[primary]["threshold"],
            test_segments[baseline],
            results[baseline]["threshold"],
            ecfg,
            reps=reps,
        )
        verdict = conclusion(primary, baseline, diff)
    else:
        diff = None
        verdict = (
            "INSUFFICIENT: at least one scorer had no feasible threshold on validation under the pre-registered caps."
        )
    report = {
        "run_id": run_id,
        "scope": "synthetic injected anomalies only",
        "dataset_id": manifest["dataset_id"],
        "synthetic_inputs": manifest.get("synthetic_inputs", []),
        "protocol_sha256": used["protocol_sha256"],
        "config": ecfg.as_dict(),
        "validation": validation,
        "test": results,
        "comparison": {"primary": primary, "baseline": baseline, "difference": diff, "conclusion": verdict},
    }
    if out_dir is not None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(canonical_json(report) + "\n", encoding="utf-8")
        (out / "REPORT.md").write_text(render_comparison(report), encoding="utf-8")
    return report


def _fmt_ci(entry: Mapping[str, Any], digits: int = 3) -> str:
    v, ci = entry["value"], entry["ci95"]
    if v is None:
        return "n/a"
    span = "CI n/a" if ci is None else f"95% CI [{ci[0]:.{digits}f}, {ci[1]:.{digits}f}]"
    return f"{v:.{digits}f} ({span})"


def render_comparison(report: Mapping[str, Any]) -> str:
    lines = [
        f"# Held-out anomaly evaluation, run `{report['run_id']}`",
        "",
        "Scope: **synthetic injected anomalies only** (two fixed fault types). Nothing here concerns real faults.",
        f"Protocol sha256 `{report['protocol_sha256']}`; dataset `{report['dataset_id']}`.",
    ]
    if report["synthetic_inputs"]:
        lines.append(f"**Synthetic inputs were substituted:** {', '.join(map(str, report['synthetic_inputs']))}.")
    lines += ["", "## Conclusion", "", report["comparison"]["conclusion"], ""]
    for name, res in report["test"].items():
        lines += [f"## `{name}`", ""]
        if not res["scored"]:
            lines += [f"Not scored on test: {res['reason']}", ""]
            continue
        b = res["bootstrap"]
        d = res["detection_delay"]
        lines += [
            f"* Threshold {res['threshold']:.6g}, chosen on validation only.",
            f"* Event recall: {_fmt_ci(b['event_recall'])}",
            f"* Event precision: {_fmt_ci(b['event_precision'])}",
            f"* Event F1: {_fmt_ci(b['event_f1'])}",
            f"* False-alarm episodes per simulated day: {_fmt_ci(b['false_alarm_episodes_per_day'])}",
            "* Detection delay: "
            + (
                "n/a"
                if d["median_minutes"] is None
                else f"median {d['median_minutes']:g} min, IQR [{d['iqr_minutes'][0]:g}, {d['iqr_minutes'][1]:g}] min over {d['n_detected']} detected events"
            ),
        ]
        for t, v in b["recall_by_type"].items():
            lines.append(f"* `{t}` ({v['n_events']} events): event recall {_fmt_ci(v)}")
        lines.append("")
    diff = report["comparison"]["difference"]
    if diff is not None and diff["ci95"] is not None:
        lines += [
            "## Paired difference",
            "",
            f"Event F1, {report['comparison']['primary']} minus {report['comparison']['baseline']}: "
            f"{diff['a_minus_b']:+.3f} (95% CI [{diff['ci95'][0]:+.3f}, {diff['ci95'][1]:+.3f}], {diff['n_valid_reps']} valid replicates).",
            "",
        ]
    text = "\n".join(lines)
    bad = find_bare_recall(text)
    if bad:
        raise AnomalyEvalError(f"report text contains a bare 'recall' at offsets {bad[:5]}")
    return text


# ----------------------------------------------------------------------------------------------------- command line
def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m src.anomaly_eval", description="T18 held-out anomaly evaluation")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("lock", help="record the SHA-256 of PROTOCOL.md (before any scoring)")
    for name in ("validate", "final"):
        p = sub.add_parser(name, help="validate: thresholds on validation only; final: the one test run")
        p.add_argument("--dataset-dir", type=Path, required=True)
        p.add_argument("--config", type=Path, default=Path("configs/anomaly/anomaly_v2.json"))
        p.add_argument("--allow-synthetic-inputs", action="store_true")
        p.add_argument("--no-detector", action="store_true", help="baseline only (validate stage only)")
    sub.choices["final"].add_argument("--run-id", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "lock":
        print(json.dumps(lock_protocol(), indent=2))
        return 0
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    scorers: list[Scorer] = [RollingZScoreScorer()]
    if args.cmd == "final" or not args.no_detector:
        scorers.append(AutoencoderScorer(cfg))  # needs TensorFlow when fitted
    if args.cmd == "validate":
        print(
            canonical_json(
                run_validation(scorers, args.dataset_dir, cfg, allow_synthetic_inputs=args.allow_synthetic_inputs)
            )
        )
        return 0
    report = run_final(
        scorers, args.dataset_dir, cfg, run_id=args.run_id, out_dir=PROTOCOL_DIR / "runs" / args.run_id,
        allow_synthetic_inputs=args.allow_synthetic_inputs,
    )  # fmt: skip
    print(report["comparison"]["conclusion"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
