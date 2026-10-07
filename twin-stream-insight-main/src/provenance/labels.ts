/**
 * FE-05: every user-facing provenance string, in one place (roadmap §7).
 * The scientific-caveat phrases are the MR phrases VERBATIM -- do not reword them.
 * Backend free text never reaches this file or the DOM; only the fixed copy below does.
 */
import type { EndpointKind, UnavailableReason } from './model';

export const NOT_REPORTED = 'not reported';

export const LABELS = {
  simulated: 'Simulated',
  simulatedTooltip: 'Values from the physics simulator, not measured telemetry.',
  measured: 'Measured',
  replayed: 'Replayed (not live)',
  unverified: 'Unverified source',
  unverifiedTooltip: 'The backend did not state where these values came from, or stated a source this client does not recognise.',
  preview: 'Preview — what this configuration would produce',
  previewShort: 'Preview',
  weather: 'Reference weather, simulated plant',
  weatherNotReported: 'weather/plant source not reported',
  simulatorOnly: 'Simulator-only',
  uncalibrated: 'Uncalibrated',
  fallbackCarbon: 'Fallback carbon (flat constant)',
  fallbackOther: 'Fallback input',
  suspect: 'Suspect',
  invalid: 'Invalid',
  connecting: 'Connecting',
  live: 'Live',
} as const;

export const KIND_LABEL: Record<EndpointKind, string> = {
  'live-feed': 'Live feed',
  preview: 'Preview',
  'run-result': 'Run result',
  evaluation: 'Evaluation',
  topology: 'Facility topology',
  alert: 'Alert',
  report: 'Report',
};

/** Fixed, safe reasons. Never backend `detail`/body text. */
export const UNAVAILABLE_REASON: Record<UnavailableReason, string> = {
  health: 'the backend health check is failing',
  invalid_payload: 'the data received was not valid',
  model_unavailable: 'no valid model is available',
  schema_incompatible: 'the data format is not supported by this client',
};

export const DETAIL_LABELS = {
  origin: 'Origin',
  quality: 'Quality',
  source: 'Source / context',
  serverTime: 'Last updated — server time',
  simClock: 'Last updated — simulated clock',
  browserReceipt: 'Last received — browser receipt age',
  freshness: 'Freshness',
  scenario: 'Scenario id',
  run: 'Run id',
  physics: 'Physics version',
  model: 'Model version',
  detector: 'Detector',
  trainedOn: 'Trained on',
  dataset: 'Dataset',
  weatherPlant: 'Weather / plant',
  evaluation: 'Evaluation status',
  calibration: 'Calibration',
  fallback: 'Fallback inputs',
} as const;

/** "42 s ago" / "2 min ago" / "3 h ago". Whole units only: no sub-second precision is claimed. */
export function formatAge(ageMs: number): string {
  const s = Math.max(0, Math.floor(ageMs / 1000));
  if (s < 60) return `${s} s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  return `${Math.floor(m / 60)} h ago`;
}
