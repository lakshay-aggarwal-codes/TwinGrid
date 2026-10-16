import { describe, expect, it } from "vitest";
import { sceneFrameloop } from "./frameloop";

describe("sceneFrameloop", () => {
  it("renders on demand while the tab is visible", () => {
    expect(sceneFrameloop(true)).toBe("demand");
  });
  it("stops rendering while the tab is hidden", () => {
    expect(sceneFrameloop(false)).toBe("never");
  });
});
