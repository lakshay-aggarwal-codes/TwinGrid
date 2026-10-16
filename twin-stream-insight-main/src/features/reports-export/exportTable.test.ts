import { describe, expect, it } from "vitest";
import { csvCell, exportFilename, toCsv, toJson, utcIso, type ExportColumn } from "./exportTable";

describe("csvCell", () => {
  it("quotes commas, quotes, CR and LF and doubles embedded quotes", () => {
    expect(csvCell("a,b")).toBe('"a,b"');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell("line1\nline2")).toBe('"line1\nline2"');
    expect(csvCell("plain")).toBe("plain");
  });
  it("neutralises spreadsheet formulas in text but never touches numbers", () => {
    expect(csvCell("=SUM(A1:A9)")).toBe("'=SUM(A1:A9)");
    expect(csvCell("+1")).toBe("'+1");
    expect(csvCell("-2")).toBe("'-2");
    expect(csvCell("@cmd")).toBe("'@cmd");
    expect(csvCell("=1,2")).toBe('"\'=1,2"');
    expect(csvCell(-2)).toBe("-2");
  });
  it("renders null, undefined and non-finite numbers as empty, booleans as words", () => {
    expect(csvCell(null)).toBe("");
    expect(csvCell(undefined)).toBe("");
    expect(csvCell(Number.NaN)).toBe("");
    expect(csvCell(Number.POSITIVE_INFINITY)).toBe("");
    expect(csvCell(true)).toBe("true");
  });
});

describe("toCsv", () => {
  const cols: ExportColumn<{ a: string; n: number | null }>[] = [
    { key: "a", header: "a", value: (r) => r.a },
    { key: "n", header: "n,units", value: (r) => r.n },
  ];
  it("writes a header, CRLF line ends and a trailing CRLF; escapes the header too", () => {
    expect(toCsv(cols, [{ a: "x,y", n: 1.5 }, { a: "=2", n: null }])).toBe('a,"n,units"\r\n"x,y",1.5\r\n\'=2,\r\n');
  });
  it("an empty table is just the header", () => {
    expect(toCsv(cols, [])).toBe('a,"n,units"\r\n');
  });
});

describe("utcIso", () => {
  it("keeps UTC and ends in Z", () => {
    expect(utcIso("2026-10-16T03:15:00Z")).toBe("2026-10-16T03:15:00.000Z");
    expect(utcIso(new Date(Date.UTC(2026, 9, 16, 3, 15)))).toBe("2026-10-16T03:15:00.000Z");
  });
  it("converts an offset to UTC", () => {
    expect(utcIso("2026-10-16T08:45:00+05:30")).toBe("2026-10-16T03:15:00.000Z");
  });
  it("reads a zone-less date-time as UTC, independent of the machine time zone", () => {
    expect(utcIso("2026-10-16T03:15:00")).toBe("2026-10-16T03:15:00.000Z");
    expect(utcIso("2026-10-16 03:15:00")).toBe("2026-10-16T03:15:00.000Z");
  });
  it("returns empty for missing or unreadable input", () => {
    expect(utcIso(null)).toBe("");
    expect(utcIso(undefined)).toBe("");
    expect(utcIso("")).toBe("");
    expect(utcIso("not a date")).toBe("");
  });
});

describe("toJson / exportFilename", () => {
  const cols: ExportColumn<{ a: string }>[] = [{ key: "a", header: "a", value: (r) => r.a }];
  const at = new Date(Date.UTC(2026, 9, 16, 3, 15, 7));
  it("carries table, origin, UTC export time, notes and row count", () => {
    const j = JSON.parse(toJson({ table: "alerts", origin: "simulated", notes: ["n1"], exportedAt: at }, cols, [{ a: "x" }]));
    expect(j).toEqual({ table: "alerts", origin: "simulated", exported_at_utc: "2026-10-16T03:15:07.000Z", notes: ["n1"], row_count: 1, rows: [{ a: "x" }] });
  });
  it("builds a path-safe UTC file name", () => {
    expect(exportFilename("Telemetry history", "csv", at)).toBe("twingrid-telemetry-history-20261016T031507Z.csv");
    expect(exportFilename("../../etc", "json", at)).toBe("twingrid-etc-20261016T031507Z.json");
    expect(exportFilename("???", "csv", at)).toBe("twingrid-export-20261016T031507Z.csv");
  });
});
