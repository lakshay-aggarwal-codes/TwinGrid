import { useRef, useState } from "react";
import { Download } from "lucide-react";
import { downloadExport, exportFilename, toCsv, toJson, type ExportColumn } from "./exportTable";

const BTN =
  "inline-flex items-center gap-1 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export interface ExportButtonsProps<T> {
  /** Human name used in labels and the file name, e.g. "alerts". */
  readonly label: string;
  readonly columns: readonly ExportColumn<T>[];
  readonly rows: readonly T[];
  /** Written into the JSON file; "simulated" for everything the simulator produced. */
  readonly origin?: string;
  readonly notes?: readonly string[];
  readonly formats?: readonly ("csv" | "json")[];
  /** Test seam. */
  readonly now?: () => Date;
}

/** Export CSV / Export JSON for one table. Disabled (with a reason) when there is nothing to export; announces the result politely. */
export function ExportButtons<T>({ label, columns, rows, origin = "simulated", notes, formats = ["csv", "json"], now = () => new Date() }: ExportButtonsProps<T>) {
  const [message, setMessage] = useState("");
  const empty = rows.length === 0;
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const run = (kind: "csv" | "json") => {
    const at = now();
    const text = kind === "csv" ? toCsv(columns, rows) : toJson({ table: label, origin, notes, exportedAt: at }, columns, rows);
    downloadExport(exportFilename(label, kind, at), text, kind === "csv" ? "text/csv" : "application/json");
    setMessage(`${kind.toUpperCase()} downloaded: ${rows.length} row${rows.length === 1 ? "" : "s"}.`);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setMessage(""), 4000);
  };

  return (
    <span className="inline-flex flex-wrap items-center gap-2" data-testid={`export-${label}`}>
      {formats.map((k) => (
        <button
          key={k}
          type="button"
          className={BTN}
          disabled={empty}
          title={empty ? `Nothing to export: there are no ${label} rows.` : undefined}
          aria-label={`Export ${label} as ${k.toUpperCase()}`}
          onClick={() => run(k)}
        >
          <Download className="h-3.5 w-3.5" aria-hidden="true" /> Export {k.toUpperCase()}
        </button>
      ))}
      <span role="status" aria-live="polite" className="sr-only">{message}</span>
    </span>
  );
}
