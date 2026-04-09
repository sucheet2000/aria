import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useWorldModel } from "./useWorldModel";
import { useAnchorHydration } from "./useAnchorHydration";

function resetStore() {
  useWorldModel.setState({ anchors: new Map(), activeGesture: null });
}

describe("useAnchorHydration", () => {
  beforeEach(() => {
    resetStore();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetches anchors on mount and adds them to the world model", async () => {
    const payload = {
      anchors: [
        { anchor_id: "a1", label: "lamp", x: 0.1, y: 0.2, z: 0.3 },
        { anchor_id: "a2", label: "chair", x: 0.4, y: 0.5, z: 0.6 },
      ],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(payload),
      })
    );

    const { unmount } = renderHook(() => useAnchorHydration());

    await waitFor(() => {
      expect(useWorldModel.getState().anchors.size).toBe(2);
    });

    const a1 = useWorldModel.getState().anchors.get("a1");
    expect(a1).toEqual({ id: "a1", label: "lamp", x: 0.1, y: 0.2, z: 0.3 });

    const a2 = useWorldModel.getState().anchors.get("a2");
    expect(a2?.label).toBe("chair");

    unmount();
  });

  it("handles fetch failure gracefully — store stays empty", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("network error"))
    );

    const { unmount } = renderHook(() => useAnchorHydration());

    // Give fetch a moment to reject
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(useWorldModel.getState().anchors.size).toBe(0);
    unmount();
  });

  it("handles non-ok HTTP response gracefully — store stays empty", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
      })
    );

    const { unmount } = renderHook(() => useAnchorHydration());

    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(useWorldModel.getState().anchors.size).toBe(0);
    unmount();
  });

  it("does not duplicate anchors on re-render (called once on mount)", async () => {
    const payload = {
      anchors: [{ anchor_id: "a1", label: "lamp", x: 0.1, y: 0.2, z: 0.3 }],
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(payload),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { rerender, unmount } = renderHook(() => useAnchorHydration());
    rerender();
    rerender();

    await waitFor(() => {
      expect(useWorldModel.getState().anchors.size).toBe(1);
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    unmount();
  });
});
