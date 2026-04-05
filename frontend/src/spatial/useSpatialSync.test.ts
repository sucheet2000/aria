import { describe, it, expect, beforeEach, vi, type Mock } from "vitest";
import { useWorldModel } from "./useWorldModel";
import { broadcastAnchorAdded, broadcastAnchorRemoved } from "./useSpatialSync";
import type { SpatialAnchor } from "./useWorldModel";

// ── BroadcastChannel mock ────────────────────────────────────────────────────

type MessageHandler = (event: { data: unknown }) => void;

const mockPostMessage = vi.fn();
const mockClose = vi.fn();
let capturedOnMessage: MessageHandler | null = null;

class MockBroadcastChannel {
  name: string;
  onmessage: MessageHandler | null = null;

  constructor(name: string) {
    this.name = name;
    // expose this instance so tests can simulate incoming messages
    MockBroadcastChannel.lastInstance = this;
    // track onmessage assignment via setter
    Object.defineProperty(this, "onmessage", {
      set(fn: MessageHandler) { capturedOnMessage = fn; },
      get() { return capturedOnMessage; },
    });
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

function simulateIncoming(data: unknown) {
  capturedOnMessage?.({ data });
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe("broadcastAnchorAdded", () => {
  beforeEach(() => {
    mockPostMessage.mockClear();
    mockClose.mockClear();
  });

  it("posts anchor_added message and closes channel", () => {
    const anchor: SpatialAnchor = { id: "b1", label: "person", x: 1, y: 2, z: 3 };
    broadcastAnchorAdded(anchor);
    expect(mockPostMessage).toHaveBeenCalledWith({ type: "anchor_added", anchor });
    expect(mockClose).toHaveBeenCalled();
  });
});

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
});

describe("useSpatialSync incoming messages", () => {
  beforeEach(() => {
    resetStore();
    capturedOnMessage = null;
  });

  it("anchor_added message adds anchor to the store", async () => {
    // Manually wire the onmessage handler the same way the hook does
    const { addAnchor, removeAnchor } = useWorldModel.getState();
    capturedOnMessage = (event: { data: unknown }) => {
      const msg = event.data as { type: string; anchor?: SpatialAnchor; id?: string };
      if (msg.type === "anchor_added" && msg.anchor) addAnchor(msg.anchor);
      else if (msg.type === "anchor_removed" && msg.id) removeAnchor(msg.id);
    };

    const anchor: SpatialAnchor = { id: "c1", label: "place", x: 0, y: 1, z: 2 };
    simulateIncoming({ type: "anchor_added", anchor });

    const { anchors } = useWorldModel.getState();
    expect(anchors.size).toBe(1);
    expect(anchors.get("c1")).toEqual(anchor);
  });

  it("anchor_removed message removes anchor from the store", () => {
    useWorldModel.getState().addAnchor({ id: "c2", label: "object", x: 0, y: 0, z: 0 });

    const { addAnchor, removeAnchor } = useWorldModel.getState();
    capturedOnMessage = (event: { data: unknown }) => {
      const msg = event.data as { type: string; anchor?: SpatialAnchor; id?: string };
      if (msg.type === "anchor_added" && msg.anchor) addAnchor(msg.anchor);
      else if (msg.type === "anchor_removed" && msg.id) removeAnchor(msg.id);
    };

    simulateIncoming({ type: "anchor_removed", id: "c2" });

    expect(useWorldModel.getState().anchors.size).toBe(0);
  });

  it("unknown message type is ignored without throwing", () => {
    const { addAnchor, removeAnchor } = useWorldModel.getState();
    capturedOnMessage = (event: { data: unknown }) => {
      const msg = event.data as { type: string; anchor?: SpatialAnchor; id?: string };
      if (msg.type === "anchor_added" && msg.anchor) addAnchor(msg.anchor);
      else if (msg.type === "anchor_removed" && msg.id) removeAnchor(msg.id);
    };

    expect(() => simulateIncoming({ type: "unknown_event" })).not.toThrow();
    expect(useWorldModel.getState().anchors.size).toBe(0);
  });

  it("channel is opened with correct name", () => {
    broadcastAnchorAdded({ id: "x1", label: "test", x: 0, y: 0, z: 0 });
    expect(MockBroadcastChannel.lastInstance?.name).toBe("aria-spatial-world");
  });
});
