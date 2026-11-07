import { describe, expect, it } from "vitest";
import { FIXTURE_RACKS } from "./fixtures";
import { NOT_REPORTED_TEXT, modeLabel, timeText, toPowerReadout, toReadout } from "./model";
import { rackViewEnvelopeSchema, telemetryRecordSchema, type TelemetryRecord } from "./schemas";

const rackB = FIXTURE_RACKS[1];
const observed = rackB.temperature_sensors[0].record as TelemetryRecord;
const missing = rackB.temperature_sensors[1].record as TelemetryRecord;

describe("fixture matches the schemas", () => {
  it.each(FIXTURE_RACKS.map((r) => [r.source_rack_id, r] as const))("rack %s parses", (_id, view) => {
    expect(() => rackViewEnvelopeSchema.parse(view)).not.toThrow();
  });
  it("is synthetic only", () => {
    for (const v of FIXTURE_RACKS) {
      expect(v.asset_external_id.startsWith("synthetic-example.")).toBe(true);
      for (const s of v.temperature_sensors) if (s.record) expect(s.record.provenance).toBe("synthetic");
    }
  });
  it("rejects an unknown enum instead of guessing", () => {
    expect(telemetryRecordSchema.safeParse({ ...observed, state: "live" }).success).toBe(false);
    expect(telemetryRecordSchema.safeParse({ ...observed, attribution: { ...observed.attribution, split_allowed: true } }).success).toBe(false);
  });
});

describe("toReadout", () => {
  it("shows the record's own canonical text and unit", () => {
    const r = toReadout(observed);
    expect(r.kind).toBe("value");
    expect(r.valueText).toBe("23.47");
    expect(r.unit).toBe("degC");
    expect(r.quality).toBe("flagged");
    expect(r.note).toMatch(/out of range/);
    expect(r.provenanceLabel).toBe("Synthetic example");
  });
  it("never renders a number for a missing cell", () => {
    const r = toReadout(missing);
    expect(r.kind).toBe("missing");
    expect(r.valueText).toBe("No value");
    expect(r.valueText).not.toMatch(/\d/);
    expect(r.note).toMatch(/conflicting values/);
  });
  it("renders Not reported for not_reported and for an absent record", () => {
    const nr = toReadout({ ...missing, state: "not_reported", reason_code: "not_reported_at_time" });
    expect(nr.valueText).toBe(NOT_REPORTED_TEXT);
    expect(toReadout(null, "not_reported_at_time").valueText).toBe(NOT_REPORTED_TEXT);
    expect(toReadout(null).kind).toBe("absent");
  });
});

describe("time and mode", () => {
  it("states the timezone is not established for source text", () => {
    expect(timeText(observed)).toBe("2000-01-01 00:00:01 (source time, timezone not established)");
  });
  it("labels import streams historical, never live", () => {
    expect(modeLabel("import:synthetic-example")).toBe("Recorded dataset (historical), not live");
    expect(toReadout(observed).modeLabel).not.toMatch(/^Live/);
  });
});

describe("power", () => {
  it("group pointer carries no value and names the members", () => {
    const p = toPowerReadout(FIXTURE_RACKS[0].power, "1");
    expect(p.kind).toBe("group_pointer");
    expect(p.readout).toBeNull();
    expect(p.detail).toMatch(/racks 1, 2, 3/);
    expect(p.detail).toMatch(/not split per rack/);
  });
  it("a single-rack port shows its own value", () => {
    const p = toPowerReadout(FIXTURE_RACKS[2].power, "5");
    expect(p.readout?.valueText).toBe("812.5");
    expect(p.readout?.unit).toBe("W");
  });
});
