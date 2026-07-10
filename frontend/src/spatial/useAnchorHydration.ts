import { useEffect, useRef } from "react";
import { useAuth } from "@clerk/nextjs";
import { useWorldModel } from "./useWorldModel";
import { API_BASE } from "@/lib/config";

interface AnchorPayload {
  anchor_id: string;
  label: string;
  x: number;
  y: number;
  z: number;
}

export function useAnchorHydration(): void {
  const addAnchor = useWorldModel((s) => s.addAnchor);
  const { getToken } = useAuth();
  const getTokenRef = useRef(getToken);
  getTokenRef.current = getToken;

  useEffect(() => {
    getTokenRef
      .current()
      .then((token) =>
        fetch(`${API_BASE}/api/anchors`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
      )
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data: { anchors: AnchorPayload[] }) => {
        for (const a of data.anchors) {
          addAnchor({ anchor_id: a.anchor_id, label: a.label, x: a.x, y: a.y, z: a.z });
        }
      })
      .catch(() => {
        // non-fatal: canvas starts empty
      });
  }, [addAnchor]);
}
