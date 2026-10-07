/**
 * FE-05: provenance view-model (roadmap §7). PURE: no React, no clock, no network.
 *
 *   buildProvenance(ProvenanceInput) -> ProvenanceView
 *
 * Invariants enforced here (and by model.test.ts / sourceGate.test.ts):
 *  - `ProvenanceView` can only come out of `buildProvenance` (branded type); there is no constructor from a string label.
 *  - The `measured` origin state exists ONLY via `classifyOrigin`, and only for the exact backend value `'measured'`.
 *    Absent / unknown / differently-cased origin => `unverified`.
 *  - `kind` (the endpoint class) only ever adds a label (Preview); it never upgrades trust.
 *  - Derived origin is the backend's: this module displays `origin` as given and never computes a lowest-evidence origin.
 *  - Missing fields become an explicit "not reported" detail row; nothing is silently omitted or shown as 0/blank.
 *  - Server time, simulated clock and browser receipt age are three different rows; browser time is never data time.
 */
import type { Freshness, FreshnessState } from '@/telemetry/freshness';
import { parseInstant } from '@/contract/time';
import { DETAIL_LABELS, KIND_LABEL, LABELS, NOT_REPORTED, UNAVAILABLE_REASON, formatAge } from './labels';

export type EndpointKind = 'live-feed' | 'preview' | 'run-result' | 'evaluation' | 'topology' | 'alert' | 'report';
export type UnavailableReason = 'health' | 'invalid_payload' | 'model_unavailable' | 'schema_incompatible';

export type OriginState = 'measured' | 'simulated' | 'replayed' | 'unverified';
export type QualityState = 'good' | 'suspect' | 'invalid' | 'unrecognised';

/** Icon shape keys. Each displayed state has its own shape so colour is never the only cue. */
export type ProvenanceIconKey =
  | 'origin-measured'
  | 'origin-simulated'
  | 'origin-replayed'
  | 'origin-unverified'
  | 'preview'
  | 'weather'
  | 'simulator-only'
  | 'quality-suspect'
  | 'quality-invalid'
  | 'uncalibrated'
  | 'fallback'
  | 'fresh-connecting'
  | 'fresh-live'
  | 'fresh-stale'
  | 'fresh-disconnected'
  | 'fresh-reconnecting'
  | 'fresh-unavailable';

/** What the frontend knows about where the data came from without a backend field: the endpoint it called. */
export interface ProvenanceSource {
  readonly kind: EndpointKind | null;
}

/**
 * Raw backend metadata (all optional except `source`). Strings are exactly as received; nothing is pre-interpreted.
 * Not constructible from a bare label: callers must provide this object.
 */
export interface ProvenanceInput {
  readonly source: ProvenanceSource;
  readonly origin?: string | null;
  readonly quality?: string | null;
  readonly inputsFallback?: readonly string[] | null;
  readonly weatherSource?: string | null;
  readonly plantKind?: string | null;
  readonly scenarioId?: string | number | null;
  readonly runId?: string | number | null;
  readonly physicsVersion?: string | null;
  readonly modelVersion?: string | null;
  readonly detectorId?: string | null;
  readonly trainedOn?: string | null;
  readonly datasetId?: string | null;
  readonly evaluationStatus?: string | null;
  readonly calibration?: string | null;
  /** `ts_ingest` (aware UTC). */
  readonly serverTime?: string | null;
  /** `sim_time` (simulated clock, offset-less by design). */
  readonly simTime?: string | null;
  /** Monotonic browser receipt time (FE-04). Not data time. */
  readonly receivedAt?: number | null;
  /** Monotonic "now", only used with `receivedAt` when `freshness` is absent. */
  readonly now?: number | null;
  readonly freshness?: Freshness | null;
  /** From the transport while reconnecting. */
  readonly reconnectAttempt?: number | null;
  /** Set when health failed / payload invalid / model unavailable. Fixed enum -> fixed copy; never backend text. */
  readonly unavailableReason?: UnavailableReason | null;
}

export interface OriginView {
  readonly state: OriginState;
  readonly text: string;
  readonly tooltip: string | null;
  readonly icon: ProvenanceIconKey;
}

export type FlagId = 'preview' | 'simulator-only' | 'weather' | 'quality' | 'uncalibrated' | 'fallback';

export interface FlagView {
  readonly id: FlagId;
  /** Full wording (strip / detail tier). */
  readonly text: string;
  /** Compact wording (badge tier). */
  readonly shortText: string;
  readonly icon: ProvenanceIconKey;
  /** Shown in the compact badge as well as the strip. */
  readonly inBadge: boolean;
  readonly tone: 'info' | 'caution' | 'danger';
}

export interface FreshnessChipView {
  readonly state: FreshnessState;
  readonly text: string;
  /** State-only wording (no age) for a live region: changes on transitions, not on every tick. */
  readonly announcement: string;
  readonly icon: ProvenanceIconKey;
  readonly assertive: boolean;
}

export interface DetailRowView {
  readonly id: string;
  readonly label: string;
  readonly value: string;
  /** false => the backend did not provide it (value says "not reported"). */
  readonly reported: boolean;
}

declare const provenanceViewBrand: unique symbol;

export interface ProvenanceView {
  readonly [provenanceViewBrand]: 'ProvenanceView';
  readonly kind: EndpointKind | null;
  readonly origin: OriginView;
  readonly flags: readonly FlagView[];
  readonly freshness: FreshnessChipView | null;
  readonly strip: {
    /** e.g. "Live feed · server time 14:03:21 UTC · simulated clock 2026-01-01 12:35" */
    readonly line: string;
    readonly scenario: string | null;
    readonly run: string | null;
  };
  /** Every field, in a fixed order, "not reported" when missing. */
  readonly detail: readonly DetailRowView[];
}

// ---------------------------------------------------------------------------------------------------------------------
// classification (the ONLY place origin / quality vocab is interpreted)
// ---------------------------------------------------------------------------------------------------------------------

/** Exact, case-sensitive match. The `measured` branch is reachable only for the backend value 'measured'. */
export function classifyOrigin(raw: unknown): OriginView {
  switch (raw) {
    case 'measured':
      return { state: 'measured', text: LABELS.measured, tooltip: null, icon: 'origin-measured' };
    case 'simulated':
      return { state: 'simulated', text: LABELS.simulated, tooltip: LABELS.simulatedTooltip, icon: 'origin-simulated' };
    case 'replayed':
      return { state: 'replayed', text: LABELS.replayed, tooltip: null, icon: 'origin-replayed' };
    default:
      return { state: 'unverified', text: LABELS.unverified, tooltip: LABELS.unverifiedTooltip, icon: 'origin-unverified' };
  }
}

export function classifyQuality(raw: unknown): QualityState | null {
  if (raw === undefined || raw === null) return null;
  if (raw === 'good' || raw === 'suspect' || raw === 'invalid') return raw;
  return 'unrecognised';
}

const DECISION_KINDS: ReadonlySet<EndpointKind> = new Set<EndpointKind>(['preview', 'run-result', 'evaluation']);

/** Identifier-ish backend strings (versions, ids) are shown as-is; anything else is treated as unreadable. */
function token(v: unknown): string | null {
  if (typeof v === 'number' && Number.isFinite(v)) return String(v);
  if (typeof v !== 'string') return null;
  const t = v.trim();
  return t !== '' && t.length <= 80 && /^[\w .:/@+()-]+$/.test(t) ? t : null;
}

function row(id: string, label: string, value: string | null, unreadable = false): DetailRowView {
  if (value === null) return { id, label, value: unreadable ? `${NOT_REPORTED} (unreadable)` : NOT_REPORTED, reported: false };
  return { id, label, value, reported: true };
}

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

function utcParts(epochMs: number) {
  const d = new Date(epochMs);
  return {
    date: `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`,
    time: `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`,
  };
}

function serverTimeText(raw: string | null | undefined): { full: string; clock: string } | 'unreadable' | null {
  if (raw === undefined || raw === null || raw === '') return null;
  const p = parseInstant(raw, 'ingest');
  if (!p.ok || p.kind === 'sim') return 'unreadable';
  const { date, time } = utcParts(p.epochMs);
  return { full: `${date} ${time} UTC`, clock: `${time} UTC` };
}

function simClockText(raw: string | null | undefined): { full: string; short: string } | 'unreadable' | null {
  if (raw === undefined || raw === null || raw === '') return null;
  const p = parseInstant(raw, 'sim');
  if (!p.ok || p.kind !== 'sim') return 'unreadable';
  // Labelled, never converted: only the separator is normalised.
  const full = p.text.replace('T', ' ');
  return { full, short: full.slice(0, 16) };
}

function buildChip(i: ProvenanceInput): FreshnessChipView | null {
  if (i.unavailableReason) {
    const why = UNAVAILABLE_REASON[i.unavailableReason] ?? UNAVAILABLE_REASON.health;
    return {
      state: 'unavailable',
      text: `Unavailable — ${why}`,
      announcement: 'Unavailable',
      icon: 'fresh-unavailable',
      assertive: false,
    };
  }
  const f = i.freshness;
  if (!f) return null;
  const age = f.ageMs === null ? null : formatAge(f.ageMs);
  switch (f.state) {
    case 'live':
      return { state: 'live', text: LABELS.live, announcement: 'Live', icon: 'fresh-live', assertive: false };
    case 'connecting':
      return { state: 'connecting', text: LABELS.connecting, announcement: 'Connecting', icon: 'fresh-connecting', assertive: false };
    case 'stale':
      return {
        state: 'stale',
        text: age ? `Stale · last update ${age}` : 'Stale · no update received',
        announcement: 'Stale',
        icon: 'fresh-stale',
        assertive: false,
      };
    case 'disconnected':
      return {
        state: 'disconnected',
        text: age ? `Disconnected · last data ${age}` : 'Disconnected · no data received',
        announcement: 'Disconnected',
        icon: 'fresh-disconnected',
        assertive: true,
      };
    case 'reconnecting': {
      const n = i.reconnectAttempt;
      const attempt = typeof n === 'number' && Number.isFinite(n) && n > 0 ? ` (attempt ${Math.floor(n)})` : '';
      return { state: 'reconnecting', text: `Reconnecting${attempt}`, announcement: 'Reconnecting', icon: 'fresh-reconnecting', assertive: false };
    }
    case 'unavailable':
      return {
        state: 'unavailable',
        text: `Unavailable — ${UNAVAILABLE_REASON.health}`,
        announcement: 'Unavailable',
        icon: 'fresh-unavailable',
        assertive: false,
      };
    default:
      // A freshness state this client does not know must not look current: treat as unavailable.
      return {
        state: 'unavailable',
        text: `Unavailable — ${UNAVAILABLE_REASON.invalid_payload}`,
        announcement: 'Unavailable',
        icon: 'fresh-unavailable',
        assertive: false,
      };
  }
}

function receiptAgeMs(i: ProvenanceInput): number | null {
  if (i.freshness && i.freshness.ageMs !== null) return i.freshness.ageMs;
  if (typeof i.receivedAt === 'number' && typeof i.now === 'number') return Math.max(0, i.now - i.receivedAt);
  return null;
}

// ---------------------------------------------------------------------------------------------------------------------
// builder
// ---------------------------------------------------------------------------------------------------------------------

export function buildProvenance(input: ProvenanceInput): ProvenanceView {
  const kind = input.source.kind;
  const origin = classifyOrigin(input.origin);
  const quality = classifyQuality(input.quality);
  const chip = buildChip(input);

  const weatherOk = input.weatherSource === 'reference' && input.plantKind === 'simulated';
  const weatherTok = token(input.weatherSource);
  const plantTok = token(input.plantKind);
  const calibrationTok = token(input.calibration);
  const uncalibrated = input.calibration === 'uncalibrated';

  const fallbackItems = Array.from(new Set((input.inputsFallback ?? []).map((x) => token(x)).filter((x): x is string => x !== null)));

  // ---- flags (display order) ----
  const flags: FlagView[] = [];
  if (kind === 'preview') {
    flags.push({ id: 'preview', text: LABELS.preview, shortText: LABELS.previewShort, icon: 'preview', inBadge: true, tone: 'info' });
  }
  if (origin.state === 'simulated' && kind !== null && DECISION_KINDS.has(kind)) {
    flags.push({ id: 'simulator-only', text: LABELS.simulatorOnly, shortText: LABELS.simulatorOnly, icon: 'simulator-only', inBadge: true, tone: 'caution' });
  }
  if (weatherOk) {
    flags.push({ id: 'weather', text: LABELS.weather, shortText: LABELS.weather, icon: 'weather', inBadge: false, tone: 'info' });
  }
  if (quality === 'suspect') {
    flags.push({ id: 'quality', text: LABELS.suspect, shortText: LABELS.suspect, icon: 'quality-suspect', inBadge: true, tone: 'caution' });
  } else if (quality === 'invalid') {
    flags.push({ id: 'quality', text: LABELS.invalid, shortText: LABELS.invalid, icon: 'quality-invalid', inBadge: true, tone: 'danger' });
  }
  if (uncalibrated) {
    flags.push({ id: 'uncalibrated', text: LABELS.uncalibrated, shortText: LABELS.uncalibrated, icon: 'uncalibrated', inBadge: true, tone: 'caution' });
  }
  for (const item of fallbackItems) {
    const text = item === 'carbon' ? LABELS.fallbackCarbon : `${LABELS.fallbackOther}: ${item}`;
    flags.push({ id: 'fallback', text, shortText: text, icon: 'fallback', inBadge: true, tone: 'caution' });
  }

  // ---- strip ----
  const server = serverTimeText(input.serverTime);
  const sim = simClockText(input.simTime);
  const parts: string[] = [kind ? KIND_LABEL[kind] : 'Source context not reported'];
  if (server && server !== 'unreadable') parts.push(`server time ${server.clock}`);
  if (sim && sim !== 'unreadable') parts.push(`simulated clock ${sim.short}`);
  const scenario = token(input.scenarioId);
  const run = token(input.runId);

  // ---- detail (always every row) ----
  const ageMs = receiptAgeMs(input);
  const weatherValue = weatherOk
    ? LABELS.weather
    : weatherTok !== null && plantTok !== null
      ? `weather: ${weatherTok}; plant: ${plantTok}`
      : LABELS.weatherNotReported;

  const detail: DetailRowView[] = [
    { id: 'origin', label: DETAIL_LABELS.origin, value: origin.state === 'unverified' ? `${origin.text} (origin ${input.origin == null ? NOT_REPORTED : 'not recognised'})` : origin.text, reported: origin.state !== 'unverified' },
    quality === null
      ? row('quality', DETAIL_LABELS.quality, null)
      : row('quality', DETAIL_LABELS.quality, quality === 'unrecognised' ? 'not recognised' : quality[0].toUpperCase() + quality.slice(1)),
    row('source', DETAIL_LABELS.source, kind ? KIND_LABEL[kind] : null),
    server === 'unreadable'
      ? row('server-time', DETAIL_LABELS.serverTime, null, true)
      : row('server-time', DETAIL_LABELS.serverTime, server ? server.full : null),
    sim === 'unreadable'
      ? row('sim-clock', DETAIL_LABELS.simClock, null, true)
      : row('sim-clock', DETAIL_LABELS.simClock, sim ? sim.full : null),
    row('browser-receipt', DETAIL_LABELS.browserReceipt, ageMs === null ? null : formatAge(ageMs)),
    row('freshness', DETAIL_LABELS.freshness, chip ? chip.text : null),
    row('scenario', DETAIL_LABELS.scenario, scenario, input.scenarioId != null),
    row('run', DETAIL_LABELS.run, run, input.runId != null),
    row('physics', DETAIL_LABELS.physics, token(input.physicsVersion), input.physicsVersion != null),
    row('model', DETAIL_LABELS.model, token(input.modelVersion), input.modelVersion != null),
    row('detector', DETAIL_LABELS.detector, token(input.detectorId), input.detectorId != null),
    row('trained-on', DETAIL_LABELS.trainedOn, token(input.trainedOn), input.trainedOn != null),
    row('dataset', DETAIL_LABELS.dataset, token(input.datasetId), input.datasetId != null),
    { id: 'weather-plant', label: DETAIL_LABELS.weatherPlant, value: weatherValue, reported: weatherOk || (weatherTok !== null && plantTok !== null) },
    row('evaluation', DETAIL_LABELS.evaluation, token(input.evaluationStatus), input.evaluationStatus != null),
    row('calibration', DETAIL_LABELS.calibration, uncalibrated ? LABELS.uncalibrated : calibrationTok, input.calibration != null),
    input.inputsFallback == null
      ? row('fallback', DETAIL_LABELS.fallback, null)
      : { id: 'fallback', label: DETAIL_LABELS.fallback, value: fallbackItems.length ? fallbackItems.join(', ') : 'none', reported: true },
  ];

  const view = {
    kind,
    origin,
    flags,
    freshness: chip,
    strip: { line: parts.join(' · '), scenario, run },
    detail,
  };
  return view as unknown as ProvenanceView;
}
