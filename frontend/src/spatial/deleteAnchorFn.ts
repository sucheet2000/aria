import { useWorldModel } from "./useWorldModel";
import { broadcastAnchorRemoved } from "./useSpatialSync";

const PYTHON_BASE = "http://localhost:8080";

// Non-React module: read the Clerk JWT off the global instance rather than a hook.
async function getClerkToken(): Promise<string | null> {
  try {
    const clerk = (
      window as unknown as {
        Clerk?: { session?: { getToken: () => Promise<string | null> } };
      }
    ).Clerk;
    return (await clerk?.session?.getToken()) ?? null;
  } catch {
    return null;
  }
}

export async function deleteAnchor(id: string): Promise<void> {
  useWorldModel.getState().removeAnchor(id);
  broadcastAnchorRemoved(id);
  try {
    const token = await getClerkToken();
    await fetch(`${PYTHON_BASE}/api/anchors/${id}`, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch {
    // optimistic remove is kept — no re-add on failure
  }
}
