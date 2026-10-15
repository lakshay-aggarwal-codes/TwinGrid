import { useMemo } from "react";
import { fetchAlerts, type AlertRecord } from "@/api/apiClient";
import { alertsQueryKey } from "@/api/alerts";
import { useSharedSimulation } from "@/hooks/simulationContext";
import { useWhatIf, type WhatIfResult } from "@/hooks/useWhatIf";
import { useApiQuery } from "@/state/useApiQuery";
import type { DataState } from "@/state/dataState";
import { useFeed } from "@/telemetry/useFeed";
import { useEvaluation, useEvaluationList } from "@/evaluation/useEvaluations";
import { newestEvaluationId, savingsFacts, type SavingsFacts } from "./kpis";

/** Same page size as the Incidents panel and the facility inspector, so all three share one cached query. */
export const ALERTS_LIMIT = 50;

/** The 24 h model run for the sidebar inputs: the same query key as the Analytics What-If tab, so no extra request. */
export function useModelRun(): WhatIfResult {
  const { config } = useSharedSimulation();
  return useWhatIf(config, { enabled: true }).result;
}

export function useFeedLive(): boolean {
  return useFeed((v) => v.freshness.state === "live");
}

export interface SavingsResult {
  readonly state: "loading" | "ready" | "none" | "error";
  readonly facts: SavingsFacts | null;
  readonly reason: string | undefined;
}

/** Newest backend policy-evaluation report -> baseline-controller comparison. Read-only; nothing is computed beyond one subtraction. */
export function useSavings(): SavingsResult {
  const list = useEvaluationList();
  const id = list.state.status === "ready" ? newestEvaluationId(list.state.data.evaluations) : null;
  const detail = useEvaluation(id);
  return useMemo<SavingsResult>(() => {
    if (list.state.status === "loading" || (id !== null && detail.state.status === "loading")) return { state: "loading", facts: null, reason: undefined };
    if (list.state.status === "not_run" || list.state.status === "empty") return { state: "none", facts: null, reason: "No policy-evaluation report has been run." };
    if (list.state.status === "unauthorized") return { state: "error", facts: null, reason: "Policy-evaluation reports are not available to this session." };
    if (list.state.status === "error") return { state: "error", facts: null, reason: "Policy-evaluation reports could not be loaded." };
    if (detail.state.status === "ready") {
      const facts = savingsFacts(detail.state.data);
      return facts ? { state: "ready", facts, reason: undefined } : { state: "none", facts: null, reason: "The newest report has no baseline controller with a second policy to compare." };
    }
    return { state: "error", facts: null, reason: "The newest policy-evaluation report could not be loaded." };
  }, [list.state, detail.state, id]);
}

/** Unacknowledged alerts among the last 50 recorded, or null when alerts are unavailable. */
export function useOpenAlerts(): { open: number; listed: number } | null {
  const { state } = useApiQuery<AlertRecord[]>({
    queryKey: alertsQueryKey(ALERTS_LIMIT),
    queryFn: ({ signal }) => fetchAlerts(ALERTS_LIMIT, signal),
    staleTime: 15_000,
    refetchOnWindowFocus: false,
  });
  const alerts: DataState<AlertRecord[]> = state;
  return alerts.status === "ready" ? { open: alerts.data.filter((a) => !a.acknowledged).length, listed: alerts.data.length } : null;
}
