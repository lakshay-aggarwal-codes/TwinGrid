import { afterEach, describe, expect, it } from "vitest";
import { FALLBACK_LAYOUT } from "@/three/facilityLayout";
import { DEFAULT_CAMERA_POSITION, DEFAULT_CAMERA_TARGET } from "@/three/cameraDefaults";
import {
  CAMERA_PRESETS,
  ORBIT_MAX_DISTANCE,
  ORBIT_MIN_DISTANCE,
  distanceBetween,
  isCameraPresetId,
  layoutBounds,
  presetPose,
} from "@/three/cameraPresets";
import { inspectorBridge } from "@/three/inspectorBridge";
import { getModeColor } from "@/three/visualizationModes";
import { frameState } from "@/three/feedTestUtils";
import type { HistoryData } from "@/telemetry/history/useTelemetryHistory";
import type { AlertRecord } from "@/api/apiClient";
import { LAYERS, LAYER_IDS, PUE_BANDS, WUE_BANDS, bandIndex, layerForMode, legendFor, modeAfterToggle } from "./layers";
import { RACK_PARAM, isListKey, listOrder, moveInList, parseRackParam, withRackParam } from "./selectionUrl";
import { buildSparkline, openAlertCount, readingRows } from "./readouts";
import { tooltipPosition } from "./tooltipPosition";

afterEach(() => inspectorBridge.reset());

describe("camera preset maths", () => {
  it("overview is exactly the app's default framing", () => {
    const pose = presetPose("overview", FALLBACK_LAYOUT);
    expect(pose.position).toEqual([...DEFAULT_CAMERA_POSITION]);
    expect(pose.target).toEqual([...DEFAULT_CAMERA_TARGET]);
  });

  it("every preset stays inside the OrbitControls distance limits", () => {
    for (const { id } of CAMERA_PRESETS) {
      const pose = presetPose(id, FALLBACK_LAYOUT);
      const d = distanceBetween(pose.position, pose.target);
      expect(d).toBeGreaterThanOrEqual(ORBIT_MIN_DISTANCE);
      expect(d).toBeLessThanOrEqual(ORBIT_MAX_DISTANCE);
    }
  });

  it("top-down looks straight down from above the middle of the racks", () => {
    const b = layoutBounds(FALLBACK_LAYOUT);
    const pose = presetPose("top-down", FALLBACK_LAYOUT);
    expect(pose.target).toEqual([b.centerX, 0, b.centerZ]);
    expect(pose.position[0]).toBeCloseTo(b.centerX, 6);
    expect(pose.position[2]).toBeCloseTo(b.centerZ, 1);
    expect(pose.position[1]).toBeGreaterThan(b.width / 4);
  });

  it("hot aisle sits at the aisle level of the first zone and looks along it", () => {
    const zone = FALLBACK_LAYOUT.zones[0];
    const pose = presetPose("hot-aisle", FALLBACK_LAYOUT);
    expect(pose.position[2]).toBe(zone.bounds.centerZ);
    expect(pose.target[2]).toBe(zone.bounds.centerZ);
    expect(pose.position[0]).toBeLessThan(zone.bounds.centerX - zone.bounds.width / 2);
    expect(pose.position[1]).toBeLessThan(2);
  });

  it("an empty layout falls back to the overview, and ids are validated", () => {
    expect(presetPose("top-down", { zones: [], racks: [] })).toEqual(presetPose("overview", { zones: [], racks: [] }));
    expect(isCameraPresetId("top-down")).toBe(true);
    expect(isCameraPresetId("sideways")).toBe(false);
  });
});

describe("?rack= and list navigation", () => {
  const first = FALLBACK_LAYOUT.racks[0].rackId;
  it("accepts only ids of the active layout", () => {
    expect(parseRackParam(`?${RACK_PARAM}=${first}`, FALLBACK_LAYOUT)).toBe(first);
    expect(parseRackParam("?rack=nope", FALLBACK_LAYOUT)).toBeNull();
    expect(parseRackParam("?rack=", FALLBACK_LAYOUT)).toBeNull();
    expect(parseRackParam("", FALLBACK_LAYOUT)).toBeNull();
  });

  it("writes and removes the parameter while keeping the others", () => {
    expect(withRackParam("", first)).toBe(`?rack=${first}`);
    expect(withRackParam("?a=1", first)).toBe(`?a=1&rack=${first}`);
    expect(withRackParam(`?a=1&rack=${first}`, null)).toBe("?a=1");
    expect(withRackParam(`?rack=${first}`, null)).toBe("");
    expect(withRackParam("?rack=old", first)).toBe(`?rack=${first}`);
  });

  it("lists racks zone by zone", () => {
    const order = listOrder(FALLBACK_LAYOUT);
    expect(order).toHaveLength(FALLBACK_LAYOUT.racks.length);
    expect(new Set(order).size).toBe(order.length);
  });

  it("moves through the list and stops at both ends", () => {
    const ids = ["a", "b", "c"];
    expect(moveInList(ids, null, "ArrowDown")).toBe("a");
    expect(moveInList(ids, null, "ArrowUp")).toBe("c");
    expect(moveInList(ids, "a", "ArrowDown")).toBe("b");
    expect(moveInList(ids, "c", "ArrowDown")).toBe("c");
    expect(moveInList(ids, "a", "ArrowUp")).toBe("a");
    expect(moveInList(ids, "b", "Home")).toBe("a");
    expect(moveInList(ids, "b", "End")).toBe("c");
    expect(moveInList([], "a", "ArrowDown")).toBeNull();
    expect(moveInList(ids, "gone", "ArrowDown")).toBe("a");
    expect(isListKey("ArrowLeft")).toBe(false);
  });
});

describe("selection state through the bridge", () => {
  it("publishes selection, mode and hover and tells subscribers only when something changed", () => {
    let calls = 0;
    const off = inspectorBridge.subscribe(() => (calls += 1));
    inspectorBridge.publish({ selectedRackId: "r1" });
    inspectorBridge.publish({ selectedRackId: "r1" });
    inspectorBridge.publish({ hoveredRackId: "r2", mode: "thermal" });
    expect(calls).toBe(2);
    expect(inspectorBridge.getState()).toEqual({ selectedRackId: "r1", hoveredRackId: "r2", mode: "thermal" });
    off();
  });

  it("routes widget actions to the page's handlers, and to nothing once they are unregistered", () => {
    const seen: string[] = [];
    const off = inspectorBridge.registerActions({
      selectRack: (id) => seen.push(`select:${id}`),
      setMode: (m) => seen.push(`mode:${m}`),
      flyToPreset: (p) => seen.push(`fly:${p}`),
    });
    inspectorBridge.actions.selectRack("r1");
    inspectorBridge.actions.selectRack(null);
    inspectorBridge.actions.setMode("energy");
    inspectorBridge.actions.flyToPreset("top-down");
    off();
    inspectorBridge.actions.selectRack("r9");
    expect(seen).toEqual(["select:r1", "select:null", "mode:energy", "fly:top-down"]);
    expect(inspectorBridge.hasActions()).toBe(false);
  });
});

describe("layers and legend", () => {
  it("maps the four layers onto the scene's existing modes and toggles them off again", () => {
    expect(LAYER_IDS).toEqual(["thermal", "airflow", "power", "carbon"]);
    expect(LAYERS.map((l) => l.mode)).toEqual(["thermal", "cooling", "energy", "sustainability"]);
    expect(modeAfterToggle("physical", "power")).toBe("energy");
    expect(modeAfterToggle("energy", "power")).toBe("physical");
    expect(modeAfterToggle("energy", "thermal")).toBe("thermal");
    expect(layerForMode("physical")).toBeNull();
    expect(layerForMode("cooling")).toBe("airflow");
  });

  it("legend band edges agree with the colours the scene actually uses", () => {
    const colorAt = (mode: "energy" | "sustainability", key: "pue" | "wue", v: number) => getModeColor(mode, frameState({ [key]: v })).emphasis;
    for (const [mode, key, bands] of [["energy", "pue", PUE_BANDS], ["sustainability", "wue", WUE_BANDS]] as const) {
      const probes = bands.map((b, i) => (b.max === Infinity ? bands[i - 1].max + 0.5 : b.max));
      const colours = probes.map((v) => colorAt(mode, key, v));
      expect(new Set(colours).size).toBe(bands.length);
      probes.forEach((v, i) => expect(bandIndex(bands, v)).toBe(i));
    }
  });

  it("every legend row has a shape glyph, and nothing is marked current without a current reading", () => {
    for (const id of LAYER_IDS) {
      const rows = legendFor(id, null);
      expect(rows.length).toBeGreaterThan(0);
      expect(rows.every((r) => r.glyph.length > 0 && r.text.length > 0)).toBe(true);
      expect(rows.some((r) => r.active)).toBe(false);
    }
    expect(legendFor("power", { pue: 1.3 }).filter((r) => r.active)).toHaveLength(1);
    expect(legendFor("airflow", { coolingMode: "hybrid" }).find((r) => r.active)?.key).toBe("hybrid");
    expect(legendFor("thermal", { inletTempC: 20, outletTempC: 30.04 })[0].text).toContain("30.0 °C");
  });
});

describe("readings, alerts and the sparkline", () => {
  it("formats the facility-wide readings and refuses an out-of-range utilisation", () => {
    const rows = readingRows(frameState({ server_utilisation: 0.5, server_outlet_temp_C: 30.04, it_power_kw: 300 }));
    expect(rows.map((r) => [r.id, r.value])).toEqual([["temperature", "30.0 °C"], ["power", "300.0 kW"], ["utilisation", "50 %"]]);
    expect(readingRows(frameState({ server_utilisation: 7 }))[2].value).toBe("not reported");
  });

  it("counts alerts that are not acknowledged", () => {
    const rows = [{ acknowledged: false }, { acknowledged: true }, { acknowledged: false }] as AlertRecord[];
    expect(openAlertCount(rows)).toBe(2);
    expect(openAlertCount([])).toBe(0);
  });

  const item = (ts: string, value: number, quality = "ok") => ({ ts_event: ts, value, origin: "simulated", quality });
  const data = (items: HistoryData["items"], gaps: HistoryData["gaps"] = []): HistoryData => ({
    sensorId: "fac1.server_outlet_temp_C",
    unit: "°C",
    samplingIntervalS: 60,
    thresholdS: 120,
    items,
    gaps,
    gapsTruncated: false,
    moreAvailable: false,
    pagesLoaded: 1,
  });

  it("draws good samples in order inside the box and ends the run at a reported gap", () => {
    const items = [
      item("2026-10-14T10:00:00Z", 20),
      item("2026-10-14T10:01:00Z", 30),
      item("2026-10-14T10:10:00Z", 25),
      item("2026-10-14T10:11:00Z", 22, "invalid"),
    ];
    const gaps = [{ start: "2026-10-14T10:01:00Z", end: "2026-10-14T10:10:00Z", duration_s: 540 }];
    const s = buildSparkline(data(items, gaps), 240, 48)!;
    expect(s.paths).toHaveLength(2);
    expect(s.goodCount).toBe(3);
    expect(s.excluded).toBe(1);
    expect([s.min, s.max, s.lastValue]).toEqual([20, 30, 25]);
    for (const d of s.paths) for (const n of d.match(/-?\d+(\.\d+)?/g)!.map(Number)) expect(n).toBeGreaterThanOrEqual(0);
    expect(s.paths[0].startsWith("M")).toBe(true);
  });

  it("returns null with no good sample and a mid-height line for a flat series", () => {
    expect(buildSparkline(data([]), 240, 48)).toBeNull();
    expect(buildSparkline(data([item("2026-10-14T10:00:00Z", 5, "invalid")]), 240, 48)).toBeNull();
    const flat = buildSparkline(data([item("2026-10-14T10:00:00Z", 5), item("2026-10-14T10:01:00Z", 5)]), 240, 48)!;
    expect(flat.paths[0]).toContain(" 24");
  });
});

describe("tooltip position", () => {
  const box = { width: 100, height: 40 };
  const vp = { width: 800, height: 600 };
  it("sits below-right of the pointer and stays inside the viewport", () => {
    expect(tooltipPosition(100, 100, box, vp)).toEqual({ left: 114, top: 114 });
    expect(tooltipPosition(790, 100, box, vp).left).toBe(800 - 100 - 8);
    expect(tooltipPosition(100, 590, box, vp).top).toBe(590 - 14 - 40);
  });
});
