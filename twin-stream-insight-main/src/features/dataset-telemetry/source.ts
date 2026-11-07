/**
 * Task 17: the readout's data source. Two implementations of one interface: a synthetic contract fixture, and the Task 16
 * API (see apiSource.ts). Every API call passes facility_id and stream = import:<dataset_id> explicitly; nothing here
 * ever requests stream=live.
 */
import { FIXTURE_RACKS } from "./fixtures";
import { errorEnvelopeSchema, rackViewEnvelopeSchema, type ErrorEnvelope, type RackViewEnvelope } from "./schemas";

export interface DatasetInfo {
  rackIds: string[];
  /** Licence attribution and modification statement supplied by the dataset route (CC BY 4.0); null for the fixture. */
  attributionText: string | null;
  modificationsStatement: string | null;
  /** Recorded window in source time text; null when unknown. */
  window: { first: string | null; last: string | null } | null;
}

export interface DatasetTelemetrySource {
  /** "fixture" = synthetic contract mock, shown with a banner. "api" = the Task 16 routes. */
  readonly kind: "fixture" | "api";
  readonly label: string;
  loadDataset(signal?: AbortSignal): Promise<DatasetInfo>;
  getRackView(sourceRackId: string, signal?: AbortSignal): Promise<RackViewEnvelope | ErrorEnvelope>;
}

export const fixtureSource: DatasetTelemetrySource = {
  kind: "fixture",
  label: "Contract fixture (synthetic, not dataset data)",
  async loadDataset() {
    return { rackIds: FIXTURE_RACKS.map((r) => r.source_rack_id), attributionText: null, modificationsStatement: null, window: null };
  },
  async getRackView(sourceRackId) {
    const found = FIXTURE_RACKS.find((r) => r.source_rack_id === sourceRackId);
    if (!found) {
      return { contract_version: "1.1.0", kind: "error", status: 404, code: "unknown_entity", message: `Unknown rack ${sourceRackId}` };
    }
    return found;
  },
};

/** Validates any rack payload a real source returns; throws on a shape the contract does not allow. */
export function parseRackViewResponse(body: unknown): RackViewEnvelope | ErrorEnvelope {
  if (typeof body === "object" && body !== null && (body as { kind?: unknown }).kind === "error") return errorEnvelopeSchema.parse(body);
  return rackViewEnvelopeSchema.parse(body);
}
