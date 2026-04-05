import { useEffect } from "react";
import { useWorldModel } from "./useWorldModel";
import type { SpatialAnchor } from "./useWorldModel";

const CHANNEL_NAME = "aria-spatial-world";

type SyncMessage =
  | { type: "anchor_added"; anchor: SpatialAnchor }
  | { type: "anchor_removed"; id: string };

export function useSpatialSync(): void {
  const addAnchor = useWorldModel((s) => s.addAnchor);
  const removeAnchor = useWorldModel((s) => s.removeAnchor);

  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;

    const channel = new BroadcastChannel(CHANNEL_NAME);

    channel.onmessage = (event: MessageEvent<SyncMessage>) => {
      const msg = event.data;
      if (msg.type === "anchor_added") {
        addAnchor(msg.anchor);
      } else if (msg.type === "anchor_removed") {
        removeAnchor(msg.id);
      }
    };

    return () => {
      channel.close();
    };
  }, [addAnchor, removeAnchor]);
}

export function broadcastAnchorAdded(anchor: SpatialAnchor): void {
  if (typeof BroadcastChannel === "undefined") return;
  const channel = new BroadcastChannel(CHANNEL_NAME);
  channel.postMessage({ type: "anchor_added", anchor } satisfies SyncMessage);
  channel.close();
}

export function broadcastAnchorRemoved(id: string): void {
  if (typeof BroadcastChannel === "undefined") return;
  const channel = new BroadcastChannel(CHANNEL_NAME);
  channel.postMessage({ type: "anchor_removed", id } satisfies SyncMessage);
  channel.close();
}
