import { createContext, useContext } from "react";
import type { DataState } from "@/state/dataState";
import type { DeltaRow, Snapshot } from "./dataset";
import type { LoadedReplay } from "./loader";
import type { ReplayAction, ReplayState } from "./model";
import type { AlertPin } from "./pins";

export interface ReplayAlerts {
  readonly status: "loading" | "ready" | "error";
  readonly pins: readonly AlertPin[];
  /** Alerts the backend returned with no readable time. */
  readonly skipped: number;
  /** The 200-alert fetch may not reach back to the window start: an empty stretch is not proof of "no alerts". */
  readonly mayBeIncomplete: boolean;
}

/**
 * Task 14: the replay context. While `isReplaying(state)`, every chart and the 3D view of the replay page read from
 * `snapshot` (stored samples at the cursor) and NOT from the live feed. The live feed is read only when `mode === "live"`.
 */
export interface ReplayContextValue {
  readonly state: ReplayState;
  readonly dispatch: (a: ReplayAction) => void;
  readonly hours: number;
  readonly setHours: (h: number) => void;
  readonly load: { readonly state: DataState<LoadedReplay>; readonly refetch: () => void };
  readonly alerts: ReplayAlerts;
  /** Stored values at the cursor (A). null while live or while nothing is loaded. */
  readonly snapshot: Snapshot | null;
  /** Stored values at compare time B. */
  readonly snapshotB: Snapshot | null;
  readonly deltas: readonly DeltaRow[] | null;
  readonly refreshWindow: () => void;
  /** Absolute URL that reopens this exact replay (`?t=`, `?tb=`, `?w=`). */
  readonly shareUrl: () => string;
}

export const ReplayContext = createContext<ReplayContextValue | null>(null);

export function useReplay(): ReplayContextValue {
  const ctx = useContext(ReplayContext);
  if (!ctx) throw new Error("useReplay must be used inside <ReplayProvider>");
  return ctx;
}
