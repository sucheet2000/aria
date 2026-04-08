import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { useWorldModel } from "./useWorldModel";
import { deleteAnchor } from "./deleteAnchorFn";

// BroadcastChannel mock (same approach as useSpatialSync.test.ts)
const mockPostMessage = vi.fn();
const mockClose = vi.fn();

class MockBroadcastChannel {
  onmessage: null = null;
  constructor() {}
  postMessage = mockPostMessage;
  close = mockClose;
}

vi.stubGlobal("BroadcastChannel", MockBroadcastChannel);

function resetStore() {
  useWorldModel.setState({ anchors: new Map(), activeGesture: null });
}

describe("deleteAnchor", () => {
  beforeEach(() => {
    resetStore();
    mockPostMessage.mockClear();
    mockClose.mockClear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    // Do not unstub BroadcastChannel — it's mocked at module level.
  });

  it("removes the anchor from the store immediately (optimistic)", async () => {
    useWorldModel.getState().addAnchor({ id: "a1", label: "lamp", x: 0, y: 0, z: 0 });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ deleted: "a1" }) })
    );

    await deleteAnchor("a1");

    expect(useWorldModel.getState().anchors.has("a1")).toBe(false);
  });

  it("calls DELETE /api/anchors/{id}", async () => {
    useWorldModel.getState().addAnchor({ id: "a1", label: "lamp", x: 0, y: 0, z: 0 });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    await deleteAnchor("a1");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8080/api/anchors/a1",
      { method: "DELETE" }
    );
  });

  it("broadcasts anchor_removed via BroadcastChannel", async () => {
    useWorldModel.getState().addAnchor({ id: "a1", label: "lamp", x: 0, y: 0, z: 0 });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));

    await deleteAnchor("a1");

    expect(mockPostMessage).toHaveBeenCalledWith({ type: "anchor_removed", id: "a1" });
  });

  it("does not re-add the anchor if fetch fails", async () => {
    useWorldModel.getState().addAnchor({ id: "a1", label: "lamp", x: 0, y: 0, z: 0 });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network error")));

    await deleteAnchor("a1");

    // Store should still not have it — optimistic remove is kept
    expect(useWorldModel.getState().anchors.has("a1")).toBe(false);
  });
});
