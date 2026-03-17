"use client";

import { useEffect, useRef, useState } from "react";
import { useAriaStore } from "@/store/ariaStore";
import { useCognition } from "@/hooks/useCognition";

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

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversationHistory]);

  async function handleSend() {
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;
    setInput("");
    await sendMessage(trimmed);
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

      {/* Message list */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {conversationHistory.length === 0 ? (
          <p className="text-center text-sm text-aria-muted">Start a conversation</p>
        ) : (
          conversationHistory.map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                style={{
                  backgroundColor: msg.role === "user" ? "#3730a3" : "#1e293b",
                  borderRadius: "0.75rem",
                  padding: "0.5rem 0.75rem",
                  maxWidth: "80%",
                  fontSize: "0.875rem",
                  color: "#e2e8f0",
                }}
              >
                {msg.content}
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input row */}
      <div className="border-t border-aria-border p-3">
        {isLoading && (
          <p className="text-xs text-aria-muted mb-2">ARIA is thinking...</p>
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
