import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: () => Promise.resolve("test-token") }),
}));

import EpisodicPanel from "./EpisodicPanel";

describe("EpisodicPanel", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("fetches /api/memory/episodic and renders the returned memories", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          facts: ["you talked about the ocean", "you asked about dinner"],
          count: 2,
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<EpisodicPanel assistantMessageCount={0} />);

    await waitFor(() => {
      expect(screen.getByText("you talked about the ocean")).toBeTruthy();
    });
    expect(screen.getByText("you asked about dinner")).toBeTruthy();

    const calledUrl = fetchMock.mock.calls[0][0] as string;
    expect(calledUrl).toContain("/api/memory/episodic");
  });

  it("shows an empty state when no memories are returned", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ facts: [], count: 0 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<EpisodicPanel assistantMessageCount={0} />);

    await waitFor(() => {
      expect(screen.getByText(/no memories/i)).toBeTruthy();
    });
  });
});
