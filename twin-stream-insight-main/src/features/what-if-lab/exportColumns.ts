import type { ExportColumn } from "../reports-export/exportTable";
import { ESTIMATE_LABEL, METRICS, type MetricId } from "./metrics";
import type { CsvRow } from "./saved";

/** Task 22: what-if results for the shared JSON export (the existing CSV button keeps its own header in `saved.ts`). */
export const WHATIF_EXPORT_COLUMNS: readonly ExportColumn<CsvRow>[] = [
  { key: "scenario", header: "scenario", value: (r) => r.name },
  { key: "kind", header: "kind", value: (r) => r.kind },
  { key: "it_load_pct", header: "it_load_pct", value: (r) => r.snap.inputs.itLoadPct },
  { key: "ambient_C", header: "ambient_C", value: (r) => r.snap.inputs.ambientC },
  { key: "chilled_water_setpoint_C", header: "chilled_water_setpoint_C", value: (r) => r.snap.inputs.setpointC },
  { key: "cooling_mode", header: "cooling_mode", value: (r) => r.snap.inputs.mode },
  ...METRICS.map((m) => ({
    key: m.id,
    header: m.id,
    value: (r: CsvRow) => r.snap.metrics[m.id as MetricId],
  })),
  { key: "carbon_data_is_real", header: "carbon_data_is_real", value: (r) => r.snap.carbonIsReal },
  { key: "label", header: "label", value: () => ESTIMATE_LABEL },
];
