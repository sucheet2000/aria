import { useWorldModel } from "./useWorldModel";
import { broadcastAnchorRemoved } from "./useSpatialSync";

const PYTHON_BASE = "http://localhost:8080";

export async function deleteAnchor(id: string): Promise<void> {
  useWorldModel.getState().removeAnchor(id);
  broadcastAnchorRemoved(id);
  try {
    await fetch(`${PYTHON_BASE}/api/anchors/${id}`, { method: "DELETE" });
  } catch {
    // optimistic remove is kept — no re-add on failure
  }
}
