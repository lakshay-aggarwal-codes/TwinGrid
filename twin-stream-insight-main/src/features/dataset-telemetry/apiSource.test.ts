import { describe, expect, it, vi } from "vitest";
import { createApiSource, DatasetApiError } from "./apiSource";
import { FIXTURE_RACKS } from "./fixtures";

const CFG = { datasetId: "synthetic-example", facilityId: "synthetic-example-facility" };
const STREAM = "import:synthetic-example";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const datasetRecord = {
  contract_version: "1.1.0",
  kind: "dataset_record",
  facility_id: CFG.facilityId,
  dataset_id: CFG.datasetId,
  stream_id: STREAM,
  attribution_text: "Synthetic attribution.",
  modifications_statement: "Synthetic modifications.",
  window: { first_source_text: "2000-01-01 00:00:00", last_source_text: "2000-01-02 00:00:00" },
  racks: [
    { source_rack_id: "1", asset_external_id: "synthetic-example.rack.a", name: "Rack 1" },
    { source_rack_id: "2", asset_external_id: "synthetic-example.rack.b", name: "Rack 2" },
  ],
};

function make(fetchImpl: typeof fetch, extra: Parameters<typeof createApiSource>[1] = {}) {
  return createApiSource(CFG, { baseUrl: "http://api.test", fetchImpl, getToken: async () => "tok", forceRefresh: async () => "fresh", ...extra });
}

describe("createApiSource", () => {
  it("sends facility_id and the import stream on every request, never live, with the bearer token", async () => {
    const f = vi.fn(async () => json(datasetRecord));
    await make(f as unknown as typeof fetch).loadDataset();
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    const u = new URL(url);
    expect(u.pathname).toBe("/api/datasets/synthetic-example");
    expect(u.searchParams.get("facility_id")).toBe(CFG.facilityId);
    expect(u.searchParams.get("stream")).toBe(STREAM);
    expect(url).not.toMatch(/stream=live/);
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
  });

  it("loads the rack list, attribution, modification statement and window", async () => {
    const info = await make((async () => json(datasetRecord)) as unknown as typeof fetch).loadDataset();
    expect(info.rackIds).toEqual(["1", "2"]);
    expect(info.attributionText).toBe("Synthetic attribution.");
    expect(info.modificationsStatement).toBe("Synthetic modifications.");
    expect(info.window).toEqual({ first: "2000-01-01 00:00:00", last: "2000-01-02 00:00:00" });
  });

  it("requests one rack by its own id and returns that rack's view", async () => {
    const f = vi.fn(async (url: string) => json(FIXTURE_RACKS.find((r) => url.includes(`/racks/${r.source_rack_id}?`))));
    const view = await make(f as unknown as typeof fetch).getRackView("2");
    expect(new URL(f.mock.calls[0][0] as string).pathname).toBe("/api/datasets/synthetic-example/racks/2");
    expect(view.kind).toBe("rack_view");
    if (view.kind === "rack_view") expect(view.source_rack_id).toBe("2");
  });

  it("refuses a response for a different rack, dataset or stream", async () => {
    const wrongRack = vi.fn(async () => json(FIXTURE_RACKS[0]));
    await expect(make(wrongRack as unknown as typeof fetch).getRackView("2")).rejects.toThrow(/different rack/);
    const wrongStream = vi.fn(async () => json({ ...FIXTURE_RACKS[0], stream_id: "import:other" }));
    await expect(make(wrongStream as unknown as typeof fetch).getRackView("1")).rejects.toThrow(/different dataset or stream/);
  });

  it("accepts the backend's real power shapes: a record-only port and a not_available reason", async () => {
    const e = FIXTURE_RACKS[2];
    const port = vi.fn(async () => json(e));
    const view = await make(port as unknown as typeof fetch).getRackView("5");
    expect(view.kind === "rack_view" && view.power.kind).toBe("single_rack_port");
    const na = vi.fn(async () => json({ ...e, power: { kind: "not_available", reason: "no_record_at_that_second" } }));
    const v2 = await make(na as unknown as typeof fetch).getRackView("5");
    expect(v2.kind === "rack_view" && v2.power.kind).toBe("not_available");
  });

  it("returns a contract error envelope instead of throwing", async () => {
    const env = { contract_version: "1.1.0", kind: "error", status: 404, code: "unknown_entity", message: "unknown source_rack_id for this dataset", facility_id: CFG.facilityId, dataset_id: CFG.datasetId, stream_id: STREAM };
    const res = await make((async () => json(env, 404)) as unknown as typeof fetch).getRackView("9");
    expect(res.kind).toBe("error");
  });

  it("maps framework failures to plain messages (demo refused, unconfigured, signed out)", async () => {
    await expect(make((async () => json({ detail: "x" }, 403)) as unknown as typeof fetch).loadDataset()).rejects.toThrow(/demo sessions are refused/);
    await expect(make((async () => json({ detail: "x" }, 404)) as unknown as typeof fetch).loadDataset()).rejects.toThrow(/No dataset is configured/);
    await expect(make((async () => json({}, 401)) as unknown as typeof fetch).loadDataset()).rejects.toThrow(/Sign in again/);
  });

  it("retries once with a refreshed token after a 401", async () => {
    const f = vi.fn().mockResolvedValueOnce(json({}, 401)).mockResolvedValueOnce(json(datasetRecord));
    await make(f as unknown as typeof fetch).loadDataset();
    expect(f).toHaveBeenCalledTimes(2);
    expect(((f.mock.calls[1] as unknown as [string, RequestInit])[1].headers as Record<string, string>).Authorization).toBe("Bearer fresh");
  });

  it("rejects a payload that breaks the contract and reports network failure plainly", async () => {
    await expect(make((async () => json({ ...datasetRecord, kind: "sensor_list" })) as unknown as typeof fetch).loadDataset()).rejects.toThrow();
    const down = (async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    await expect(make(down).loadDataset()).rejects.toBeInstanceOf(DatasetApiError);
  });
});
