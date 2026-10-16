import type { HistoryPoint, Series } from "@/telemetry/history/model";
import { utcIso, type ExportColumn } from "./exportTable";

/** Task 22: telemetry-history export. Event and ingest times are UTC ISO-8601; a missing value exports empty, never 0. */
export function historyExportColumns(series: Pick<Series, "sensorId" | "unit">): readonly ExportColumn<HistoryPoint>[] {
  return [
    { key: "sensor_id", header: "sensor_id", value: () => series.sensorId },
    { key: "event_time_utc", header: "event_time_utc", value: (p) => utcIso(p.iso) },
    { key: "value", header: "value", value: (p) => p.v },
    { key: "unit", header: "unit", value: () => series.unit ?? "" },
    { key: "quality", header: "quality", value: (p) => p.quality ?? "" },
    { key: "origin", header: "origin", value: (p) => p.origin ?? "" },
    { key: "invalid_reason", header: "invalid_reason", value: (p) => p.invalidReason ?? "" },
    { key: "ingested_utc", header: "ingested_utc", value: (p) => utcIso(p.ingestIso) },
  ];
}
