import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { DataState } from "@/state/dataState";
import { StandardBoundary, StandardState } from "./StandardState";
import { StateSkeleton } from "./StateSkeleton";

afterEach(cleanup);

describe("StateSkeleton", () => {
  it.each(["lines", "card", "table", "chart"] as const)("%s: one polite status, shapes hidden, pulse off under reduced motion", (variant) => {
    const { container } = render(<StateSkeleton variant={variant} label="Loading alerts…" />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(status).toHaveAttribute("data-skeleton", variant);
    expect(status).toHaveTextContent("Loading alerts…");
    const shapes = container.querySelectorAll("[aria-hidden='true'] > div");
    expect(shapes.length).toBeGreaterThan(0);
    shapes.forEach((s) => expect(s.className).toContain("motion-reduce:animate-none"));
  });
});

describe("StandardState", () => {
  it("loading is a skeleton, not a bare spinner or a zero", () => {
    render(<StandardState kind="loading" skeleton="card" />);
    expect(screen.getByRole("status")).toHaveAttribute("data-skeleton", "card");
  });

  it("empty is plain language, not an error, and offers no retry", () => {
    render(<StandardState kind="empty" onRetry={() => undefined} />);
    expect(screen.getByText("Nothing here yet")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a retryable error shows an alert with a working Try again button and no backend text", () => {
    const retry = vi.fn();
    render(<StandardState kind="error" errorKind="network" onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not reach the server");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it.each(["forbidden", "unauthenticated", "validation", "contract"] as const)("a %s error never offers a retry", (errorKind) => {
    render(<StandardState kind="error" errorKind={errorKind} onRetry={() => undefined} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("stale says it may be out of date and offers Refresh", () => {
    const retry = vi.fn();
    render(<StandardState kind="stale" onRetry={retry} />);
    expect(screen.getByText("This may be out of date")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(retry).toHaveBeenCalled();
  });

  it("disconnected is announced assertively and has an icon and words, not colour alone", () => {
    const { container } = render(<StandardState kind="disconnected" onRetry={() => undefined} />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "assertive");
    expect(screen.getByText("Connection lost")).toBeInTheDocument();
    expect(container.querySelector("[data-state-icon='disconnected']")).not.toBeNull();
  });

  it("feature wording replaces the default text", () => {
    render(<StandardState kind="empty">No alerts in this period.</StandardState>);
    expect(screen.getByText("No alerts in this period.")).toBeInTheDocument();
  });
});

describe("StandardBoundary", () => {
  const view = (state: DataState<string>, onRetry?: () => void) =>
    render(
      <StandardBoundary state={state} onRetry={onRetry} skeleton="table">
        {(d) => <p>data: {d}</p>}
      </StandardBoundary>,
    );

  it("skeleton while loading, children when ready", () => {
    const { unmount } = view({ status: "loading" });
    expect(screen.getByRole("status")).toHaveAttribute("data-skeleton", "table");
    unmount();
    view({ status: "ready", data: "x" });
    expect(screen.getByText("data: x")).toBeInTheDocument();
  });

  it("a failed refetch keeps the last data, labelled, with a retry", () => {
    const retry = vi.fn();
    view({ status: "ready", data: "old", refreshFailed: true }, retry);
    expect(screen.getByText("data: old")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
  });

  it("errors and empty come from the shared boundary", () => {
    const { unmount } = view({ status: "error", kind: "server" }, () => undefined);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    unmount();
    view({ status: "empty" });
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
