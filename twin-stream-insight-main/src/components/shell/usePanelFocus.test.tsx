import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { usePanelFocus } from "./usePanelFocus.ts";

function Panel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const headingRef = usePanelFocus(open);
  if (!open) return null;
  return (
    <aside aria-label="Test panel">
      <h2 ref={headingRef} tabIndex={-1}>
        Test panel
      </h2>
      <button onClick={onClose}>Close panel</button>
    </aside>
  );
}

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen((o) => !o)}>Toggle panel</button>
      <button>Other control</button>
      <Panel open={open} onClose={() => setOpen(false)} />
    </>
  );
}

describe("usePanelFocus (FE-19, Section 13 Focus)", () => {
  it("opening the panel moves focus to its heading", () => {
    render(<Harness />);
    const toggle = screen.getByRole("button", { name: "Toggle panel" });
    toggle.focus();
    fireEvent.click(toggle);
    expect(screen.getByRole("heading", { name: "Test panel" })).toHaveFocus();
  });

  it("closing from inside the panel returns focus to the control that opened it", () => {
    render(<Harness />);
    const toggle = screen.getByRole("button", { name: "Toggle panel" });
    toggle.focus();
    fireEvent.click(toggle);
    const close = screen.getByRole("button", { name: "Close panel" });
    close.focus();
    fireEvent.click(close);
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(toggle).toHaveFocus();
  });

  it("does not steal focus when the user has already moved to another control", () => {
    render(<Harness />);
    const toggle = screen.getByRole("button", { name: "Toggle panel" });
    toggle.focus();
    fireEvent.click(toggle);
    const other = screen.getByRole("button", { name: "Other control" });
    other.focus();
    fireEvent.click(toggle); // closes the panel while focus is on `other`
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(other).toHaveFocus();
  });

  it("can be reopened and still returns to the toggle", () => {
    render(<Harness />);
    const toggle = screen.getByRole("button", { name: "Toggle panel" });
    for (let i = 0; i < 2; i++) {
      toggle.focus();
      fireEvent.click(toggle);
      const close = screen.getByRole("button", { name: "Close panel" });
      close.focus();
      fireEvent.click(close);
      expect(toggle).toHaveFocus();
    }
  });
});
