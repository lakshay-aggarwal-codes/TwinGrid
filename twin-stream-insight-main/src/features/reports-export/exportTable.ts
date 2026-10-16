/**
 * Task 22: one export path for every table (runs, telemetry history, alerts, what-if results, the printable report).
 * PURE except `downloadExport`. Rules enforced here, once:
 *  - CSV cells that a spreadsheet would run as a formula (start with = + - @ tab CR) are prefixed with an apostrophe (text only; numbers never);
 *  - every timestamp column goes through `utcIso`, so exported times are always UTC ISO-8601 ending in "Z";
 *  - the JSON export carries the table label, the UTC export time and the origin label so a file kept apart from the app still says what it is.
 */
export type Cell = string | number | boolean | null | undefined;

export interface ExportColumn<T> {
  /** Machine key: the JSON property name. */
  readonly key: string;
  /** CSV header text. */
  readonly header: string;
  readonly value: (row: T) => Cell;
}

/** Spreadsheet-safe, RFC 4180 style quoting. Non-finite numbers export as an empty cell, never "NaN". */
export function csvCell(v: Cell): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "";
  if (typeof v === "boolean") return v ? "true" : "false";
  const safe = /^[=+\-@\t\r]/.test(v) ? `'${v}` : v;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

/** Header line plus one line per row, CRLF line ends, trailing CRLF. */
export function toCsv<T>(columns: readonly ExportColumn<T>[], rows: readonly T[]): string {
  const lines = [columns.map((c) => csvCell(c.header)).join(",")];
  for (const r of rows) lines.push(columns.map((c) => csvCell(c.value(r))).join(","));
  return `${lines.join("\r\n")}\r\n`;
}

/**
 * A timestamp as UTC ISO-8601 with milliseconds and a trailing "Z", or "" when it is missing or unparseable.
 * A string WITHOUT a zone designator is read as UTC (the backend contract is UTC only); a string with an offset is converted.
 */
export function utcIso(input: Date | string | number | null | undefined): string {
  if (input === null || input === undefined || input === "") return "";
  let d: Date;
  if (typeof input === "string") {
    const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(input.trim());
    const dateTimeLike = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(input.trim());
    d = new Date(!hasZone && dateTimeLike ? `${input.trim().replace(" ", "T")}Z` : input);
  } else {
    d = new Date(input);
  }
  return Number.isNaN(d.getTime()) ? "" : d.toISOString();
}

export interface JsonMeta {
  /** What the table is, e.g. "alerts". */
  readonly table: string;
  /** Where the values come from, e.g. "simulated". Never omitted from the file. */
  readonly origin: string;
  /** Extra plain-text caveats printed in the file (e.g. the carbon fallback label). */
  readonly notes?: readonly string[];
  readonly exportedAt: Date;
}

export function toJson<T>(meta: JsonMeta, columns: readonly ExportColumn<T>[], rows: readonly T[]): string {
  const out = {
    table: meta.table,
    origin: meta.origin,
    exported_at_utc: utcIso(meta.exportedAt),
    notes: meta.notes ?? [],
    row_count: rows.length,
    rows: rows.map((r) => Object.fromEntries(columns.map((c) => [c.key, c.value(r) ?? null]))),
  };
  return `${JSON.stringify(out, null, 2)}\n`;
}

/** `twingrid-<base>-20261016T031500Z.csv`. The base is reduced to [a-z0-9-] so it can never form a path. */
export function exportFilename(base: string, ext: "csv" | "json", at: Date): string {
  const safe = base.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "export";
  const stamp = utcIso(at).replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  return `twingrid-${safe}-${stamp}.${ext}`;
}

/** Browser only. Hands a text file to the browser as a download. */
export function downloadExport(filename: string, text: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
