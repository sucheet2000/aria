"use client";

import Avatar3D from "@/components/Avatar3D";
import CameraFeed from "@/components/CameraFeed";
import ChatPanel from "@/components/ChatPanel";
import EmotionIndicator from "@/components/EmotionIndicator";
import MemoryPanel from "@/components/MemoryPanel";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useAriaStore } from "@/store/ariaStore";

function deriveStateLabel(
  wsConnected: boolean,
  isSpeaking: boolean,
  isThinking: boolean,
  isListening: boolean
): string {
  if (!wsConnected) return "idle";
  if (isSpeaking) return "speaking";
  if (isThinking) return "thinking";
  if (isListening) return "listening";
  return "idle";
}

export default function Home() {
  const { connected } = useWebSocket();

  const emotion = useAriaStore((s) => s.emotion);
  const emotionConfidence = useAriaStore((s) => s.emotionConfidence);
  const processingMs = useAriaStore((s) => s.processingMs);
  const conversationHistory = useAriaStore((s) => s.conversationHistory);
  const wsConnected = useAriaStore((s) => s.wsConnected);
  const isSpeaking = useAriaStore((s) => s.isSpeaking);
  const isThinking = useAriaStore((s) => s.isThinking);
  const isListening = useAriaStore((s) => s.isListening);
  const symbolicInference = useAriaStore((s) => s.symbolicInference);

  const assistantMessageCount = conversationHistory.filter(
    (m) => m.role === "assistant"
  ).length;

  const stateLabel = deriveStateLabel(wsConnected, isSpeaking, isThinking, isListening);

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
        <div style={{ position: "relative" }}>
          <MemoryPanel assistantMessageCount={assistantMessageCount} />
        </div>
      </div>
      <div
        className="flex-1 p-4"
        style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}
      >
        <Avatar3D />
        <p
          style={{
            marginTop: 12,
            fontSize: 11,
            color: "#4338ca",
            letterSpacing: "0.1em",
            textAlign: "center",
            textTransform: "uppercase",
          }}
        >
          {stateLabel}
        </p>
        {symbolicInference && (
          <p
            style={{
              marginTop: 4,
              fontSize: 12,
              fontStyle: "italic",
              color: "#312e81",
              maxWidth: 280,
              textAlign: "center",
            }}
          >
            {symbolicInference}
          </p>
        )}
      </div>
    </main>
  );
}
