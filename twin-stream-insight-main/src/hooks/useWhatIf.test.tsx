import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/apiError";
import { AuthRequiredError } from "@/authClient";
import type { SimConfig } from "@/hooks/useSimulation";
import { whatIf } from "@/test/whatifFixtures";

const { fetchWhatIf } = vi.hoisted(() => ({ fetchWhatIf: vi.fn() }));
vi.mock("@/api/apiClient", () => ({ fetchWhatIf }));

import { describeInputs, inputsOf, physicsVersionOf, useWhatIf, whatIfFailure, whatIfParams } from "./useWhatIf";

const cfg: SimConfig = { serverUtil: 50, outsideTemp: 20, waterStress: 0.2, chilledWaterSetpoint: 7, coolingMode: "Hybrid", aiOptimizer: true };
const wrapper = () => {
  const client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } });
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

beforeEach(() => fetchWhatIf.mockReset());

describe("useWhatIf requests", () => {
  it("makes NO request while disabled", async () => {
    renderHook(() => useWhatIf(cfg, { enabled: false, debounceMs: 0 }), { wrapper: wrapper() });
    await new Promise((r) => setTimeout(r, 30));
    expect(fetchWhatIf).not.toHaveBeenCalled();
  });

  it("makes exactly one request for one set of inputs once enabled, with the mapped parameters and a signal", async () => {
    fetchWhatIf.mockResolvedValue(whatIf());
    const { result } = renderHook(() => useWhatIf(cfg, { enabled: true, debounceMs: 0 }), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.result.status).toBe("ready"));
    expect(fetchWhatIf).toHaveBeenCalledTimes(1);
    expect(fetchWhatIf.mock.calls[0][0]).toEqual({ utilisation: 0.5, outside_temp: 20, water_stress: 0.2, mode: "hybrid", chilled_water_temp: 7 });
    expect(fetchWhatIf.mock.calls[0][1]).toBeInstanceOf(AbortSignal);
  });

  it("changing the inputs aborts the previous request", async () => {
    const signals: AbortSignal[] = [];
    fetchWhatIf.mockImplementation((_p: unknown, s: AbortSignal) => {
      signals.push(s);
      return new Promise(() => {});
    });
    const { rerender } = renderHook(({ c }: { c: SimConfig }) => useWhatIf(c, { enabled: true, debounceMs: 0 }), {
      wrapper: wrapper(),
      initialProps: { c: cfg },
    });
    await waitFor(() => expect(signals).toHaveLength(1));
    rerender({ c: { ...cfg, outsideTemp: 25 } });
    await waitFor(() => expect(signals).toHaveLength(2));
    await waitFor(() => expect(signals[0].aborted).toBe(true));
    expect(signals[1].aborted).toBe(false);
  });
});

describe("useWhatIf results", () => {
  it("keeps the last good result, labelled refreshFailed, when a later request fails", async () => {
    fetchWhatIf.mockResolvedValueOnce(whatIf({ mean_pue: 1.4 }));
    const { result, rerender } = renderHook(({ c }: { c: SimConfig }) => useWhatIf(c, { enabled: true, debounceMs: 0 }), {
      wrapper: wrapper(),
      initialProps: { c: cfg },
    });
    await waitFor(() => expect(result.current.result.status).toBe("ready"));
    fetchWhatIf.mockRejectedValue(new ApiError({ kind: "network" }));
    rerender({ c: { ...cfg, outsideTemp: 30 } });
    await waitFor(() => {
      const r = result.current.result;
      expect(r.status === "ready" && r.refreshFailed === true).toBe(true);
    });
    const r = result.current.result;
    expect(r.status === "ready" && r.data.mean_pue).toBe(1.4);
  });

  it("an error with no earlier result is an error state carrying only the kind", async () => {
    fetchWhatIf.mockRejectedValue(new ApiError({ kind: "server", status: 500 }));
    const { result } = renderHook(() => useWhatIf(cfg, { enabled: true, debounceMs: 0 }), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.result).toEqual({ status: "error", kind: "server" }), { timeout: 5000 });
  });

  it("a 403 is unauthorized and is not retried", async () => {
    fetchWhatIf.mockRejectedValue(new ApiError({ kind: "forbidden", status: 403 }));
    const { result } = renderHook(() => useWhatIf(cfg, { enabled: true, debounceMs: 0 }), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.result).toEqual({ status: "unauthorized", reason: "forbidden" }));
    expect(fetchWhatIf).toHaveBeenCalledTimes(1);
  });

  it("debounces rapid input changes into one request", async () => {
    fetchWhatIf.mockResolvedValue(whatIf());
    const { rerender } = renderHook(({ c }: { c: SimConfig }) => useWhatIf(c, { enabled: true, debounceMs: 60 }), {
      wrapper: wrapper(),
      initialProps: { c: cfg },
    });
    await waitFor(() => expect(fetchWhatIf).toHaveBeenCalledTimes(1));
    for (const t of [21, 22, 23]) act(() => rerender({ c: { ...cfg, outsideTemp: t } }));
    await waitFor(() => expect(fetchWhatIf).toHaveBeenCalledTimes(2));
    await new Promise((r) => setTimeout(r, 120));
    expect(fetchWhatIf).toHaveBeenCalledTimes(2);
  });
});

describe("pure helpers", () => {
  it("whatIfFailure keeps only kind/reason", () => {
    expect(whatIfFailure(new AuthRequiredError())).toEqual({ status: "unauthorized", reason: "session_ended" });
    expect(whatIfFailure(new Error("secret"))).toEqual({ status: "error", kind: "server" });
  });

  it("whatIfParams scales utilisation from percent and maps the mode", () => {
    expect(whatIfParams(cfg)).toEqual({ utilisation: 0.5, outside_temp: 20, water_stress: 0.2, mode: "hybrid", chilled_water_temp: 7 });
  });

  it("physics_version is shown only when the backend sends one", () => {
    expect(physicsVersionOf(whatIf())).toBeNull();
    expect(physicsVersionOf({ ...whatIf(), physics_version: "p-2" } as ReturnType<typeof whatIf>)).toBe("p-2");
  });

  it("inputsOf prefers the backend echo and falls back to the request", () => {
    const params = whatIfParams(cfg);
    expect(inputsOf(whatIf(), params).mode).toBe("hybrid");
    const echo = { utilisation: 0.9, outside_temp_C: 1, water_stress: 0, mode: "free_air", chilled_water_temp_C: 9 };
    expect(inputsOf(whatIf({ inputs: echo }), params)).toEqual(echo);
    expect(describeInputs(echo)).toContain("mode free_air");
  });
});
