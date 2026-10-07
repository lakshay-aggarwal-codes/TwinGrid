import { describe, expect, it } from 'vitest';
import type { Freshness, FreshnessState } from '@/telemetry/freshness';
import { buildProvenance, classifyOrigin, classifyQuality, type EndpointKind, type ProvenanceInput } from './model';

const fresh = (state: FreshnessState, ageMs: number | null = null): Freshness => ({ state, ageMs, staleAfterMs: 9000, lastReceivedAt: null });
const input = (over: Partial<ProvenanceInput> = {}, kind: EndpointKind | null = 'live-feed'): ProvenanceInput => ({ source: { kind }, ...over });
const detail = (i: ProvenanceInput, id: string) => buildProvenance(i).detail.find((r) => r.id === id)!;

describe('origin -> displayed state (exhaustive, incl. unknown)', () => {
  it.each([
    ['simulated', 'simulated', 'Simulated'],
    ['measured', 'measured', 'Measured'],
    ['replayed', 'replayed', 'Replayed (not live)'],
    [undefined, 'unverified', 'Unverified source'],
    [null, 'unverified', 'Unverified source'],
    ['', 'unverified', 'Unverified source'],
    ['telemetry', 'unverified', 'Unverified source'],
    ['Measured', 'unverified', 'Unverified source'], // case-sensitive: not the backend value
    ['MEASURED', 'unverified', 'Unverified source'],
    [' measured', 'unverified', 'Unverified source'],
    ['measured ', 'unverified', 'Unverified source'],
    ['live', 'unverified', 'Unverified source'],
    [1, 'unverified', 'Unverified source'],
    [true, 'unverified', 'Unverified source'],
    [{ origin: 'measured' }, 'unverified', 'Unverified source'],
  ])('origin %j -> %s', (origin, state, text) => {
    const o = classifyOrigin(origin);
    expect(o.state).toBe(state);
    expect(o.text).toBe(text);
    expect(buildProvenance(input({ origin: origin as string })).origin.state).toBe(state);
  });

  it('`measured` is reachable only from the backend origin "measured", whatever else the input says', () => {
    const kinds: Array<EndpointKind | null> = [null, 'live-feed', 'preview', 'run-result', 'evaluation', 'topology', 'alert', 'report'];
    const others = [undefined, null, 'simulated', 'replayed', 'unknown', 'Measured'];
    for (const kind of kinds) {
      for (const origin of others) {
        const v = buildProvenance({
          source: { kind },
          origin,
          quality: 'good',
          weatherSource: 'measured',
          plantKind: 'measured',
          datasetId: 'measured',
          freshness: fresh('live', 0),
        });
        expect(v.origin.state).not.toBe('measured');
        expect(v.origin.text).not.toBe('Measured');
      }
    }
    expect(buildProvenance(input({ origin: 'measured' })).origin.state).toBe('measured');
  });

  it('simulated origin carries the simulator tooltip; absent origin is never styled as simulated or measured', () => {
    expect(classifyOrigin('simulated').tooltip).toMatch(/physics simulator, not measured telemetry/);
    expect(classifyOrigin(undefined).state).toBe('unverified');
  });

  it('each origin state has a distinct icon shape', () => {
    const icons = ['measured', 'simulated', 'replayed', undefined].map((o) => classifyOrigin(o).icon);
    expect(new Set(icons).size).toBe(4);
  });
});

describe('quality', () => {
  it.each([
    ['good', 'good'],
    ['suspect', 'suspect'],
    ['invalid', 'invalid'],
    ['bad', 'unrecognised'],
    ['Good', 'unrecognised'],
    [undefined, null],
    [null, null],
  ])('%j -> %s', (raw, expected) => {
    expect(classifyQuality(raw)).toBe(expected);
  });

  it('suspect / invalid add a flag; good / unknown / absent add none (and unknown is not shown as good)', () => {
    const flag = (q?: string) => buildProvenance(input({ origin: 'simulated', quality: q })).flags.find((f) => f.id === 'quality');
    expect(flag('suspect')?.text).toBe('Suspect');
    expect(flag('invalid')?.text).toBe('Invalid');
    expect(flag('good')).toBeUndefined();
    expect(flag('bad')).toBeUndefined();
    expect(flag(undefined)).toBeUndefined();
    expect(detail(input({ quality: 'bad' }), 'quality').value).toBe('not recognised');
    expect(detail(input({ quality: 'good' }), 'quality').value).toBe('Good');
    expect(detail(input({}), 'quality')).toMatchObject({ value: 'not reported', reported: false });
  });
});

describe('kind only labels; it never upgrades trust', () => {
  it('preview adds the Preview flag and nothing else changes the origin', () => {
    const v = buildProvenance(input({}, 'preview'));
    expect(v.flags.map((f) => f.id)).toEqual(['preview']);
    expect(v.flags[0].text).toBe('Preview — what this configuration would produce');
    expect(v.origin.state).toBe('unverified');
  });

  it.each([
    ['preview', true],
    ['run-result', true],
    ['evaluation', true],
    ['live-feed', false],
    ['topology', false],
    ['alert', false],
    ['report', false],
    [null, false],
  ] as const)('simulator-only for kind %s with origin=simulated: %s', (kind, expected) => {
    const v = buildProvenance({ source: { kind }, origin: 'simulated' });
    expect(v.flags.some((f) => f.id === 'simulator-only')).toBe(expected);
  });

  it('simulator-only is not shown when origin is not simulated', () => {
    for (const origin of [undefined, 'measured', 'replayed', 'x']) {
      expect(buildProvenance({ source: { kind: 'run-result' }, origin }).flags.some((f) => f.id === 'simulator-only')).toBe(false);
    }
  });
});

describe('Reference weather, simulated plant', () => {
  it.each([
    ['reference', 'simulated', 'Reference weather, simulated plant', true],
    ['reference', undefined, 'weather/plant source not reported', false],
    [undefined, 'simulated', 'weather/plant source not reported', false],
    [undefined, undefined, 'weather/plant source not reported', false],
    ['reference', null, 'weather/plant source not reported', false],
    ['Reference', 'simulated', 'weather: Reference; plant: simulated', false],
    ['station', 'simulated', 'weather: station; plant: simulated', false],
  ])('weather=%s plant=%s', (weatherSource, plantKind, value, flagged) => {
    const i = input({ weatherSource: weatherSource as string | undefined, plantKind: plantKind as string | undefined });
    const v = buildProvenance(i);
    expect(v.flags.some((f) => f.id === 'weather')).toBe(flagged);
    expect(detail(i, 'weather-plant').value).toBe(value);
  });
});

describe('uncalibrated / fallback inputs', () => {
  it('uncalibrated flag only when the backend says so; absent -> "not reported" in detail', () => {
    expect(buildProvenance(input({ calibration: 'uncalibrated' })).flags.map((f) => f.id)).toContain('uncalibrated');
    expect(buildProvenance(input({ calibration: 'calibrated' })).flags.map((f) => f.id)).not.toContain('uncalibrated');
    expect(buildProvenance(input({})).flags.map((f) => f.id)).not.toContain('uncalibrated');
    expect(detail(input({}), 'calibration')).toMatchObject({ value: 'not reported', reported: false });
    expect(detail(input({ calibration: 'uncalibrated' }), 'calibration').value).toBe('Uncalibrated');
  });

  it('fallback carbon uses the fixed wording; other items are named; duplicates collapse', () => {
    const v = buildProvenance(input({ inputsFallback: ['carbon', 'carbon', 'weather'] }));
    expect(v.flags.filter((f) => f.id === 'fallback').map((f) => f.text)).toEqual(['Fallback carbon (flat constant)', 'Fallback input: weather']);
  });

  it('empty fallback list = "none" (reported); missing = "not reported"', () => {
    expect(detail(input({ inputsFallback: [] }), 'fallback')).toMatchObject({ value: 'none', reported: true });
    expect(detail(input({}), 'fallback')).toMatchObject({ value: 'not reported', reported: false });
    expect(buildProvenance(input({ inputsFallback: [] })).flags).toHaveLength(0);
  });
});

describe('freshness chip', () => {
  it.each([
    ['live', 800, 'Live', 'fresh-live'],
    ['connecting', null, 'Connecting', 'fresh-connecting'],
    ['stale', 42_000, 'Stale · last update 42 s ago', 'fresh-stale'],
    ['stale', null, 'Stale · no update received', 'fresh-stale'],
    ['disconnected', 120_000, 'Disconnected · last data 2 min ago', 'fresh-disconnected'],
    ['disconnected', null, 'Disconnected · no data received', 'fresh-disconnected'],
    ['reconnecting', 5000, 'Reconnecting', 'fresh-reconnecting'],
    ['unavailable', 3_600_000, 'Unavailable — the backend health check is failing', 'fresh-unavailable'],
  ] as const)('%s (age %s) -> "%s"', (state, ageMs, text, icon) => {
    const chip = buildProvenance(input({ freshness: fresh(state, ageMs) })).freshness!;
    expect(chip.text).toBe(text);
    expect(chip.icon).toBe(icon);
    expect(chip.state).toBe(state);
  });

  it('reconnecting shows the attempt number only when the transport supplies a valid one', () => {
    const t = (n: number | null | undefined) => buildProvenance(input({ freshness: fresh('reconnecting'), reconnectAttempt: n })).freshness!.text;
    expect(t(3)).toBe('Reconnecting (attempt 3)');
    expect(t(undefined)).toBe('Reconnecting');
    expect(t(0)).toBe('Reconnecting');
    expect(t(Number.NaN)).toBe('Reconnecting');
  });

  it('only live reads as live; stale/disconnected/reconnecting/unavailable never contain "Live"', () => {
    for (const s of ['stale', 'disconnected', 'reconnecting', 'unavailable', 'connecting'] as const) {
      expect(buildProvenance(input({ freshness: fresh(s, 1000) })).freshness!.text).not.toMatch(/\blive\b/i);
    }
  });

  it('disconnected is the only assertive announcement; announcements carry no age', () => {
    for (const s of ['live', 'connecting', 'stale', 'disconnected', 'reconnecting', 'unavailable'] as const) {
      const chip = buildProvenance(input({ freshness: fresh(s, 42_000) })).freshness!;
      expect(chip.assertive).toBe(s === 'disconnected');
      expect(chip.announcement).not.toMatch(/\d/);
    }
  });

  it('no freshness (REST payload) -> no chip; it is never defaulted to live', () => {
    expect(buildProvenance(input({}, 'report')).freshness).toBeNull();
    expect(detail(input({}, 'report'), 'freshness')).toMatchObject({ value: 'not reported', reported: false });
  });

  it('an unrecognised freshness state degrades to unavailable, never current', () => {
    const chip = buildProvenance(input({ freshness: { ...fresh('live'), state: 'warp' as FreshnessState } })).freshness!;
    expect(chip.state).toBe('unavailable');
  });

  it.each([
    ['health', 'Unavailable — the backend health check is failing'],
    ['invalid_payload', 'Unavailable — the data received was not valid'],
    ['model_unavailable', 'Unavailable — no valid model is available'],
    ['schema_incompatible', 'Unavailable — the data format is not supported by this client'],
  ] as const)('unavailableReason %s uses fixed copy and overrides a live freshness', (reason, text) => {
    const chip = buildProvenance(input({ freshness: fresh('live', 0), unavailableReason: reason })).freshness!;
    expect(chip.state).toBe('unavailable');
    expect(chip.text).toBe(text);
  });

  it('browser receipt age falls back to receivedAt/now only when freshness has no age', () => {
    expect(detail(input({ receivedAt: 1000, now: 43_000 }), 'browser-receipt').value).toBe('42 s ago');
    expect(detail(input({ receivedAt: 1000 }), 'browser-receipt').reported).toBe(false);
    expect(detail(input({ freshness: fresh('stale', 61_000), receivedAt: 0, now: 1 }), 'browser-receipt').value).toBe('1 min ago');
  });
});

describe('time labels: three distinct clocks', () => {
  const i = input({ serverTime: '2026-10-06T14:03:21Z', simTime: '2026-01-01T12:35:00', freshness: fresh('stale', 42_000) }, 'live-feed');

  it('strip line matches the contract example', () => {
    expect(buildProvenance(i).strip.line).toBe('Live feed · server time 14:03:21 UTC · simulated clock 2026-01-01 12:35');
  });

  it('detail keeps server time, simulated clock and browser receipt age as separate rows', () => {
    expect(detail(i, 'server-time')).toMatchObject({ label: 'Last updated — server time', value: '2026-10-06 14:03:21 UTC' });
    expect(detail(i, 'sim-clock')).toMatchObject({ label: 'Last updated — simulated clock', value: '2026-01-01 12:35:00' });
    expect(detail(i, 'browser-receipt')).toMatchObject({ label: 'Last received — browser receipt age', value: '42 s ago' });
  });

  it('server time with an offset is shown in UTC; the simulated clock is labelled, never converted', () => {
    const v = input({ serverTime: '2026-10-06T16:03:21+02:00', simTime: '2026-01-01T12:35:00+05:00' });
    expect(detail(v, 'server-time').value).toBe('2026-10-06 14:03:21 UTC');
    expect(detail(v, 'sim-clock').value).toBe('2026-01-01 12:35:00+05:00');
  });

  it('an offset-less server time is a contract violation: unreadable, not guessed', () => {
    const v = input({ serverTime: '2026-10-06T14:03:21' });
    expect(detail(v, 'server-time')).toMatchObject({ value: 'not reported (unreadable)', reported: false });
    expect(buildProvenance(v).strip.line).toBe('Live feed');
  });

  it('missing times are listed as not reported and left out of the strip line', () => {
    const v = input({});
    expect(detail(v, 'server-time').value).toBe('not reported');
    expect(detail(v, 'sim-clock').value).toBe('not reported');
    expect(buildProvenance(v).strip.line).toBe('Live feed');
  });

  it('no row says "browser time" for data time and no clock is read: the model is deterministic', () => {
    expect(JSON.stringify(buildProvenance(i))).toBe(JSON.stringify(buildProvenance(i)));
  });
});

describe('detail tier is exhaustive: every field is listed, missing ones as "not reported"', () => {
  const IDS = [
    'origin', 'quality', 'source', 'server-time', 'sim-clock', 'browser-receipt', 'freshness', 'scenario', 'run', 'physics', 'model',
    'detector', 'trained-on', 'dataset', 'weather-plant', 'evaluation', 'calibration', 'fallback',
  ];

  it('an empty input lists every row, each unreported', () => {
    const rows = buildProvenance({ source: { kind: null } }).detail;
    expect(rows.map((r) => r.id)).toEqual(IDS);
    for (const r of rows) {
      expect(r.value).not.toBe('');
      expect(r.value).not.toBe('0');
    }
    const unreported = rows.filter((r) => !r.reported).map((r) => r.id);
    expect(unreported).toEqual(IDS); // origin reads "Unverified source (origin not reported)"
    expect(rows[0].value).toBe('Unverified source (origin not reported)');
    expect(rows.slice(1).every((r) => /^(not reported|Unverified)/.test(r.value) || r.id === 'weather-plant')).toBe(true);
  });

  it('a full input reports every row', () => {
    const rows = buildProvenance({
      source: { kind: 'run-result' },
      origin: 'simulated',
      quality: 'good',
      inputsFallback: [],
      weatherSource: 'reference',
      plantKind: 'simulated',
      scenarioId: 'scn-7',
      runId: 42,
      physicsVersion: '1.2.0',
      modelVersion: 'm-3',
      detectorId: 'iforest',
      trainedOn: 'ashrae',
      datasetId: 'ds-9',
      evaluationStatus: 'complete',
      calibration: 'calibrated',
      serverTime: '2026-10-06T14:03:21Z',
      simTime: '2026-01-01T12:35:00',
      freshness: fresh('live', 0),
    }).detail;
    expect(rows.filter((r) => !r.reported)).toEqual([]);
  });

  it('numeric ids are shown; 0 is a real value, not "missing"', () => {
    expect(detail(input({ runId: 0 }), 'run')).toMatchObject({ value: '0', reported: true });
  });

  it('unreadable identifier text is never rendered raw', () => {
    const v = detail(input({ modelVersion: '<script>alert(1)</script>' }), 'model');
    expect(v).toMatchObject({ value: 'not reported (unreadable)', reported: false });
  });

  it('scenario and run ids reach the strip when present', () => {
    const v = buildProvenance(input({ scenarioId: 'scn-7', runId: 'run-2' }, 'run-result'));
    expect(v.strip.scenario).toBe('scn-7');
    expect(v.strip.run).toBe('run-2');
    expect(buildProvenance(input({}, 'run-result')).strip).toMatchObject({ scenario: null, run: null });
  });
});

describe('combinations never contradict the origin', () => {
  const origins = [undefined, 'simulated', 'measured', 'replayed', 'nope'];
  const states: FreshnessState[] = ['connecting', 'live', 'stale', 'disconnected', 'reconnecting', 'unavailable'];
  const qualities = [undefined, 'good', 'suspect', 'invalid', 'zzz'];
  const kinds: Array<EndpointKind | null> = [null, 'live-feed', 'preview', 'run-result', 'evaluation', 'topology', 'alert', 'report'];

  it('every origin x freshness x quality x kind combination builds, keeps its origin, and renders non-empty text', () => {
    let n = 0;
    for (const origin of origins) {
      for (const state of states) {
        for (const quality of qualities) {
          for (const kind of kinds) {
            const v = buildProvenance({ source: { kind }, origin, quality, freshness: fresh(state, 5000) });
            n++;
            expect(v.origin.state).toBe(classifyOrigin(origin).state);
            expect(v.origin.text.length).toBeGreaterThan(0);
            expect(v.freshness!.state).toBe(state);
            expect(v.freshness!.text.length).toBeGreaterThan(0);
            expect(v.detail).toHaveLength(18);
          }
        }
      }
    }
    expect(n).toBe(origins.length * states.length * qualities.length * kinds.length);
  });
});
