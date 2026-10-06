"""Anomaly evaluation per roadmap 13.4 (T26) -- the ONLY place anomaly metrics are computed.

Pure NumPy, no TensorFlow/scikit-learn, no I/O. Everything here is deterministic.

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
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

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
