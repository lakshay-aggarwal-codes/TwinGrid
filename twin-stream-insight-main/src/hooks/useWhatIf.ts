import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchWhatIf, type WhatIfParams, type WhatIfResponse } from '@/api/apiClient';
import { ApiError, type ApiErrorKind } from '@/api/apiError';
import { AuthRequiredError } from '@/authClient';
import { coolingModeToApi, type SimConfig } from '@/hooks/useSimulation';

/** One stable freshness decision for a constant-input preview: the same inputs are not refetched for a minute. */
export const WHATIF_STALE_MS = 60_000;

export type WhatIfFailure =
  | { status: 'unauthorized'; reason: 'session_ended' | 'forbidden' }
  | { status: 'error'; kind: ApiErrorKind; code?: string };

/**
 * Same shape family as the FE-03 `DataState`: `loading | error{kind} | unauthorized{reason} | ready{data}`.
 * `ready` carries the last good result when a refetch failed (`refreshFailed`) or while new inputs load (`updating`).
 */
export type WhatIfResult =
  | { status: 'loading' }
  | WhatIfFailure
  | { status: 'ready'; data: WhatIfResponse; params: WhatIfParams; refreshFailed?: boolean; updating?: boolean };

export function whatIfParams(cfg: Pick<SimConfig, 'serverUtil' | 'outsideTemp' | 'waterStress' | 'coolingMode' | 'chilledWaterSetpoint'>): WhatIfParams {
  return {
    utilisation: cfg.serverUtil / 100,
    outside_temp: cfg.outsideTemp,
    water_stress: cfg.waterStress,
    mode: coolingModeToApi(cfg.coolingMode),
    chilled_water_temp: cfg.chilledWaterSetpoint,
  };
}

/** A failure as a state. Only the kind (and machine code) is kept; never the error's text. */
export function whatIfFailure(error: unknown): WhatIfFailure {
  if (error instanceof AuthRequiredError) return { status: 'unauthorized', reason: 'session_ended' };
  if (error instanceof ApiError) {
    if (error.kind === 'unauthenticated') return { status: 'unauthorized', reason: 'session_ended' };
    if (error.kind === 'forbidden') return { status: 'unauthorized', reason: 'forbidden' };
    return { status: 'error', kind: error.kind, ...(error.code !== undefined && { code: error.code }) };
  }
  return { status: 'error', kind: 'server' };
}

const RETRYABLE: ReadonlySet<ApiErrorKind> = new Set<ApiErrorKind>(['network', 'unavailable', 'server']);
function retryPolicy(failureCount: number, error: unknown): boolean {
  return error instanceof ApiError && RETRYABLE.has(error.kind) && failureCount < 2;
}

function useDebounced<T>(value: T, ms: number): T {
  const key = JSON.stringify(value);
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    if (ms <= 0) {
      setDebounced(value);
      return;
    }
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
    // `key` stands for the value's content; the object identity changes on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ms]);
  return debounced;
}

export interface UseWhatIfOptions {
  /** False => no request at all (a closed panel must never fetch). */
  enabled: boolean;
  debounceMs?: number;
}

export interface UseWhatIf {
  result: WhatIfResult;
  /** The inputs of the request now in flight / last settled (after debounce). */
  params: WhatIfParams;
  isFetching: boolean;
}

/**
 * Real scenario result for one configuration: GET /api/whatif (an isolated 24 h backend run at constant inputs;
 * a preview). Nothing is computed locally.
 *  - keyed query `['whatif', params]`; `enabled` gates every request;
 *  - changing the inputs makes React Query abort the previous request through the signal it passes to the fetcher,
 *    so a slow older response cannot overwrite a newer one;
 *  - on error the last good result stays visible, labelled `refreshFailed`, never silently.
 */
export function useWhatIf(cfg: SimConfig, { enabled, debounceMs = 400 }: UseWhatIfOptions): UseWhatIf {
  const { serverUtil, outsideTemp, waterStress, coolingMode, chilledWaterSetpoint } = cfg;
  const live = useMemo(
    () => whatIfParams({ serverUtil, outsideTemp, waterStress, coolingMode, chilledWaterSetpoint }),
    [serverUtil, outsideTemp, waterStress, coolingMode, chilledWaterSetpoint]
  );
  const params = useDebounced(live, debounceMs);

  const query = useQuery({
    queryKey: ['whatif', params],
    queryFn: ({ signal }) => fetchWhatIf(params, signal),
    enabled,
    staleTime: WHATIF_STALE_MS,
    retry: retryPolicy,
    refetchOnWindowFocus: false,
  });

  const lastGood = useRef<{ data: WhatIfResponse; params: WhatIfParams } | null>(null);
  useEffect(() => {
    if (query.data !== undefined) lastGood.current = { data: query.data, params };
  }, [query.data, params]);

  let result: WhatIfResult;
  if (query.data !== undefined) {
    result = { status: 'ready', data: query.data, params, ...(query.isError && { refreshFailed: true }) };
  } else if (query.isError) {
    const failure = whatIfFailure(query.error);
    const last = lastGood.current;
    result = failure.status === 'error' && last ? { status: 'ready', data: last.data, params: last.params, refreshFailed: true } : failure;
  } else if (lastGood.current) {
    result = { status: 'ready', data: lastGood.current.data, params: lastGood.current.params, updating: true };
  } else {
    result = { status: 'loading' };
  }
  return { result, params, isFetching: query.isFetching };
}

// ------------------------------------------------------------------ presentation helpers (no maths)

export interface WhatIfMetric {
  key: string;
  label: string;
  format: (v: number) => string;
  pick: (d: WhatIfResponse) => number;
  /** The value depends on the carbon-intensity input; flagged when the backend says it is a fallback. */
  carbon?: boolean;
}

export const WHATIF_METRICS: readonly WhatIfMetric[] = [
  { key: 'pue', label: 'PUE (24 h mean)', format: (v) => v.toFixed(2), pick: (d) => d.mean_pue },
  { key: 'wue', label: 'WUE (L/kWh)', format: (v) => v.toFixed(3), pick: (d) => d.wue },
  { key: 'water', label: 'Water (L/day)', format: (v) => Math.round(v).toLocaleString(), pick: (d) => d.total_water_L },
  { key: 'energy', label: 'Energy (kWh/day)', format: (v) => Math.round(v).toLocaleString(), pick: (d) => d.total_energy_kwh },
  { key: 'co2', label: 'CO₂ (kg/day)', format: (v) => Math.round(v).toLocaleString(), pick: (d) => d.total_co2_kg, carbon: true },
  { key: 'outlet', label: 'Peak outlet temp (°C)', format: (v) => v.toFixed(1), pick: (d) => d.max_outlet_temp_C },
];

/** The backend's `physics_version`, when it sends one (BC-02, not in payloads today). */
export function physicsVersionOf(d: WhatIfResponse): string | null {
  return 'physics_version' in d && typeof d.physics_version === 'string' && d.physics_version !== '' ? d.physics_version : null;
}

export interface InputsEcho {
  utilisation: number;
  outside_temp_C: number;
  water_stress: number;
  mode: string;
  chilled_water_temp_C: number;
}

/** The inputs this result was produced from: the backend's own echo when present, else the request we sent. */
export function inputsOf(data: WhatIfResponse, params: WhatIfParams): InputsEcho {
  if (data.inputs) return data.inputs;
  return {
    utilisation: params.utilisation,
    outside_temp_C: params.outside_temp,
    water_stress: params.water_stress,
    mode: params.mode,
    chilled_water_temp_C: params.chilled_water_temp,
  };
}

export function describeInputs(i: InputsEcho): string {
  return `utilisation ${i.utilisation}, outside ${i.outside_temp_C} °C, water stress ${i.water_stress}, mode ${i.mode}, chilled water ${i.chilled_water_temp_C} °C`;
}
