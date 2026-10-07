/**
 * FE-14: the active topology (backend-sourced, or the built-in fallback) as a tiny external store, so that the 3D scene, the
 * command palette, the inspector and the (non-React) keyboard-navigation helpers all read the SAME layout.
 *
 * `useFacilityTopology()` is the fetch driver (mounted once, by TwinScene). Everything else reads with `useTopology()` / `getTopology()`.
 * Rollback: `VITE_TOPOLOGY_SOURCE=static` skips the fetch and uses the built-in layout (still flagged as not backend-sourced).
 */
import { useEffect, useMemo, useSyncExternalStore } from 'react';
import { fetchFacilityTopology } from '@/api/facility';
import { useApiQuery } from '@/state/useApiQuery';
import { buildFacilityModel, type TopologyRejection, type UnplacedAsset } from './facilityModel';
import { FALLBACK_LAYOUT, type FacilityLayout } from './facilityLayout';

export type FallbackReason = 'configured_static' | 'unavailable' | 'not_found' | TopologyRejection;

export type Topology =
  | { readonly status: 'loading'; readonly source: 'fallback'; readonly layout: FacilityLayout; readonly reason: null; readonly frameUnit: null; readonly frameNote: null; readonly unplaced: readonly UnplacedAsset[] }
  | { readonly status: 'ready'; readonly source: 'backend'; readonly layout: FacilityLayout; readonly reason: null; readonly frameUnit: string; readonly frameNote: string; readonly unplaced: readonly UnplacedAsset[] }
  | { readonly status: 'fallback'; readonly source: 'fallback'; readonly layout: FacilityLayout; readonly reason: FallbackReason; readonly frameUnit: null; readonly frameNote: null; readonly unplaced: readonly UnplacedAsset[] };

export const LOADING_TOPOLOGY: Topology = { status: 'loading', source: 'fallback', layout: FALLBACK_LAYOUT, reason: null, frameUnit: null, frameNote: null, unplaced: [] };

export function fallbackTopology(reason: FallbackReason): Topology {
  return { status: 'fallback', source: 'fallback', layout: FALLBACK_LAYOUT, reason, frameUnit: null, frameNote: null, unplaced: [] };
}

let current: Topology = LOADING_TOPOLOGY;
const listeners = new Set<() => void>();

export function getTopology(): Topology {
  return current;
}

export function setTopology(next: Topology): void {
  if (next === current) return;
  current = next;
  listeners.forEach((l) => l());
}

/** Test helper. */
export function resetTopology(): void {
  setTopology(LOADING_TOPOLOGY);
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function useTopology(): Topology {
  return useSyncExternalStore(subscribe, getTopology, getTopology);
}

export function topologySourceIsStatic(): boolean {
  return String(import.meta.env.VITE_TOPOLOGY_SOURCE ?? '').trim().toLowerCase() === 'static';
}

/** Persistent badge wording. */
export const FALLBACK_BADGE = 'Topology: built-in fallback (not backend-sourced)';
export const LOADING_BADGE = 'Topology: loading…';

export const FALLBACK_REASON_TEXT: Record<FallbackReason, string> = {
  configured_static: 'selected by configuration (VITE_TOPOLOGY_SOURCE=static)',
  unavailable: 'the topology could not be loaded',
  not_found: 'the backend has no facility topology',
  empty: 'the backend topology has no placed racks',
  count_mismatch: 'the backend rack count differs from the expected layout',
  unsupported_frame_unit: 'the backend coordinate unit is not supported by this client',
  invalid: 'the backend topology was not usable',
};

type QueryState = ReturnType<typeof useApiQuery<Awaited<ReturnType<typeof fetchFacilityTopology>>>>['state'];

/** Pure: query state -> topology. */
export function topologyFromQuery(state: QueryState, staticMode: boolean): Topology {
  if (staticMode) return fallbackTopology('configured_static');
  switch (state.status) {
    case 'loading':
      return LOADING_TOPOLOGY;
    case 'error':
      return fallbackTopology(state.kind === 'not_found' ? 'not_found' : state.kind === 'contract' ? 'invalid' : 'unavailable');
    case 'ready': {
      const built = buildFacilityModel(state.data);
      if (built.ok === false) return fallbackTopology(built.reason);
      const { zones, racks, frameUnit, frameNote, unplaced } = built.model;
      return { status: 'ready', source: 'backend', layout: { zones, racks }, reason: null, frameUnit, frameNote, unplaced };
    }
    default:
      return fallbackTopology(state.status === 'empty' ? 'empty' : 'unavailable');
  }
}

/** Fetch driver. Mount ONCE (TwinScene). Backend errors never leave the scene empty: the built-in layout takes over, flagged. */
export function useFacilityTopology(): Topology {
  const staticMode = topologySourceIsStatic();
  const { state } = useApiQuery({
    queryKey: ['facility-topology'],
    queryFn: ({ signal }) => fetchFacilityTopology(signal),
    enabled: !staticMode,
    staleTime: 5 * 60_000,
  });
  const next = useMemo(() => topologyFromQuery(state, staticMode), [state, staticMode]);
  useEffect(() => {
    setTopology(next);
  }, [next]);
  return next;
}
