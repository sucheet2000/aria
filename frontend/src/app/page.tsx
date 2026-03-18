"use client";

import Avatar3D from "@/components/Avatar3D";
import CameraFeed from "@/components/CameraFeed";
import ChatPanel from "@/components/ChatPanel";
import EmotionIndicator from "@/components/EmotionIndicator";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useAriaStore } from "@/store/ariaStore";

export default function Home() {
  const { connected } = useWebSocket();

  const emotion = useAriaStore((s) => s.emotion);
  const emotionConfidence = useAriaStore((s) => s.emotionConfidence);
  const processingMs = useAriaStore((s) => s.processingMs);

  return (
    <main className="flex h-screen w-screen overflow-hidden bg-aria-dark">
      <div className="w-80 flex-shrink-0 flex flex-col gap-4 p-4 overflow-hidden">
        <div className="flex flex-col gap-1">
          <h1 className="text-3xl font-bold tracking-widest text-aria-accent">ARIA</h1>
          <EmotionIndicator emotion={emotion} confidence={emotionConfidence} size="sm" />
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span
              style={{
                display: "inline-block",
                width: 8,
                height: 8,
                borderRadius: "50%",
                backgroundColor: connected ? "#22c55e" : "#f97316",
                flexShrink: 0,
              }}
            />
            <span className="text-xs" style={{ color: connected ? "#22c55e" : "#f97316" }}>
              {connected ? "live" : "reconnecting"}
            </span>
          </div>
        </div>
        <CameraFeed />
        <ChatPanel />
        {processingMs > 0 && (
          <p className="text-xs text-aria-muted text-right">
            last response: {processingMs}ms
          </p>
        )}
      </div>
      <div className="flex-1 p-4">
        <Avatar3D />
      </div>
    </main>
  );
}
