import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErrorBoundary } from "./ErrorBoundary";

function Boom(): JSX.Element {
  throw new Error("kaboom");
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // React logs caught render errors to console.error — silence the noise.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders children when nothing throws", () => {
    render(
      <ErrorBoundary>
        <span>all good</span>
      </ErrorBoundary>
    );
    expect(screen.getByText("all good")).toBeTruthy();
  });

  it("renders the default fallback when a child throws", () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>
    );
    expect(screen.getByText("3D view unavailable")).toBeTruthy();
  });

  it("renders a custom label in the fallback", () => {
    render(
      <ErrorBoundary label="Avatar unavailable">
        <Boom />
      </ErrorBoundary>
    );
    expect(screen.getByText("Avatar unavailable")).toBeTruthy();
  });

  it("exposes the fallback as an alert for assistive tech", () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>
    );
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("logs the error via componentDidCatch", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>
    );
    const loggedBoundary = errorSpy.mock.calls.some(
      (call) => call[0] === "[ErrorBoundary]"
    );
    expect(loggedBoundary).toBe(true);
  });
});
