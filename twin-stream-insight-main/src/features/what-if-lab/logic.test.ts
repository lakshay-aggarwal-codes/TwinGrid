import { describe, expect, it } from "vitest";
import { createDebouncer, type Timers } from "./debounce";
import { DIRECTION_WORD, METRICS, deltaOf, deltasOf, readMetrics, signed, signedPct, thermalMargin, OUTLET_LIMIT_C } from "./metrics";
import { DEFAULT_INPUTS, inputsEqual, normalise, snap, toParams, type LabInputs } from "./model";
import { CSV_HEADER, MAX_NAME, MAX_SAVED, addSaved, csvCell, parseSaved, parseSavedList, removeSaved, serializeSaved, toCsv, type SavedScenario, type Snapshot } from "./saved";
import { CAPTURED_SWEEP, CAPTURED_WHATIF, whatIfWith } from "./testFixtures";
import { axisExtent, axisPos, tornadoRows } from "./tornadoRows";
import { parseLabUrl, withLabParams } from "./url";

const I = (over: Partial<LabInputs> = {}): LabInputs => ({ ...DEFAULT_INPUTS, ...over });

/** A fake clock: `set` records the callback, `advance(ms)` runs what is due. */
function fakeTimers() {
  let now = 0;
  let next = 1;
  const pending = new Map<number, { at: number; fn: () => void }>();
  const timers: Timers = {
    set: (fn, ms) => {
      const id = next++;
      pending.set(id, { at: now + ms, fn });
      return id;
    },
    clear: (h) => void pending.delete(h as number),
  };
  const advance = (ms: number) => {
    now += ms;
    for (const [id, t] of [...pending]) if (t.at <= now) { pending.delete(id); t.fn(); }
  };
  return { timers, advance, count: () => pending.size };
}

describe("inputs", () => {
  it("sends IT load as a fraction without float noise, and holds water stress at 0", () => {
    expect(toParams(I({ itLoadPct: 65 })).utilisation).toBe(0.65);
    expect(toParams(I({ itLoadPct: 7 })).utilisation).toBe(0.07);
    expect(toParams(I({ itLoadPct: 100 })).utilisation).toBe(1);
    const p = toParams(I({ ambientC: -3.5, setpointC: 9.5, mode: "hybrid" }));
    expect(p).toEqual({ utilisation: 0.65, outside_temp: -3.5, water_stress: 0, mode: "hybrid", chilled_water_temp: 9.5 });
  });
  it("the defaults are the backend's documented what-if defaults", () => {
    expect(toParams(DEFAULT_INPUTS)).toEqual({ utilisation: 0.65, outside_temp: 22, water_stress: 0, mode: "auto", chilled_water_temp: 7 });
  });
  it("snaps to range and step, and falls back on NaN", () => {
    expect(snap("itLoadPct", 140, 65)).toBe(100);
    expect(snap("itLoadPct", -5, 65)).toBe(0);
    expect(snap("ambientC", 22.3, 22)).toBe(22.5);
    expect(snap("setpointC", 4, 7)).toBe(5);
    expect(snap("setpointC", NaN, 7)).toBe(7);
  });
  it("normalise repairs only by clamping and an unknown mode falls back to auto", () => {
    expect(normalise({ itLoadPct: 500, mode: "banana" as never })).toEqual(I({ itLoadPct: 100 }));
    expect(inputsEqual(normalise({}), DEFAULT_INPUTS)).toBe(true);
  });
});

describe("delta math", () => {
  it("is scenario minus baseline, with a percent of the baseline", () => {
    const d = deltaOf(200, 250);
    expect(d.delta).toBe(50);
    expect(d.pct).toBe(25);
    expect(d.direction).toBe("up");
    const down = deltaOf(200, 150);
    expect(down.delta).toBe(-50);
    expect(down.pct).toBe(-25);
    expect(down.direction).toBe("down");
  });
  it("uses the absolute baseline for the percent of a negative baseline", () => {
    expect(deltaOf(-10, -5).pct).toBe(50);
  });
  it("has no percent when the baseline is zero, and treats float noise as no change", () => {
    expect(deltaOf(0, 5).pct).toBeNull();
    expect(deltaOf(0, 0).direction).toBe("same");
    const same = deltaOf(1.321550439044979, 1.321550439044979 + 1e-13);
    expect(same.direction).toBe("same");
    expect(same.delta).toBe(0);
    expect(same.pct).toBe(0);
  });
  it("thermal margin is the 45 C outlet ceiling minus the hottest outlet, and negative past it", () => {
    expect(OUTLET_LIMIT_C).toBe(45);
    expect(thermalMargin(36.5)).toBe(8.5);
    expect(thermalMargin(46)).toBe(-1);
    expect(readMetrics(CAPTURED_WHATIF).margin).toBe(45 - CAPTURED_WHATIF.max_outlet_temp_C);
  });
  it("reads the four metrics straight from the response", () => {
    const m = readMetrics(CAPTURED_WHATIF);
    expect(m.energy).toBe(CAPTURED_WHATIF.total_energy_kwh);
    expect(m.pue).toBe(CAPTURED_WHATIF.mean_pue);
    expect(m.carbon).toBe(CAPTURED_WHATIF.total_co2_kg);
  });
  it("deltas for a scenario with more energy and less margin", () => {
    const base = readMetrics(CAPTURED_WHATIF);
    const scen = readMetrics(whatIfWith({ total_energy_kwh: CAPTURED_WHATIF.total_energy_kwh + 1000, max_outlet_temp_C: CAPTURED_WHATIF.max_outlet_temp_C + 2 }));
    const d = deltasOf(base, scen);
    expect(d.energy.delta).toBeCloseTo(1000, 6);
    expect(d.energy.direction).toBe("up");
    expect(d.margin.delta).toBeCloseTo(-2, 9);
    expect(d.margin.direction).toBe("down");
    expect(d.pue.direction).toBe("same");
  });
  it("formats signs with a real minus and never a '+0' or '-0'", () => {
    expect(signed(5.25, 1)).toBe("+5.3");
    expect(signed(-5.25, 1)).toBe("−5.3");
    expect(signed(0, 1)).toBe("0.0");
    expect(signed(0.0001, 1)).toBe("0.0");
    expect(signed(-0.0001, 1)).toBe("0.0");
    expect(signedPct(null)).toMatch(/n\/a/);
    expect(signedPct(12.34)).toBe("+12.3%");
    expect(DIRECTION_WORD.up.word).toBe("higher");
  });
});

describe("shareable URL", () => {
  it("round-trips a scenario and a baseline", () => {
    const scenario = I({ itLoadPct: 80, ambientC: 31.5, setpointC: 9, mode: "closed_loop" });
    const baseline = I({ itLoadPct: 50, mode: "hybrid" });
    const search = withLabParams("", { scenario, baseline });
    expect(parseLabUrl(search)).toEqual({ scenario, baseline });
  });
  it("omits defaults, so the plain page has a clean address", () => {
    expect(withLabParams("", { scenario: DEFAULT_INPUTS, baseline: DEFAULT_INPUTS })).toBe("");
    expect(parseLabUrl("")).toEqual({ scenario: DEFAULT_INPUTS, baseline: DEFAULT_INPUTS });
  });
  it("keeps unrelated parameters and replaces its own", () => {
    const search = withLabParams("?foo=bar&load=10", { scenario: I({ itLoadPct: 90 }), baseline: DEFAULT_INPUTS });
    const p = new URLSearchParams(search);
    expect(p.get("foo")).toBe("bar");
    expect(p.get("load")).toBe("90");
  });
  it("snaps out-of-range values and ignores junk instead of trusting it", () => {
    const { scenario } = parseLabUrl("?load=900&amb=abc&set=2&mode=banana");
    expect(scenario).toEqual(I({ itLoadPct: 100, setpointC: 5 }));
    expect(parseLabUrl("?load=").scenario).toEqual(DEFAULT_INPUTS);
  });
  it("a partial baseline fills the rest from the defaults", () => {
    expect(parseLabUrl("?bmode=hybrid").baseline).toEqual(I({ mode: "hybrid" }));
  });
});

describe("debounce", () => {
  it("fires once, with the last value, after the quiet period", () => {
    const { timers, advance } = fakeTimers();
    const fired: number[] = [];
    const d = createDebouncer<number>(400, (v) => fired.push(v), timers);
    d.push(1);
    advance(200);
    d.push(2);
    advance(200);
    expect(fired).toEqual([]);
    d.push(3);
    advance(399);
    expect(fired).toEqual([]);
    advance(1);
    expect(fired).toEqual([3]);
    expect(d.pending).toBe(false);
  });
  it("a burst of changes schedules one pending timer, never a pile", () => {
    const { timers, count } = fakeTimers();
    const d = createDebouncer<number>(400, () => undefined, timers);
    for (let i = 0; i < 50; i += 1) d.push(i);
    expect(count()).toBe(1);
  });
  it("cancel drops the pending call; flush fires it now", () => {
    const { timers, advance } = fakeTimers();
    const fired: string[] = [];
    const d = createDebouncer<string>(400, (v) => fired.push(v), timers);
    d.push("a");
    d.cancel();
    advance(1000);
    expect(fired).toEqual([]);
    d.push("b");
    d.flush();
    expect(fired).toEqual(["b"]);
    advance(1000);
    expect(fired).toEqual(["b"]);
  });
  it("zero delay fires immediately", () => {
    const fired: number[] = [];
    createDebouncer<number>(0, (v) => fired.push(v)).push(7);
    expect(fired).toEqual([7]);
  });
});

const snapOf = (over: Partial<Snapshot> = {}): Snapshot => ({ inputs: DEFAULT_INPUTS, metrics: readMetrics(CAPTURED_WHATIF), carbonIsReal: false, ...over });

describe("saved scenarios", () => {
  let n = 0;
  const id = () => `id${++n}`;
  it("adds with a unique name, rejects an empty name, and stops at the cap", () => {
    let list: SavedScenario[] = [];
    const a = addSaved(list, " Hot day ", snapOf(), id);
    expect(a.ok).toBe(true);
    if (a.ok === true) list = a.list;
    const b = addSaved(list, "Hot day", snapOf(), id);
    if (b.ok === true) list = b.list;
    expect(list.map((s) => s.name)).toEqual(["Hot day", "Hot day (2)"]);
    expect(addSaved(list, "   ", snapOf(), id)).toEqual({ ok: false, reason: "empty-name" });
    while (list.length < MAX_SAVED) {
      const r = addSaved(list, `s${list.length}`, snapOf(), id);
      if (r.ok === true) list = r.list;
    }
    expect(addSaved(list, "one more", snapOf(), id)).toEqual({ ok: false, reason: "full" });
    expect(list.length).toBe(MAX_SAVED);
  });
  it("truncates a long name", () => {
    const r = addSaved([], "x".repeat(200), snapOf(), id);
    expect(r.ok === true && r.list[0].name.length).toBe(MAX_NAME);
  });
  it("removes by id", () => {
    const r = addSaved([], "a", snapOf(), () => "keep");
    const list = r.ok === true ? r.list : [];
    expect(removeSaved(list, "keep")).toEqual([]);
    expect(removeSaved(list, "other")).toHaveLength(1);
  });
  it("round-trips through storage text, and drops damaged or hand-edited entries instead of repairing them", () => {
    const r = addSaved([], "a", snapOf(), () => "one");
    const list = r.ok === true ? r.list : [];
    expect(parseSavedList(serializeSaved(list))).toEqual(list);
    const bad = JSON.stringify([list[0], { ...list[0], id: "" }, { ...list[0], metrics: { energy: "x" } }, { ...list[0], carbonIsReal: "yes" }, null, 5]);
    expect(parseSavedList(bad)).toHaveLength(1);
    expect(parseSavedList("not json")).toEqual([]);
    expect(parseSavedList("{}")).toEqual([]);
    expect(parseSavedList(null)).toEqual([]);
    expect(parseSaved({})).toBeNull();
  });
  it("clamps stored inputs back into range", () => {
    const r = addSaved([], "a", snapOf(), () => "one");
    const raw = JSON.parse(serializeSaved(r.ok === true ? r.list : []));
    raw[0].inputs.itLoadPct = 9999;
    expect(parseSaved(raw[0])?.inputs.itLoadPct).toBe(100);
  });
});

describe("CSV export", () => {
  it("quotes commas, quotes and newlines, and neutralises spreadsheet formulas in text only", () => {
    expect(csvCell("plain")).toBe("plain");
    expect(csvCell("a,b")).toBe('"a,b"');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell("line\nbreak")).toBe('"line\nbreak"');
    expect(csvCell("=SUM(A1)")).toBe("'=SUM(A1)");
    expect(csvCell("+1")).toBe("'+1");
    expect(csvCell("-1")).toBe("'-1");
    expect(csvCell("@x")).toBe("'@x");
    expect(csvCell(-5.5)).toBe("-5.5");
    expect(csvCell(NaN)).toBe("");
    expect(csvCell(true)).toBe("true");
  });
  it("writes a header, one row per scenario, CRLF line ends, and the estimate label on every row", () => {
    const csv = toCsv([
      { name: "Baseline", kind: "baseline", snap: snapOf() },
      { name: "=evil()", kind: "saved", snap: snapOf({ inputs: I({ itLoadPct: 80 }), carbonIsReal: true }) },
    ]);
    const lines = csv.split("\r\n");
    expect(lines[lines.length - 1]).toBe("");
    expect(lines).toHaveLength(4);
    expect(lines[0]).toBe(CSV_HEADER.join(","));
    expect(lines[1].split(",")[0]).toBe("Baseline");
    expect(lines[2]).toContain("'=evil()");
    for (const l of lines.slice(1, 3)) expect(l.endsWith("model estimate on simulated data")).toBe(true);
    expect(lines[2].split(",")).toHaveLength(CSV_HEADER.length);
    expect(lines[1]).toContain(",false,");
    expect(lines[2]).toContain(",true,");
  });
  it("lists every metric column", () => {
    for (const m of METRICS) expect(CSV_HEADER.some((h) => h.startsWith(m.id))).toBe(true);
  });
});

describe("tornado rows (from a captured real sweep)", () => {
  it("is one row per swept input, sorted by swing, largest first", () => {
    const rows = tornadoRows(CAPTURED_SWEEP, "energy");
    expect(rows.map((r) => r.parameter).sort()).toEqual(["chilled_water_temp", "mode", "outside_temp", "utilisation"]);
    for (let i = 1; i < rows.length; i += 1) expect(rows[i - 1].swing).toBeGreaterThanOrEqual(rows[i].swing);
    expect(rows[0].parameter).toBe("utilisation");
  });
  it("bars are the backend's own deltas, not recomputed", () => {
    const util = tornadoRows(CAPTURED_SWEEP, "energy").find((r) => r.parameter === "utilisation")!;
    const apiUtil = CAPTURED_SWEEP.parameters.find((p) => p.parameter === "utilisation")!;
    expect(util.points.map((p) => p.delta)).toEqual(apiUtil.variants.map((v) => v.deltas.total_energy_kwh));
    expect(util.min).toBeLessThan(0);
    expect(util.max).toBeGreaterThan(0);
  });
  it("is deterministic and stable under ties", () => {
    expect(tornadoRows(CAPTURED_SWEEP, "pue")).toEqual(tornadoRows(CAPTURED_SWEEP, "pue"));
    const tie = { ...CAPTURED_SWEEP, parameters: CAPTURED_SWEEP.parameters.map((p) => ({ ...p, variants: p.variants.map((v) => ({ ...v, deltas: { ...v.deltas, mean_pue: 0 } })) })) };
    expect(tornadoRows(tie, "pue").map((r) => r.parameter)).toEqual(["chilled_water_temp", "mode", "outside_temp", "utilisation"]);
  });
  it("labels points, with the mode alternatives named", () => {
    const mode = tornadoRows(CAPTURED_SWEEP, "energy").find((r) => r.parameter === "mode")!;
    expect(mode.points.map((p) => p.label)).toEqual(["free air", "closed loop", "evaporative", "hybrid"]);
    const util = tornadoRows(CAPTURED_SWEEP, "energy").find((r) => r.parameter === "utilisation")!;
    expect(util.points[0].label).toBe("low 0.55");
  });
  it("the thermal-margin metric reads the backend's margin deltas", () => {
    const util = tornadoRows(CAPTURED_SWEEP, "margin").find((r) => r.parameter === "utilisation")!;
    expect(util.points[0].delta).toBeGreaterThan(0); // less load, more margin
    expect(util.points[1].delta).toBeLessThan(0);
  });
  it("axis maths: symmetric, never zero-width, baseline in the middle", () => {
    const rows = tornadoRows(CAPTURED_SWEEP, "energy");
    const e = axisExtent(rows);
    expect(e).toBeGreaterThan(0);
    expect(axisPos(0, e)).toBe(0.5);
    expect(axisPos(e, e)).toBe(1);
    expect(axisPos(-e, e)).toBe(0);
    expect(axisExtent([])).toBe(1);
  });
  it("the capture is labelled a model estimate, within the cap, and carries the carbon flag", () => {
    expect(CAPTURED_SWEEP.label).toBe("model estimate on simulated data");
    expect(CAPTURED_SWEEP.runs).toBeLessThanOrEqual(CAPTURED_SWEEP.max_runs);
    expect(typeof CAPTURED_SWEEP.carbon_data_is_real).toBe("boolean");
  });
});
