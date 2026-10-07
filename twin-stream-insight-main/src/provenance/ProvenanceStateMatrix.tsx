import { ProvenanceStrip } from './ProvenanceStrip';
import { buildProvenance, type ProvenanceInput } from './model';
import type { Freshness } from '@/telemetry/freshness';

/**
 * FE-05 evidence artifact: the state matrix used for the light/dark/reduced-motion screenshots.
 * Every row is built through `buildProvenance` from a fixed, clearly synthetic INPUT FIXTURE (these are labels for
 * screenshots, not data); it is not mounted by the app. Feature screens must never import it.
 */
const fresh = (state: Freshness['state'], ageMs: number | null): Freshness => ({ state, ageMs, staleAfterMs: 9000, lastReceivedAt: null });

const BASE: ProvenanceInput = {
  source: { kind: 'live-feed' },
  serverTime: '2026-10-06T14:03:21Z',
  simTime: '2026-01-01T12:35:00',
};

const ROWS: ReadonlyArray<readonly [string, ProvenanceInput]> = [
  ['Simulated · live', { ...BASE, origin: 'simulated', freshness: fresh('live', 800) }],
  ['Measured (backend origin=measured)', { ...BASE, origin: 'measured', freshness: fresh('live', 800) }],
  ['Replayed', { ...BASE, origin: 'replayed', freshness: fresh('live', 800) }],
  ['Unverified (origin absent)', { ...BASE, freshness: fresh('live', 800) }],
  ['Unverified (unrecognised origin)', { ...BASE, origin: 'telemetry', freshness: fresh('live', 800) }],
  ['Stale', { ...BASE, origin: 'simulated', freshness: fresh('stale', 42_000) }],
  ['Disconnected', { ...BASE, origin: 'simulated', freshness: fresh('disconnected', 120_000) }],
  ['Reconnecting', { ...BASE, origin: 'simulated', freshness: fresh('reconnecting', 15_000), reconnectAttempt: 3 }],
  ['Connecting', { ...BASE, origin: 'simulated', freshness: fresh('connecting', null) }],
  ['Unavailable (health)', { ...BASE, origin: 'simulated', freshness: fresh('unavailable', 60_000) }],
  ['Unavailable (model)', { source: { kind: 'run-result' }, origin: 'simulated', unavailableReason: 'model_unavailable' }],
  ['Preview', { source: { kind: 'preview' }, origin: 'simulated', weatherSource: 'reference', plantKind: 'simulated', physicsVersion: '1.0' }],
  ['Run result · simulator-only', { source: { kind: 'run-result' }, origin: 'simulated', scenarioId: 'scn-1', runId: 'run-1', weatherSource: 'reference', plantKind: 'simulated' }],
  ['Quality suspect', { ...BASE, origin: 'simulated', quality: 'suspect', freshness: fresh('live', 500) }],
  ['Quality invalid', { ...BASE, origin: 'simulated', quality: 'invalid', freshness: fresh('live', 500) }],
  ['Uncalibrated', { ...BASE, origin: 'simulated', calibration: 'uncalibrated', freshness: fresh('live', 500) }],
  ['Fallback carbon', { ...BASE, origin: 'simulated', inputsFallback: ['carbon'], freshness: fresh('live', 500) }],
];

export function ProvenanceStateMatrix() {
  return (
    <div className="space-y-3 p-4" data-provenance-matrix>
      {ROWS.map(([title, input]) => (
        <div key={title} className="space-y-1 rounded-md border p-2">
          <div className="text-xs font-semibold">{title}</div>
          <ProvenanceStrip view={buildProvenance(input)} />
        </div>
      ))}
    </div>
  );
}
