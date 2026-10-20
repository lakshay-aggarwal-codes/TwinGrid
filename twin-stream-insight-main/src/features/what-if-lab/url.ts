/**
 * Task 15: shareable URL for the lab. PURE. `?load=<pct>&amb=<°C>&set=<°C>&mode=<id>` is the scenario; `bload/bamb/bset/bmode`
 * is the baseline when it differs from the default. Anything unreadable is ignored (the default is used), never trusted:
 * values are snapped to the control ranges (the set-point range is the server's, passed in), and the backend validates
 * every request again.
 */
import { defaultInputs, inputsEqual, isMode, normalise, type LabInputs, type SetpointRange } from "./model";

const KEYS = { itLoadPct: "load", ambientC: "amb", setpointC: "set", mode: "mode" } as const;
const BASE_KEYS = { itLoadPct: "bload", ambientC: "bamb", setpointC: "bset", mode: "bmode" } as const;

function read(p: URLSearchParams, keys: typeof KEYS | typeof BASE_KEYS, range: SetpointRange): { inputs: LabInputs; any: boolean } {
  const num = (k: string): number | undefined => {
    const raw = p.get(k);
    if (raw === null || raw.trim() === "") return undefined;
    const n = Number(raw);
    return Number.isFinite(n) ? n : undefined;
  };
  const mode = p.get(keys.mode);
  const given = { itLoadPct: num(keys.itLoadPct), ambientC: num(keys.ambientC), setpointC: num(keys.setpointC), mode: isMode(mode) ? mode : undefined };
  return {
    inputs: normalise(given, range),
    any: given.itLoadPct !== undefined || given.ambientC !== undefined || given.setpointC !== undefined || given.mode !== undefined,
  };
}

export interface LabUrl {
  readonly scenario: LabInputs;
  readonly baseline: LabInputs;
}

export function parseLabUrl(search: string, range: SetpointRange): LabUrl {
  const p = new URLSearchParams(search);
  const s = read(p, KEYS, range);
  const b = read(p, BASE_KEYS, range);
  return { scenario: s.inputs, baseline: b.any ? b.inputs : defaultInputs(range) };
}

/** `search` with the lab parameters set (defaults are omitted); every other parameter is kept. Returns "" or "?...". */
export function withLabParams(search: string, v: LabUrl, range: SetpointRange): string {
  const p = new URLSearchParams(search);
  for (const k of [...Object.values(KEYS), ...Object.values(BASE_KEYS)]) p.delete(k);
  const put = (keys: typeof KEYS | typeof BASE_KEYS, i: LabInputs) => {
    p.set(keys.itLoadPct, String(i.itLoadPct));
    p.set(keys.ambientC, String(i.ambientC));
    p.set(keys.setpointC, String(i.setpointC));
    p.set(keys.mode, i.mode);
  };
  const defaults = defaultInputs(range);
  if (!inputsEqual(v.scenario, defaults)) put(KEYS, v.scenario);
  if (!inputsEqual(v.baseline, defaults)) put(BASE_KEYS, v.baseline);
  const text = p.toString();
  return text === "" ? "" : `?${text}`;
}
