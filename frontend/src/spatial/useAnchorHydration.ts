import { useEffect } from "react";
import { useWorldModel } from "./useWorldModel";

const PYTHON_BASE = "http://localhost:8080";

interface AnchorPayload {
  anchor_id: string;
  label: string;
  x: number;
  y: number;
  z: number;
}

export function useAnchorHydration(): void {
  const addAnchor = useWorldModel((s) => s.addAnchor);

  useEffect(() => {
    fetch(`${PYTHON_BASE}/api/anchors`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data: { anchors: AnchorPayload[] }) => {
        for (const a of data.anchors) {
          addAnchor({ id: a.anchor_id, label: a.label, x: a.x, y: a.y, z: a.z });
        }
      })
      .catch(() => {
        // non-fatal: canvas starts empty
      });
  }, [addAnchor]);
}
