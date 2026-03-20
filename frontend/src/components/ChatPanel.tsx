"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAriaStore } from "@/store/ariaStore";
import { useCognition } from "@/hooks/useCognition";
import { useTTS } from "@/hooks/useTTS";
import VoiceIndicator from "@/components/VoiceIndicator";

const EMOTION_COLORS: Record<string, string> = {
  neutral: "#64748b",
  happy: "#22c55e",
  sad: "#3b82f6",
  angry: "#ef4444",
  surprised: "#f59e0b",
  fearful: "#8b5cf6",
  disgusted: "#84cc16",
};

function colorForEmotion(emotion: string): string {
  return EMOTION_COLORS[emotion] ?? EMOTION_COLORS["neutral"];
}

export default function ChatPanel() {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const conversationHistory = useAriaStore((s) => s.conversationHistory);
  const emotion = useAriaStore((s) => s.emotion);
  const emotionConfidence = useAriaStore((s) => s.emotionConfidence);
  const headPose = useAriaStore((s) => s.headPose);
  const faceLandmarks = useAriaStore((s) => s.faceLandmarks);

  const { sendMessage, isLoading } = useCognition();
  const { speak } = useTTS();

  const handleSendWithTTS = useCallback(
    async (text: string) => {
      await sendMessage(text, speak);
    },
    [sendMessage, speak]
  );

  useEffect(() => {
    const handler = (e: Event) => {
      const text = (e as CustomEvent<{ transcript: string }>).detail.transcript;
      if (text) {
        handleSendWithTTS(text);
      }
    };
    window.addEventListener("aria:voice-transcript", handler);
    return () => window.removeEventListener("aria:voice-transcript", handler);
  }, [handleSendWithTTS]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversationHistory]);

  async function handleSend() {
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;
    setInput("");
    await handleSendWithTTS(trimmed);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") handleSend();
  }

  const dotColor = colorForEmotion(emotion);

  return (
    <div className="flex flex-col flex-1 min-h-0 rounded-lg border border-aria-border bg-[#0a0a0f] overflow-hidden">
      {/* Emotion indicator bar */}
      <div className="border-b border-aria-border px-3 py-2">
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              display: "inline-block",
              width: 10,
              height: 10,
              borderRadius: "50%",
              backgroundColor: dotColor,
              flexShrink: 0,
            }}
          />
          <span className="text-sm text-slate-200">
            {emotion}
            {emotionConfidence > 0 && (
              <span className="text-aria-muted ml-1 text-xs">
                {Math.round(emotionConfidence * 100)}%
              </span>
            )}
          </span>
        </div>
        {faceLandmarks.length === 0 ? (
          <p className="text-xs text-aria-muted mt-1">no face detected</p>
        ) : (
          <p className="text-xs text-aria-muted mt-1">
            pitch: {headPose.pitch.toFixed(1)} yaw: {headPose.yaw.toFixed(1)} roll: {headPose.roll.toFixed(1)}
          </p>
        )}
      </div>

      {/* Voice status */}
      <VoiceIndicator />

      {/* Message list */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {conversationHistory.length === 0 ? (
          <p className="text-center text-sm text-aria-muted">Start a conversation</p>
        ) : (
          conversationHistory.map((msg, i) => {
            const isUser = msg.role === "user";
            const prevRole = i > 0 ? conversationHistory[i - 1].role : null;
            const showLabel = prevRole !== msg.role;

            return (
              <div
                key={i}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: isUser ? "flex-end" : "flex-start",
                  marginBottom: "8px",
                }}
              >
                {showLabel && (
                  <span
                    style={{
                      fontSize: "11px",
                      color: isUser ? "#6366f1" : "#94a3b8",
                      marginBottom: "2px",
                      paddingLeft: isUser ? 0 : "4px",
                      paddingRight: isUser ? "4px" : 0,
                    }}
                  >
                    {isUser ? "You" : "ARIA"}
                  </span>
                )}
                <div
                  style={{
                    backgroundColor: isUser ? "#4f46e5" : "#1e293b",
                    borderRadius: isUser ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
                    borderLeft: isUser ? undefined : "3px solid #6366f1",
                    padding: "10px 14px",
                    maxWidth: "80%",
                    fontSize: "0.875rem",
                    color: isUser ? "#ffffff" : "#e2e8f0",
                  }}
                >
                  {msg.content}
                </div>
              </div>
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input row */}
      <div className="border-t border-aria-border p-3">
        {isLoading && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              marginBottom: "8px",
            }}
          >
            <style>{`
              @keyframes aria-dot-pulse {
                0%, 100% { opacity: 0; }
                50% { opacity: 1; }
              }
            `}</style>
            {[0, 0.2, 0.4].map((delay, idx) => (
              <span
                key={idx}
                style={{
                  display: "inline-block",
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  backgroundColor: "#6366f1",
                  animation: `aria-dot-pulse 1.2s ease-in-out ${delay}s infinite`,
                }}
              />
            ))}
            <span style={{ fontSize: "13px", color: "#6366f1", fontStyle: "italic" }}>
              ARIA is thinking
            </span>
          </div>
        )}
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message"
            className="flex-1 rounded-md bg-aria-surface px-3 py-2 text-sm text-slate-200 placeholder-aria-muted outline-none focus:ring-1"
            style={{ borderColor: "#6366f1" }}
          />
          <button
            type="button"
            onClick={handleSend}
            disabled={isLoading || !input.trim()}
            className="rounded-md bg-aria-accent px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
