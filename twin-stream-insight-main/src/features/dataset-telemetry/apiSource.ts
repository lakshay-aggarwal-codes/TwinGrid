/**
 * Task 17: client for the Task 16 dataset routes (api/plugins/dataset_telemetry.py):
 *   GET /api/datasets/{dataset_id}                        dataset record (rack list, attribution, window)
 *   GET /api/datasets/{dataset_id}/racks/{source_rack_id} rack_view
 * facility_id and stream = import:<dataset_id> are sent on every request. The dataset id and facility id come from
 * VITE_DATASET_ID and VITE_DATASET_FACILITY_ID; neither is guessed or defaulted.
 */
import { forceRefresh as defaultForceRefresh, getToken as defaultGetToken } from "@/authClient";
import { API_BASE_URL } from "@/config";
import { datasetRecordSchema, errorEnvelopeSchema, rackViewEnvelopeSchema, type ErrorEnvelope, type RackViewEnvelope } from "./schemas";
import type { DatasetInfo, DatasetTelemetrySource } from "./source";

export class DatasetApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "DatasetApiError";
  }
}

export interface ApiSourceDeps {
  baseUrl: string;
  fetchImpl: typeof fetch;
  getToken: () => Promise<string>;
  forceRefresh: () => Promise<string>;
}

export interface ApiSourceConfig {
  datasetId: string;
  facilityId: string;
}

function friendly(status: number): string {
  if (status === 401) return "Sign in again to view dataset telemetry.";
  if (status === 403) return "Dataset telemetry is not available to this session (demo sessions are refused).";
  if (status === 404) return "No dataset is configured on this server.";
  if (status === 429) return "Too many requests. Try again shortly.";
  return `The dataset request failed (HTTP ${status}).`;
}

export function createApiSource(cfg: ApiSourceConfig, overrides: Partial<ApiSourceDeps> = {}): DatasetTelemetrySource {
  const deps: ApiSourceDeps = {
    baseUrl: API_BASE_URL,
    fetchImpl: (input, init) => fetch(input, init),
    getToken: defaultGetToken,
    forceRefresh: defaultForceRefresh,
    ...overrides,
  };
  const stream = `import:${cfg.datasetId}`;
  const base = `/api/datasets/${encodeURIComponent(cfg.datasetId)}`;

  const urlFor = (path: string): string => {
    const u = new URL(path, deps.baseUrl);
    u.searchParams.set("facility_id", cfg.facilityId);
    u.searchParams.set("stream", stream);
    return u.toString();
  };

  async function call(url: string, token: string, signal?: AbortSignal): Promise<Response> {
    try {
      return await deps.fetchImpl(url, { signal, headers: { Authorization: `Bearer ${token}` } });
    } catch (e) {
      if (e instanceof Error && e.name === "AbortError") throw e;
      throw new DatasetApiError("Could not reach the server.");
    }
  }

  /** Returns the parsed JSON body of a 2xx, or of a non-2xx that is a contract error envelope; other failures throw. */
  async function request(path: string, signal?: AbortSignal): Promise<unknown> {
    const url = urlFor(path);
    let res = await call(url, await deps.getToken(), signal);
    if (res.status === 401) res = await call(url, await deps.forceRefresh(), signal);
    const text = await res.text();
    let body: unknown = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = null;
    }
    const isEnvelope = typeof body === "object" && body !== null && (body as { kind?: unknown }).kind === "error";
    if (!res.ok && !isEnvelope) throw new DatasetApiError(friendly(res.status), res.status);
    if (res.ok && body === null) throw new DatasetApiError("The server returned an empty response.", res.status);
    return body;
  }

  return {
    kind: "api",
    label: `Dataset ${cfg.datasetId} (recorded, historical)`,
    async loadDataset(signal) {
      const body = await request(base, signal);
      if (typeof body === "object" && body !== null && (body as { kind?: unknown }).kind === "error") {
        throw new DatasetApiError(errorEnvelopeSchema.parse(body).message);
      }
      const rec = datasetRecordSchema.parse(body);
      if (rec.dataset_id !== cfg.datasetId || rec.stream_id !== stream) throw new DatasetApiError("The server answered for a different dataset or stream.");
      const info: DatasetInfo = {
        rackIds: rec.racks.map((r) => r.source_rack_id),
        attributionText: rec.attribution_text,
        modificationsStatement: rec.modifications_statement,
        window: { first: rec.window.first_source_text, last: rec.window.last_source_text },
      };
      return info;
    },
    async getRackView(sourceRackId, signal): Promise<RackViewEnvelope | ErrorEnvelope> {
      const body = await request(`${base}/racks/${encodeURIComponent(sourceRackId)}`, signal);
      if (typeof body === "object" && body !== null && (body as { kind?: unknown }).kind === "error") return errorEnvelopeSchema.parse(body);
      const view = rackViewEnvelopeSchema.parse(body);
      // A response for another rack must never be shown under the selected one.
      if (view.source_rack_id !== sourceRackId) throw new DatasetApiError("The server answered for a different rack.");
      if (view.dataset_id !== cfg.datasetId || view.stream_id !== stream) throw new DatasetApiError("The server answered for a different dataset or stream.");
      return view;
    },
  };
}

/** The real source when both settings exist, else null (the page then uses the synthetic fixture). */
export function sourceFromEnv(env: { VITE_DATASET_ID?: string; VITE_DATASET_FACILITY_ID?: string }): DatasetTelemetrySource | null {
  const datasetId = env.VITE_DATASET_ID?.trim();
  const facilityId = env.VITE_DATASET_FACILITY_ID?.trim();
  if (!datasetId || !facilityId || !API_BASE_URL) return null;
  return createApiSource({ datasetId, facilityId });
}
