import { describe, expect, it } from 'vitest';
import { buildProvenance } from '@/provenance/model';
import {
  CONSTANT_INPUT_WEATHER_TEXT,
  controlText,
  initialValues,
  kindSupport,
  overridesOf,
  paramFields,
  runRequest,
  scenarioProvenance,
  validateValues,
  weatherPlantText,
} from './model';
import type { ScenarioDescriptor } from './schema';
import { CAPTURED_REGISTRY, clone } from './testFixtures';

const byId = (id: string): ScenarioDescriptor => clone(CAPTURED_REGISTRY).scenarios.find((s) => s.id === id) as ScenarioDescriptor;

describe('kindSupport', () => {
  it.each(['workload', 'heat-wave', 'drought', 'weather', 'physics-perturbation'])('%s is supported', (k) => {
    expect(kindSupport(k).supported).toBe(true);
  });
  it.each(['carbon-shock', '', null, undefined, 'Workload'])('%s is unsupported', (k) => {
    expect(kindSupport(k as string | null | undefined).supported).toBe(false);
  });
  it('every captured descriptor is a supported kind', () => {
    expect(CAPTURED_REGISTRY.scenarios.every((s) => kindSupport(s.kind).supported)).toBe(true);
  });
});

describe('weatherPlantText is computed from descriptor fields, never from the name', () => {
  it('constant_input + simulated (what the backend reports today) is NOT "Reference weather"', () => {
    expect(weatherPlantText(byId('whatif-heat-wave'))).toBe(CONSTANT_INPUT_WEATHER_TEXT);
  });
  it('reference + simulated gives the reference label', () => {
    expect(weatherPlantText({ weather_source: 'reference', plant: 'simulated' })).toBe('Reference weather, simulated plant');
  });
  it('a scenario NAMED like the label gets no reference label without the fields', () => {
    const d = { ...byId('whatif-baseline'), label: 'Reference weather, simulated plant', weather_source: 'constant_input' };
    expect(weatherPlantText(d)).toBe(CONSTANT_INPUT_WEATHER_TEXT);
  });
  it.each([
    [{ weather_source: undefined, plant: 'simulated' }],
    [{ weather_source: 'reference', plant: undefined }],
    [{ weather_source: '', plant: '' }],
    [{ weather_source: null, plant: null }],
  ])('a missing field is "weather/plant source not reported": %j', (d) => {
    expect(weatherPlantText(d as never)).toBe('weather/plant source not reported');
  });
  it('an unrecognised pair is shown as given and never as reference', () => {
    const t = weatherPlantText({ weather_source: 'ensemble', plant: 'real' });
    expect(t).toContain('ensemble');
    expect(t).not.toBe('Reference weather, simulated plant');
  });
});

describe('controlText', () => {
  it('never assumes "none" when the backend did not say', () => {
    expect(controlText({ control: undefined })).toBe('Control: not reported');
    expect(controlText({ control: 'none' })).toMatch(/nothing is sent to a facility/);
    expect(controlText({ control: 'advisory' })).toBe('Control: advisory');
  });
});

describe('parameter form from the backend schema', () => {
  const d = byId('whatif-heat-wave');
  const { fields, unrecognised } = paramFields(d);

  it('has one field per backend parameter, in backend order, with backend bounds and options', () => {
    expect(unrecognised).toEqual([]);
    expect(fields.map((f) => f.name)).toEqual(['utilisation', 'outside_temp', 'water_stress', 'mode', 'chilled_water_temp']);
    const temp = fields.find((f) => f.name === 'outside_temp');
    expect([temp?.min, temp?.max, temp?.unit, temp?.defaultValue]).toEqual([-10, 50, '°C', '38']);
    expect(fields.find((f) => f.name === 'mode')?.options).toEqual(['auto', 'free_air', 'closed_loop', 'evaporative', 'hybrid']);
  });

  it('a parameter type this client does not know is listed, not rendered and not sent', () => {
    const odd = { ...d, parameters: [...(d.parameters ?? []), { name: 'seed', type: 'integer', default: 1 }] } as ScenarioDescriptor;
    expect(paramFields(odd).unrecognised).toEqual(['seed']);
    expect(paramFields(odd).fields.map((f) => f.name)).not.toContain('seed');
  });

  it('an enum without options is not rendered', () => {
    expect(paramFields({ parameters: [{ name: 'm', type: 'enum', options: [] }] }).unrecognised).toEqual(['m']);
  });

  it('validation mirrors only supplied bounds', () => {
    const v = { ...initialValues(fields) };
    expect(validateValues(fields, v)).toEqual({});
    expect(validateValues(fields, { ...v, outside_temp: '99' }).outside_temp).toBe('Must be at most 50');
    expect(validateValues(fields, { ...v, outside_temp: '-11' }).outside_temp).toBe('Must be at least -10');
    expect(validateValues(fields, { ...v, utilisation: '' }).utilisation).toBe('Enter a number');
    expect(validateValues(fields, { ...v, mode: 'turbo' }).mode).toBe('Choose one of the listed options');
    const unbounded = [{ ...fields[0], min: null, max: null }];
    expect(validateValues(unbounded, { utilisation: '1000' })).toEqual({});
  });
});

describe('runRequest', () => {
  const d = byId('whatif-heat-wave');
  const { fields } = paramFields(d);

  it('always carries the selected scenario id; unchanged defaults are not sent (the backend preset stays authoritative)', () => {
    expect(runRequest(d, fields, initialValues(fields))).toEqual({ scenario_id: 'whatif-heat-wave' });
  });

  it('sends only values the person changed, under the backend parameter names', () => {
    const values = { ...initialValues(fields), outside_temp: '30', mode: 'hybrid' };
    expect(overridesOf(fields, values)).toEqual({ outside_temp: 30, mode: 'hybrid' });
    expect(runRequest(d, fields, values)).toEqual({ scenario_id: 'whatif-heat-wave', outside_temp: 30, mode: 'hybrid' });
  });

  it('is null while a value is invalid, and for an unsupported kind', () => {
    expect(runRequest(d, fields, { ...initialValues(fields), outside_temp: '99' })).toBeNull();
    expect(runRequest({ ...d, kind: 'carbon-shock' }, fields, initialValues(fields))).toBeNull();
  });
});

describe('scenario provenance', () => {
  it('the selected scenario id and the descriptor weather/plant appear in the provenance detail', () => {
    const d = byId('whatif-drought');
    const view = buildProvenance(scenarioProvenance(d, null));
    expect(view.detail.find((r) => r.id === 'scenario')).toMatchObject({ value: 'whatif-drought', reported: true });
    expect(view.detail.find((r) => r.id === 'weather-plant')?.value).toBe('weather: constant_input; plant: simulated');
    expect(view.strip.scenario).toBe('whatif-drought');
  });

  it('origin is not invented: a preview with no backend origin reads "Unverified source" and Preview', () => {
    const view = buildProvenance(scenarioProvenance(byId('whatif-baseline'), null));
    expect(view.origin.state).toBe('unverified');
    expect(view.flags.some((f) => f.id === 'preview')).toBe(true);
  });

  it('physics version is shown only when the result carries one; fallback carbon is flagged from the backend flag', () => {
    const d = byId('whatif-baseline');
    const without = buildProvenance(scenarioProvenance(d, { carbon_data_is_real: false }));
    expect(without.detail.find((r) => r.id === 'physics')?.reported).toBe(false);
    expect(without.flags.some((f) => f.id === 'fallback')).toBe(true);
    const withV = buildProvenance(scenarioProvenance(d, { carbon_data_is_real: true, physics_version: '1' }));
    expect(withV.detail.find((r) => r.id === 'physics')?.value).toBe('1');
    expect(withV.flags.some((f) => f.id === 'fallback')).toBe(false);
  });

  it('a descriptor without weather/plant says so and never claims reference weather', () => {
    const view = buildProvenance(scenarioProvenance({ id: 'x', weather_source: undefined, plant: undefined }, null));
    expect(view.detail.find((r) => r.id === 'weather-plant')?.value).toBe('weather/plant source not reported');
    expect(view.flags.some((f) => f.id === 'weather')).toBe(false);
  });
});
