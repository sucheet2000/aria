import { create } from "zustand";

export interface SpatialAnchor {
  id: string;
  label: string;
  x: number;
  y: number;
  z: number;
  velocity?: [number, number, number];
}

interface WorldModelState {
  anchors: Map<string, SpatialAnchor>;
  activeGesture: string | null;
  addAnchor: (anchor: SpatialAnchor) => void;
  removeAnchor: (id: string) => void;
  updateAnchor: (id: string, label: string) => void;
  setActiveGesture: (gesture: string | null) => void;
  setAnchorVelocity: (id: string, velocity: [number, number, number]) => void;
}

export const useWorldModel = create<WorldModelState>((set) => ({
  anchors: new Map(),
  activeGesture: null,

  addAnchor: (anchor) =>
    set((state) => {
      const next = new Map(state.anchors);
      next.set(anchor.id, anchor);
      return { anchors: next };
    }),

  removeAnchor: (id) =>
    set((state) => {
      const next = new Map(state.anchors);
      next.delete(id);
      return { anchors: next };
    }),

  updateAnchor: (id, label) =>
    set((state) => {
      const existing = state.anchors.get(id);
      if (!existing) return {};
      const next = new Map(state.anchors);
      next.set(id, { ...existing, label });
      return { anchors: next };
    }),

  setActiveGesture: (gesture) => set({ activeGesture: gesture }),

  setAnchorVelocity: (id, velocity) =>
    set((state) => {
      const existing = state.anchors.get(id);
      if (!existing) return {};
      const next = new Map(state.anchors);
      next.set(id, { ...existing, velocity });
      return { anchors: next };
    }),
}));
