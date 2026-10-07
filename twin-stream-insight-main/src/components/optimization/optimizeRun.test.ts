import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/apiError";
import { AuthRequiredError } from "@/authClient";
import type { OptimizeResponse } from "@/api/apiClient";
import { INITIAL_RUN, failureOf, isModelUnavailable, optimizeReducer, optionalFlag, optionalText, type OptimizeRun } from "./optimizeRun";

const result = { results: [], summary: { mean_pue: 1, mean_wue: 1, mean_cooling_power_kw: 1, total_water_consumed_L: 1, total_reward: 1, safety_violations: 0 } } as OptimizeResponse;

describe("optimizeReducer", () => {
  it("walks idle -> confirming -> submitting -> completed", () => {
    let s: OptimizeRun = INITIAL_RUN;
    s = optimizeReducer(s, { type: "request" });
    expect(s.status).toBe("confirming");
    s = optimizeReducer(s, { type: "submit" });
    expect(s.status).toBe("submitting");
    s = optimizeReducer(s, { type: "succeeded", result });
    expect(s).toEqual({ status: "completed", result });
  });

  it("cancel returns to idle only from confirming", () => {
    expect(optimizeReducer({ status: "confirming" }, { type: "cancel" })).toEqual({ status: "idle" });
    expect(optimizeReducer({ status: "submitting" }, { type: "cancel" })).toEqual({ status: "submitting" });
  });

  it("cannot submit without confirming (no double submit)", () => {
    expect(optimizeReducer({ status: "idle" }, { type: "submit" })).toEqual({ status: "idle" });
    expect(optimizeReducer({ status: "submitting" }, { type: "submit" })).toEqual({ status: "submitting" });
  });

  it("ignores a response that arrives outside `submitting`", () => {
    expect(optimizeReducer({ status: "idle" }, { type: "succeeded", result })).toEqual({ status: "idle" });
    expect(optimizeReducer({ status: "confirming" }, { type: "failed", error: new Error("x") })).toEqual({ status: "confirming" });
  });

  it("failure keeps only kind / code / retry-after", () => {
    const s = optimizeReducer({ status: "submitting" }, { type: "failed", error: new ApiError({ kind: "rate_limited", status: 429, retryAfterS: 5 }) });
    expect(s).toEqual({ status: "failed", kind: "rate_limited", retryAfterS: 5 });
  });

  it("a failed or completed run can be requested again or dismissed", () => {
    expect(optimizeReducer({ status: "failed", kind: "server" }, { type: "request" }).status).toBe("confirming");
    expect(optimizeReducer({ status: "failed", kind: "server" }, { type: "reset" }).status).toBe("idle");
    expect(optimizeReducer({ status: "completed", result }, { type: "reset" }).status).toBe("idle");
  });
});

describe("failureOf", () => {
  it("maps 403 / 429 / 503 model_unavailable / lost session", () => {
    expect(failureOf(new ApiError({ kind: "forbidden", status: 403 }))).toMatchObject({ kind: "forbidden" });
    expect(failureOf(new ApiError({ kind: "rate_limited", status: 429 }))).toMatchObject({ kind: "rate_limited" });
    expect(failureOf(new AuthRequiredError())).toEqual({ status: "failed", kind: "unauthenticated" });
    const model = failureOf(new ApiError({ kind: "unavailable", status: 503, code: "model_unavailable" }));
    expect(isModelUnavailable(model)).toBe(true);
    expect(isModelUnavailable(failureOf(new ApiError({ kind: "unavailable", status: 503 })))).toBe(false);
  });

  it("an arbitrary thrown error is generic and its text is dropped", () => {
    const f = failureOf(new Error("traceback: secret"));
    expect(f).toEqual({ status: "failed", kind: "server" });
  });
});

describe("optional response metadata", () => {
  it("reads strings and flags only when present", () => {
    const o = { model_version: "ppo-3", experimental: true, physics_version: "" };
    expect(optionalText(o, "model_version")).toBe("ppo-3");
    expect(optionalText(o, "physics_version")).toBeNull();
    expect(optionalText(o, "absent")).toBeNull();
    expect(optionalFlag(o, "experimental")).toBe(true);
    expect(optionalFlag(o, "model_version")).toBeNull();
  });
});
