import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RackInspectorContent } from "./RackInspectorContent.tsx";

describe("RackInspectorContent", () => {
  it("names the zone the same way as the search palette and screen-reader announcements", () => {
    render(<RackInspectorContent rackId="zone-2-row-1-rack-3" />);
    expect(screen.getByText(/Zone B · Row 1/)).toBeTruthy();
    expect(screen.queryByText(/Zone 2/)).toBeNull();
  });

  it("without a feed it shows a state notice, never a number", () => {
    render(<RackInspectorContent rackId="zone-2-row-1-rack-3" />);
    expect(screen.getByText(/Connecting to live feed/)).toBeTruthy();
  });
});
