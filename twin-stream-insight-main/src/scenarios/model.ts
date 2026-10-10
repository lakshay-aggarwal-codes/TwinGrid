/**
 * FE-15: PURE scenario view-model (no React, no clock, no network). Everything is derived from backend descriptor fields.
 *
 *  - No scenario list, id, parameter name or bound is hardcoded here: they all come from the descriptor.
 *  - The weather/plant label is computed from `weather_source` + `plant`, never from the scenario's name or id.
 *  - A `kind` this client does not know is "Unsupported scenario type" (state `unsupported_scenario`), never guessed.
 *  - Client validation only mirrors bounds the backend supplied; the backend remains the authority (422 is final).
 */
import type { ProvenanceInput } from '@/provenance/model';
import { LABELS } from '@/provenance/labels';
import type { ScenarioDescriptor, ScenarioParameter } from './schema';

/** What the pack allows a descriptor `kind` to be. A kind is only offered when the backend lists it AND it is one of these. */
const KIND_TEXT: Readonly<Record<string, string>> = {
  weather: 'Weather',
  'heat-wave': 'Heat wave',
  drought: 'Drought',
  workload: 'Workload',
  'physics-perturbation': 'Physics perturbation',
};

export const UNSUPPORTED_SCENARIO_TEXT = 'Unsupported scenario type';
export const CONSTANT_INPUT_WEATHER_TEXT = 'Constant-input weather, simulated plant';

export type KindSupport = { supported: true; text: string } | { supported: false; raw: string | null };

export function kindSupport(kind: string | null | undefined): KindSupport {
  if (typeof kind === 'string' && Object.prototype.hasOwnProperty.call(KIND_TEXT, kind)) return { supported: true, text: KIND_TEXT[kind] };
  return { supported: false, raw: typeof kind === 'string' && kind !== '' ? kind : null };
}

const present = (v: unknown): v is string => typeof v === 'string' && v.trim() !== '';

/**
 * "Reference weather, simulated plant" only when the descriptor says `reference` AND `simulated`.
 * Today the backend reports `constant_input`: ONE outside temperature held for the run, which is not reference weather.
 */
export function weatherPlantText(d: Pick<ScenarioDescriptor, 'weather_source' | 'plant'>): string {
  const w = d.weather_source;
  const p = d.plant;
  if (!present(w) || !present(p)) return LABELS.weatherNotReported;
  if (w === 'reference' && p === 'simulated') return LABELS.weather;
  if (w === 'constant_input' && p === 'simulated') return CONSTANT_INPUT_WEATHER_TEXT;
  return `Unrecognised weather/plant source (weather: ${w}; plant: ${p})`;
}

/** What the backend says about control. Shown as reported; a missing field is "not reported", never assumed "none". */
export function controlText(d: Pick<ScenarioDescriptor, 'control'>): string {
  if (!present(d.control)) return 'Control: not reported';
  if (d.control === 'none') return 'Control: none (evaluated in simulation; nothing is sent to a facility)';
  return `Control: ${d.control}`;
}

// ------------------------------------------------------------------------------------------------ parameter form

export interface ParamField {
  readonly name: string;
  readonly label: string;
  readonly kind: 'number' | 'enum';
  readonly unit: string | null;
  readonly min: number | null;
  readonly max: number | null;
  readonly options: readonly string[];
  readonly defaultValue: string;
  readonly description: string | null;
}

export interface ParamFields {
  readonly fields: readonly ParamField[];
  /** Parameter names whose type this client does not understand: listed, never rendered as an input, never sent. */
  readonly unrecognised: readonly string[];
}

const humanise = (name: string) => {
  const t = name.replace(/_/g, ' ').trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
};

function fieldOf(p: ScenarioParameter): ParamField | null {
  const base = {
    name: p.name,
    label: humanise(p.name),
    unit: present(p.unit) ? p.unit : null,
    description: present(p.description) ? p.description : null,
    defaultValue: p.default === null || p.default === undefined ? '' : String(p.default),
  };
  if (p.type === 'number') {
    return { ...base, kind: 'number', min: typeof p.min === 'number' ? p.min : null, max: typeof p.max === 'number' ? p.max : null, options: [] };
  }
  if (p.type === 'enum' && Array.isArray(p.options) && p.options.length > 0) {
    return { ...base, kind: 'enum', min: null, max: null, options: p.options };
  }
  return null;
}

export function paramFields(d: Pick<ScenarioDescriptor, 'parameters'>): ParamFields {
  const fields: ParamField[] = [];
  const unrecognised: string[] = [];
  for (const p of d.parameters ?? []) {
    const f = fieldOf(p);
    if (f) fields.push(f);
    else unrecognised.push(p.name);
  }
  return { fields, unrecognised };
}

export type ParamValues = Readonly<Record<string, string>>;

export function initialValues(fields: readonly ParamField[]): ParamValues {
  return Object.fromEntries(fields.map((f) => [f.name, f.defaultValue]));
}

/** Messages keyed by parameter name. Empty object = valid. Only backend-supplied bounds/options are enforced. */
export function validateValues(fields: readonly ParamField[], values: ParamValues): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const f of fields) {
    const raw = values[f.name] ?? '';
    if (f.kind === 'enum') {
      if (!f.options.includes(raw)) errors[f.name] = 'Choose one of the listed options';
      continue;
    }
    if (raw.trim() === '' || !Number.isFinite(Number(raw))) {
      errors[f.name] = 'Enter a number';
    } else if (f.min !== null && Number(raw) < f.min) {
      errors[f.name] = `Must be at least ${f.min}`;
    } else if (f.max !== null && Number(raw) > f.max) {
      errors[f.name] = `Must be at most ${f.max}`;
    }
  }
  return errors;
}

/**
 * The scenario run request, sent to the endpoint the backend documents (`/api/whatif`). The scenario id is always
 * included. Only values the user changed from the descriptor default are sent as explicit overrides, so the backend's
 * own preset stays authoritative for everything else (precedence there: explicit value > preset > built-in default).
 * Returns null while any value is invalid.
 */
export interface ScenarioRunRequest {
  readonly scenario_id: string;
  readonly [param: string]: string | number;
}

export function overridesOf(fields: readonly ParamField[], values: ParamValues): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  for (const f of fields) {
    const raw = values[f.name] ?? '';
    if (f.kind === 'number') {
      if (f.defaultValue === '' || Number(raw) !== Number(f.defaultValue)) out[f.name] = Number(raw);
    } else if (raw !== f.defaultValue) {
      out[f.name] = raw;
    }
  }
  return out;
}

export function runRequest(d: ScenarioDescriptor, fields: readonly ParamField[], values: ParamValues): ScenarioRunRequest | null {
  if (!kindSupport(d.kind).supported) return null;
  if (Object.keys(validateValues(fields, values)).length > 0) return null;
  return { ...overridesOf(fields, values), scenario_id: d.id };
}

// ------------------------------------------------------------------------------------------------ provenance

interface ResultLike {
  readonly carbon_data_is_real?: boolean;
  readonly physics_version?: unknown;
}

/**
 * Provenance input for one scenario preview. `origin` is deliberately NOT set: /api/whatif does not send one, so the
 * badge honestly reads "Unverified source". Scenario id and weather/plant come from the descriptor.
 */
export function scenarioProvenance(d: Pick<ScenarioDescriptor, 'id' | 'weather_source' | 'plant'>, result: ResultLike | null): ProvenanceInput {
  const base: ProvenanceInput = {
    source: { kind: 'preview' },
    scenarioId: d.id,
    weatherSource: present(d.weather_source) ? d.weather_source : null,
    plantKind: present(d.plant) ? d.plant : null,
  };
  if (result === null) return base;
  return {
    ...base,
    physicsVersion: typeof result.physics_version === 'string' && result.physics_version !== '' ? result.physics_version : null,
    inputsFallback: result.carbon_data_is_real === true ? [] : ['carbon'],
  };
}
