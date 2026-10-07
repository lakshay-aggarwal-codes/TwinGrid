import { describe, expect, it } from "vitest";
import fresh from "./golden/operational-fresh.md?raw";
import stale from "./golden/operational-stale.md?raw";
import { buildOperationalReport, reportToMarkdown } from "./reports";
import { captureIn } from "./reportFixtures";

/**
 * Markdown goldens double as the evidence artifact (sample outputs, fresh vs stale). To refresh them after an intentional
 * change, regenerate from `captureIn("live" | "stale")` with `buildOperationalReport` + `reportToMarkdown` and review the diff.
 */
const build = (state: "live" | "stale") => {
  const { capture, liveState } = captureIn(state);
  return reportToMarkdown(buildOperationalReport({ liveState, latestAnomaly: null, optimizeSummary: null }, capture));
};

describe("operational report Markdown goldens", () => {
  it("fresh feed", () => {
    expect(build("live")).toBe(fresh);
  });

  it("stale feed: the report says so in its first lines", () => {
    expect(build("stale")).toBe(stale);
    const firstLines = stale.split("\n").slice(0, 6).join("\n");
    expect(firstLines).toMatch(/STALE: generated while the live feed was stale \(last update 42 s ago\)/);
    expect(fresh).not.toMatch(/STALE|DISCONNECTED/);
  });
});
