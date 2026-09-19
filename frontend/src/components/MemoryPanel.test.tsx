import { describe, it, expect, afterEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  waitFor,
  fireEvent,
} from "@testing-library/react";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: () => Promise.resolve("test-token") }),
}));

import MemoryPanel from "./MemoryPanel";

const profileResponse = {
  ok: true,
  status: 200,
  json: () => Promise.resolve({ facts: ["likes tea", "lives in Hyderabad"] }),
};

const emptyProfileResponse = {
  ok: true,
  status: 200,
  json: () => Promise.resolve({ facts: [] }),
};

interface MockResponse {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
}

function stubFetch(deleteResponse?: MockResponse) {
  let deleted = false;
  const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
    if (init?.method === "DELETE") {
      const res = deleteResponse ?? {
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({ deleted: { profile: 2, episodic: 0, working: 0 } }),
      };
      if (res.ok) deleted = true;
      return Promise.resolve(res);
    }
    return Promise.resolve(deleted ? emptyProfileResponse : profileResponse);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function deleteCalls(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.filter(
    (call) => (call[1] as RequestInit | undefined)?.method === "DELETE",
  );
}

async function renderWithFacts() {
  render(<MemoryPanel assistantMessageCount={0} />);
  await waitFor(() => {
    expect(screen.getByText("likes tea")).toBeTruthy();
  });
}

describe("MemoryPanel", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders facts from /api/memory/profile and shows the delete all memory button", async () => {
    const fetchMock = stubFetch();
    await renderWithFacts();

    expect(screen.getByText("lives in Hyderabad")).toBeTruthy();
    expect(fetchMock.mock.calls[0][0]).toContain("/api/memory/profile");
    expect(
      screen.getByRole("button", { name: "delete all memory" }),
    ).toBeTruthy();
  });

  it("clicking delete all memory shows the confirmation without sending a DELETE", async () => {
    const fetchMock = stubFetch();
    await renderWithFacts();

    fireEvent.click(screen.getByRole("button", { name: "delete all memory" }));

    expect(
      screen.getByText("delete everything ARIA remembers about you?"),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "yes, delete" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "cancel" })).toBeTruthy();
    expect(deleteCalls(fetchMock)).toHaveLength(0);
  });

  it("cancel hides the confirmation and sends no DELETE", async () => {
    const fetchMock = stubFetch();
    await renderWithFacts();

    fireEvent.click(screen.getByRole("button", { name: "delete all memory" }));
    fireEvent.click(screen.getByRole("button", { name: "cancel" }));

    expect(
      screen.queryByText("delete everything ARIA remembers about you?"),
    ).toBeNull();
    expect(deleteCalls(fetchMock)).toHaveLength(0);
    expect(screen.getByText("likes tea")).toBeTruthy();
  });

  it("yes, delete sends DELETE /api/memory with the bearer token, clears facts and notifies", async () => {
    const fetchMock = stubFetch();
    const dispatchSpy = vi.spyOn(window, "dispatchEvent");
    await renderWithFacts();

    fireEvent.click(screen.getByRole("button", { name: "delete all memory" }));
    fireEvent.click(screen.getByRole("button", { name: "yes, delete" }));

    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toBe("memory deleted");
    });

    const calls = deleteCalls(fetchMock);
    expect(calls).toHaveLength(1);
    const [url, init] = calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/memory$/);
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer test-token",
    );

    expect(screen.getByText("no facts stored")).toBeTruthy();
    expect(screen.queryByText("likes tea")).toBeNull();
    expect(
      screen.queryByText("delete everything ARIA remembers about you?"),
    ).toBeNull();

    const dispatched = dispatchSpy.mock.calls.map(
      (call) => (call[0] as Event).type,
    );
    expect(dispatched).toContain("aria:memory-updated");
    dispatchSpy.mockRestore();
  });

  it("a failed DELETE keeps the facts and reports could not delete memory", async () => {
    stubFetch({
      ok: false,
      status: 500,
      json: () => Promise.resolve({ error: "boom" }),
    });
    await renderWithFacts();

    fireEvent.click(screen.getByRole("button", { name: "delete all memory" }));
    fireEvent.click(screen.getByRole("button", { name: "yes, delete" }));

    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toBe(
        "could not delete memory",
      );
    });
    expect(screen.getByText("likes tea")).toBeTruthy();
    expect(screen.getByText("lives in Hyderabad")).toBeTruthy();
  });

  it("yes, delete also clears the browser conversation history so old replies cannot replay deleted facts", async () => {
    const { useAriaStore } = await import("@/store/ariaStore");
    useAriaStore.setState({
      conversationHistory: [
        { role: "user", content: "what do I own" },
        { role: "assistant", content: "you own a red bicycle" },
      ],
    });
    const fetchMock = vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === "DELETE") {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ deleted: { profile: 1, episodic: 0, working: 0 } }) });
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ facts: [], count: 0 }) });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryPanel assistantMessageCount={0} />);
    fireEvent.click(await screen.findByRole("button", { name: /delete all memory/i }));
    fireEvent.click(screen.getByRole("button", { name: /yes, delete/i }));
    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toMatch(/memory deleted/i);
    });
    expect(useAriaStore.getState().conversationHistory).toEqual([]);
  });

  it("export my data downloads every page of /api/memory/export as one JSON file", async () => {
    const page0 = { profile: [{ id: "a1", collection: "profile", content: "one" }], episodic: [], working: [], truncated: ["profile"] };
    const page1 = { profile: [{ id: "a2", collection: "profile", content: "two" }], episodic: [], working: [], truncated: [] };
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/memory/export")) {
        const body = url.includes("offset=500") ? page1 : page0;
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ facts: ["one"], count: 1 }) });
    });
    vi.stubGlobal("fetch", fetchMock);
    const createObjectURL = vi.fn().mockReturnValue("blob:aria-export");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL }));
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<MemoryPanel assistantMessageCount={0} />);
    fireEvent.click(await screen.findByRole("button", { name: /export my data/i }));

    await waitFor(() => {
      expect(clickSpy).toHaveBeenCalledTimes(1);
    });
    const exportCalls = fetchMock.mock.calls.filter(([u]) => String(u).includes("/api/memory/export"));
    expect(exportCalls).toHaveLength(2);
    expect(String(exportCalls[1][0])).toContain("offset=500");
    const blob = createObjectURL.mock.calls[0][0] as Blob;
    const text = await blob.text();
    const parsed = JSON.parse(text);
    expect(parsed.profile.map((e: { id: string }) => e.id)).toEqual(["a1", "a2"]);
    expect(screen.getByRole("status").textContent).toMatch(/exported/i);
    clickSpy.mockRestore();
  });
});
