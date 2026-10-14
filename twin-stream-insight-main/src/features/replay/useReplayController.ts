import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { fetchAlerts } from "@/api/apiClient";
import type { AlertRecord } from "@/api/models";
import type { DataState } from "@/state/dataState";
import { useApiQuery } from "@/state/useApiQuery";
import { useFacilityId } from "@/telemetry/history/useTelemetryHistory";
import { prefersReducedMotion } from "@/three/motion";
import { compareSnapshots, hasAnyData, snapshotAt, type DeltaRow, type Snapshot } from "./dataset";
import { loadReplay, type LoadedReplay } from "./loader";
import { initialState, isReplaying, replayReducer, windowFor, type ReplayState } from "./model";
import { ALERT_FETCH_LIMIT, alertPins, pinsMayBeIncomplete } from "./pins";
import { formatInstantParam, parseReplayUrl, withReplayParams } from "./url";
import type { ReplayAlerts, ReplayContextValue } from "./ReplayContext";

/** Data history is fetched when the window changes or on an explicit refresh (the telemetry API allows 60 requests/minute), never on a timer. */
const STALE_MS = 30_000;
/** Playback tick: 4 per second (1 per second under reduced motion). Cursor state only; the 3D scene is not re-rendered per tick. */
const TICK_MS = 250;
const TICK_REDUCED_MS = 1000;
const URL_DEBOUNCE_MS = 300;

function startState(search: string, nowMs: number): { state: ReplayState; hours: number } {
  const url = parseReplayUrl(search);
  let state = initialState(windowFor(url.tMs, url.hours, nowMs));
  if (url.tMs !== null) state = replayReducer(state, { type: "scrub", ms: url.tMs });
  if (url.tMs !== null && url.bMs !== null) {
    state = replayReducer(state, { type: "compare", on: true });
    state = replayReducer(state, { type: "setB", ms: url.bMs });
  }
  return { state, hours: url.hours };
}

/** Owns everything the replay page shows. Mounted once, by `ReplayProvider`. */
export function useReplayController(): ReplayContextValue {
  const location = useLocation();
  const navigate = useNavigate();
  const start = useRef<{ state: ReplayState; hours: number } | null>(null);
  if (start.current === null) start.current = startState(location.search, Date.now());

  const [state, dispatch] = useReducer(replayReducer, start.current.state);
  const [hours, setHoursState] = useState(start.current.hours);

  // ---- stored history (all five measurands, paged with next_cursor inside loadReplay)
  const facility = useFacilityId();
  const facilityId = facility.state.status === "ready" ? facility.state.data : null;
  const fromIso = formatInstantParam(state.fromMs);
  const toIso = formatInstantParam(state.toMs);
  const load = useApiQuery<LoadedReplay>({
    queryKey: ["replay-history", facilityId, fromIso, toIso],
    queryFn: ({ signal }) => loadReplay(facilityId as number, { from: fromIso, to: toIso }, signal),
    enabled: facilityId !== null,
    staleTime: STALE_MS,
    refetchOnWindowFocus: false,
    refetchInterval: false,
    isEmpty: (d) => !hasAnyData(d.dataset),
  });
  // One state for the page: the facility lookup (loading / error with retry) until it is ready, then the history load.
  const facilityReady = facility.state.status === "ready";
  const loadView = {
    // A non-ready DataState carries no data, so re-typing it as the load's state is safe.
    state: facilityReady ? load.state : (facility.state as unknown as DataState<LoadedReplay>),
    refetch: facilityReady ? load.refetch : facility.refetch,
  };

  // ---- alert pins
  const alertsQuery = useApiQuery<AlertRecord[]>({
    queryKey: ["replay-alerts", ALERT_FETCH_LIMIT],
    queryFn: ({ signal }) => fetchAlerts(ALERT_FETCH_LIMIT, signal),
    staleTime: STALE_MS,
    refetchOnWindowFocus: false,
  });
  const alerts = useMemo<ReplayAlerts>(() => {
    const s = alertsQuery.state;
    if (s.status === "loading") return { status: "loading", pins: [], skipped: 0, mayBeIncomplete: false };
    if (s.status !== "ready" && s.status !== "empty") return { status: "error", pins: [], skipped: 0, mayBeIncomplete: false };
    const rows = s.status === "ready" ? s.data : [];
    const { pins, skipped, oldestMs } = alertPins(rows, state.fromMs, state.toMs);
    return { status: "ready", pins, skipped, mayBeIncomplete: pinsMayBeIncomplete(rows.length, oldestMs, state.fromMs) };
  }, [alertsQuery.state, state.fromMs, state.toMs]);

  // ---- values at the cursor (A) and at compare time B
  const dataset = loadView.state.status === "ready" ? loadView.state.data.dataset : null;
  const snapshot = useMemo<Snapshot | null>(() => (dataset && state.cursorMs !== null ? snapshotAt(dataset, state.cursorMs) : null), [dataset, state.cursorMs]);
  const snapshotB = useMemo<Snapshot | null>(() => (dataset && state.compareOn && state.compareBMs !== null ? snapshotAt(dataset, state.compareBMs) : null), [dataset, state.compareOn, state.compareBMs]);
  const deltas = useMemo<readonly DeltaRow[] | null>(() => (dataset && snapshot && snapshotB ? compareSnapshots(dataset, snapshot, snapshotB) : null), [dataset, snapshot, snapshotB]);

  // ---- playback
  useEffect(() => {
    if (state.mode !== "playing") return;
    let last = performance.now();
    const id = setInterval(() => {
      const now = performance.now();
      dispatch({ type: "tick", wallDeltaMs: now - last });
      last = now;
    }, prefersReducedMotion() ? TICK_REDUCED_MS : TICK_MS);
    return () => clearInterval(id);
  }, [state.mode]);

  // ---- URL: `?t=` follows the cursor (debounced; not while playing). Live removes it. Other parameters are kept.
  const search = useRef(location.search);
  search.current = location.search;
  useEffect(() => {
    if (state.mode === "playing") return;
    const id = setTimeout(() => {
      const next = withReplayParams(search.current, { tMs: state.mode === "live" ? null : state.cursorMs, bMs: state.mode !== "live" && state.compareOn ? state.compareBMs : null, hours });
      if (next !== search.current) navigate({ search: next }, { replace: true });
    }, URL_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [state.mode, state.cursorMs, state.compareOn, state.compareBMs, hours, navigate]);

  const setHours = useCallback(
    (h: number) => {
      setHoursState(h);
      dispatch({ type: "window", ...windowFor(state.cursorMs, h, Date.now()) });
    },
    [state.cursorMs],
  );
  const refreshWindow = useCallback(() => dispatch({ type: "window", ...windowFor(state.cursorMs, hours, Date.now()) }), [state.cursorMs, hours]);
  const shareUrl = useCallback(() => {
    const q = withReplayParams("", { tMs: isReplaying(state) ? state.cursorMs : null, bMs: state.compareOn ? state.compareBMs : null, hours });
    return `${window.location.origin}${window.location.pathname}${q}`;
  }, [state, hours]);

  return { state, dispatch, hours, setHours, load: loadView, alerts, snapshot, snapshotB, deltas, refreshWindow, shareUrl };
}
