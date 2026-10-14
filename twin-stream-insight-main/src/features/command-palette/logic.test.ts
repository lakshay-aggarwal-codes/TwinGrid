import { describe, expect, it } from "vitest";
import { commandItems, dedupe, groupItems, pageItems, resolveRecents, scenarioItems } from "./items";
import { MAX_RECENTS, RECENTS_KEY, loadRecents, pushRecent } from "./recents";
import { isEditableTarget, isHelpShortcut, isPaletteShortcut } from "./shortcuts";
import { buildSceneCommands } from "./useSceneCommands";
import type { Command } from "../types";

const mem = () => {
  const data = new Map<string, string>();
  return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
};
const key = (key: string, mods: Partial<Pick<KeyboardEvent, "ctrlKey" | "metaKey" | "altKey" | "shiftKey">> = {}, target: EventTarget | null = null) => ({
  key,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  shiftKey: false,
  target,
  ...mods,
});

describe("shortcut rules", () => {
  it("Ctrl+K and Cmd+K open the palette, other modifiers do not", () => {
    expect(isPaletteShortcut(key("k", { ctrlKey: true }))).toBe(true);
    expect(isPaletteShortcut(key("K", { metaKey: true }))).toBe(true);
    expect(isPaletteShortcut(key("k"))).toBe(false);
    expect(isPaletteShortcut(key("k", { ctrlKey: true, shiftKey: true }))).toBe(false);
    expect(isPaletteShortcut(key("k", { ctrlKey: true, altKey: true }))).toBe(false);
  });

  it("? works outside text fields only", () => {
    const input = document.createElement("input");
    const button = document.createElement("button");
    const editable = document.createElement("div");
    editable.setAttribute("contenteditable", "true");
    Object.defineProperty(editable, "isContentEditable", { value: true });
    expect(isHelpShortcut(key("?", { shiftKey: true }, button))).toBe(true);
    expect(isHelpShortcut(key("?", { shiftKey: true }, input))).toBe(false);
    expect(isHelpShortcut(key("?", {}, editable))).toBe(false);
    expect(isHelpShortcut(key("?", { ctrlKey: true }, button))).toBe(false);
    expect(isHelpShortcut(key("/", {}, button))).toBe(false);
    expect(isEditableTarget(null)).toBe(false);
  });
});

describe("recents", () => {
  it("keeps most recent first, no duplicates, capped", () => {
    const s = mem();
    for (const id of ["a", "b", "c", "a", "d", "e", "f"]) pushRecent(id, s);
    expect(loadRecents(s)).toEqual(["f", "e", "d", "a", "c"]);
    expect(loadRecents(s)).toHaveLength(MAX_RECENTS);
  });

  it("survives broken or missing storage", () => {
    const bad = { getItem: () => "{not json", setItem: () => { throw new Error("full"); } };
    expect(loadRecents(bad)).toEqual([]);
    expect(pushRecent("x", bad)).toEqual(["x"]);
    expect(loadRecents(null)).toEqual([]);
    const s = mem();
    s.setItem(RECENTS_KEY, JSON.stringify([1, "ok", "", null]));
    expect(loadRecents(s)).toEqual(["ok"]);
  });
});

describe("items", () => {
  it("pages: core pages plus feature pages, no duplicates, navigate on run", () => {
    const go: string[] = [];
    const items = pageItems((p) => go.push(p), [{ path: "/replay", label: "Replay" }, { path: "/analytics", label: "Analytics again" }]);
    expect(items.map((i) => i.label)).toContain("Go to Replay");
    expect(items.filter((i) => i.id === "page:/analytics")).toHaveLength(1);
    items.find((i) => i.id === "page:/replay")!.run();
    expect(go).toEqual(["/replay"]);
  });

  it("scenarios: one row per scenario, searchable by id and description", () => {
    const opened: string[] = [];
    const [row] = scenarioItems([{ id: "heatwave-1", label: "Heatwave", description: "hot week" }], (id) => opened.push(id));
    expect(row.keywords).toEqual(expect.arrayContaining(["Heatwave", "heatwave-1", "hot week"]));
    row.run();
    expect(opened).toEqual(["heatwave-1"]);
  });

  it("commands: default group, prefixed ids, shortcut hint kept", () => {
    const cmds: Command[] = [{ id: "x.y", label: "Do it", keywords: ["k"], shortcut: "G then X", run: () => undefined }];
    const [row] = commandItems(cmds);
    expect(row).toMatchObject({ id: "cmd:x.y", group: "Actions", shortcut: "G then X" });
    expect(row.keywords).toEqual(["Do it", "k"]);
  });

  it("groups in a fixed order, unknown groups after, alphabetically", () => {
    const mk = (id: string, group: string) => ({ id, label: id, group, keywords: [], run: () => undefined });
    const groups = groupItems([mk("1", "Zeta"), mk("2", "Actions"), mk("3", "Navigate"), mk("4", "Alpha"), mk("5", "Racks")]);
    expect(groups.map((g) => g.group)).toEqual(["Navigate", "Racks", "Actions", "Alpha", "Zeta"]);
  });

  it("dedupe keeps the first; recents drop ids that no longer exist", () => {
    const mk = (id: string) => ({ id, label: id, group: "g", keywords: [], run: () => undefined });
    expect(dedupe([mk("a"), mk("b"), mk("a")]).map((i) => i.id)).toEqual(["a", "b"]);
    expect(resolveRecents(["b", "gone", "a"], [mk("a"), mk("b")]).map((i) => i.id)).toEqual(["b", "a"]);
  });
});

describe("scene commands", () => {
  const layout = {
    zones: [{ zoneId: "zone-1", label: "Zone 1" }],
    racks: [
      { rackId: "zone-1-row-1-rack-1", rowId: "row-1", zoneId: "zone-1", position: [0, 0, 0] },
      { rackId: "zone-1-row-1-rack-2", rowId: "row-1", zoneId: "zone-1", position: [1, 0, 0] },
    ],
  } as never;

  it("one command per zone, rack and (capped, unique) alert, each calling the right action", () => {
    const calls: string[] = [];
    const events = Array.from({ length: 12 }, (_, i) => ({ id: i % 10, message: `m${i}` }));
    const cmds = buildSceneCommands(layout, events, {
      onFocusRack: (id) => calls.push(`rack:${id}`),
      onFocusZone: (id) => calls.push(`zone:${id}`),
      onOpenIncidents: () => calls.push("incidents"),
    });
    expect(cmds.filter((c) => c.group === "Racks")).toHaveLength(2);
    expect(cmds.filter((c) => c.group === "Zones")).toHaveLength(1);
    expect(cmds.filter((c) => c.group === "Alerts")).toHaveLength(8);
    expect(new Set(cmds.map((c) => c.id)).size).toBe(cmds.length);
    cmds.find((c) => c.id === "scene.rack.zone-1-row-1-rack-2")!.run();
    cmds.find((c) => c.id === "scene.zone.zone-1")!.run();
    cmds.find((c) => c.group === "Alerts")!.run();
    expect(calls).toEqual(["rack:zone-1-row-1-rack-2", "zone:zone-1", "incidents"]);
  });
});
