import { describe, it, expect, beforeEach } from "vitest";
import { useWorldModel } from "./useWorldModel";

function resetStore() {
  useWorldModel.setState({ anchors: new Map(), activeGesture: null });
}

describe("useWorldModel", () => {
  beforeEach(resetStore);

  it("starts with empty anchors and null gesture", () => {
    const { anchors, activeGesture } = useWorldModel.getState();
    expect(anchors.size).toBe(0);
    expect(activeGesture).toBeNull();
  });

  it("addAnchor inserts an anchor by id", () => {
    useWorldModel.getState().addAnchor({ id: "a1", label: "person", x: 1, y: 2, z: 3 });
    const { anchors } = useWorldModel.getState();
    expect(anchors.size).toBe(1);
    expect(anchors.get("a1")).toEqual({ id: "a1", label: "person", x: 1, y: 2, z: 3 });
  });

  it("addAnchor overwrites an existing anchor with the same id", () => {
    useWorldModel.getState().addAnchor({ id: "a1", label: "person", x: 1, y: 0, z: 0 });
    useWorldModel.getState().addAnchor({ id: "a1", label: "object", x: 4, y: 5, z: 6 });
    const { anchors } = useWorldModel.getState();
    expect(anchors.size).toBe(1);
    expect(anchors.get("a1")?.label).toBe("object");
  });

  it("removeAnchor deletes by id", () => {
    useWorldModel.getState().addAnchor({ id: "a1", label: "place", x: 0, y: 0, z: 0 });
    useWorldModel.getState().addAnchor({ id: "a2", label: "event", x: 1, y: 1, z: 1 });
    useWorldModel.getState().removeAnchor("a1");
    const { anchors } = useWorldModel.getState();
    expect(anchors.size).toBe(1);
    expect(anchors.has("a1")).toBe(false);
    expect(anchors.has("a2")).toBe(true);
  });

  it("removeAnchor on unknown id does not throw", () => {
    expect(() => useWorldModel.getState().removeAnchor("nonexistent")).not.toThrow();
  });

  it("updateAnchor changes label while preserving position", () => {
    useWorldModel.getState().addAnchor({ id: "a1", label: "person", x: 2, y: 3, z: 4 });
    useWorldModel.getState().updateAnchor("a1", "updated-person");
    const anchor = useWorldModel.getState().anchors.get("a1");
    expect(anchor?.label).toBe("updated-person");
    expect(anchor?.x).toBe(2);
    expect(anchor?.y).toBe(3);
    expect(anchor?.z).toBe(4);
  });

  it("updateAnchor on unknown id is a no-op", () => {
    useWorldModel.getState().updateAnchor("ghost", "noop");
    expect(useWorldModel.getState().anchors.size).toBe(0);
  });

  it("setActiveGesture sets and clears gesture", () => {
    useWorldModel.getState().setActiveGesture("point");
    expect(useWorldModel.getState().activeGesture).toBe("point");
    useWorldModel.getState().setActiveGesture(null);
    expect(useWorldModel.getState().activeGesture).toBeNull();
  });

  it("multiple anchors coexist independently", () => {
    const anchors = [
      { id: "a1", label: "person", x: 0, y: 0, z: 0 },
      { id: "a2", label: "object", x: 1, y: 1, z: 1 },
      { id: "a3", label: "place", x: 2, y: 2, z: 2 },
    ];
    anchors.forEach((a) => useWorldModel.getState().addAnchor(a));
    expect(useWorldModel.getState().anchors.size).toBe(3);
    useWorldModel.getState().removeAnchor("a2");
    expect(useWorldModel.getState().anchors.size).toBe(2);
    expect(useWorldModel.getState().anchors.has("a1")).toBe(true);
    expect(useWorldModel.getState().anchors.has("a3")).toBe(true);
  });
});
