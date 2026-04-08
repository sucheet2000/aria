import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useWorldModel } from "./useWorldModel";
import { useSpatialSync, broadcastAnchorAdded, broadcastAnchorRemoved } from "./useSpatialSync";
import type { SpatialAnchor } from "./useWorldModel";

// ── BroadcastChannel mock ────────────────────────────────────────────────────

type MessageHandler = (event: { data: unknown }) => void;

const mockPostMessage = vi.fn();
const mockClose = vi.fn();

class MockBroadcastChannel {
  name: string;
  onmessage: MessageHandler | null = null;

  constructor(name: string) {
    this.name = name;
    MockBroadcastChannel.lastInstance = this;
  }
  postMessage = mockPostMessage;
  close = mockClose;

  static lastInstance: MockBroadcastChannel | null = null;
}

vi.stubGlobal("BroadcastChannel", MockBroadcastChannel);

// ── Helpers ──────────────────────────────────────────────────────────────────

function resetStore() {
  useWorldModel.setState({ anchors: new Map(), activeGesture: null });
}

// ── broadcastAnchorAdded ─────────────────────────────────────────────────────

describe("broadcastAnchorAdded", () => {
  beforeEach(() => {
    mockPostMessage.mockClear();
    mockClose.mockClear();
  });

  it("posts anchor_added message and closes channel", () => {
    const anchor: SpatialAnchor = { anchor_id: "b1", label: "person", x: 1, y: 2, z: 3 };
    broadcastAnchorAdded(anchor);
    expect(mockPostMessage).toHaveBeenCalledWith({ type: "anchor_added", anchor });
    expect(mockClose).toHaveBeenCalled();
  });
});

// ── broadcastAnchorRemoved ───────────────────────────────────────────────────

describe("broadcastAnchorRemoved", () => {
  beforeEach(() => {
    mockPostMessage.mockClear();
    mockClose.mockClear();
  });

  it("posts anchor_removed message and closes channel", () => {
    broadcastAnchorRemoved("b1");
    expect(mockPostMessage).toHaveBeenCalledWith({ type: "anchor_removed", id: "b1" });
    expect(mockClose).toHaveBeenCalled();
  });

  it("channel is opened with correct name", () => {
    broadcastAnchorAdded({ anchor_id: "x1", label: "test", x: 0, y: 0, z: 0 });
    expect(MockBroadcastChannel.lastInstance?.name).toBe("aria-spatial-world");
  });
});

// ── useSpatialSync incoming messages (real hook via renderHook) ───────────────

describe("useSpatialSync incoming messages", () => {
  beforeEach(() => {
    resetStore();
    MockBroadcastChannel.lastInstance = null;
  });

  it("anchor_added message adds anchor to the store", () => {
    const { unmount } = renderHook(() => useSpatialSync());
    const instance = MockBroadcastChannel.lastInstance!;

    const anchor: SpatialAnchor = { anchor_id: "c1", label: "place", x: 0, y: 1, z: 2 };
    act(() => {
      instance.onmessage?.({ data: { type: "anchor_added", anchor } });
    });

    expect(useWorldModel.getState().anchors.get("c1")).toEqual(anchor);
    unmount();
  });

  it("anchor_removed message removes anchor from the store", () => {
    useWorldModel.getState().addAnchor({ anchor_id: "c2", label: "object", x: 0, y: 0, z: 0 });

    const { unmount } = renderHook(() => useSpatialSync());
    const instance = MockBroadcastChannel.lastInstance!;

    act(() => {
      instance.onmessage?.({ data: { type: "anchor_removed", id: "c2" } });
    });

    expect(useWorldModel.getState().anchors.size).toBe(0);
    unmount();
  });

  it("unknown message type is ignored without throwing", () => {
    const { unmount } = renderHook(() => useSpatialSync());
    const instance = MockBroadcastChannel.lastInstance!;

    expect(() =>
      act(() => {
        instance.onmessage?.({ data: { type: "unknown_event" } });
      })
    ).not.toThrow();

    expect(useWorldModel.getState().anchors.size).toBe(0);
    unmount();
  });

  it("unmount closes the channel", () => {
    mockClose.mockClear();
    const { unmount } = renderHook(() => useSpatialSync());
    unmount();
    expect(mockClose).toHaveBeenCalled();
  });
});
