"use client";

import { useEffect, useRef, useState } from "react";
import { useAriaStore } from "@/store/ariaStore";

export default function ChatPanel() {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const conversationHistory = useAriaStore((s) => s.conversationHistory);
  const addMessage = useAriaStore((s) => s.addMessage);
  const emotion = useAriaStore((s) => s.emotion);
  const headPose = useAriaStore((s) => s.headPose);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversationHistory]);

  function handleSend() {
    const trimmed = input.trim();
    if (!trimmed) return;
    addMessage("user", trimmed);
    setInput("");
    setTimeout(() => {
      addMessage("assistant", "Voice response coming in Sprint 5.");
    }, 0);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") handleSend();
  }

  return (
    <div className="flex flex-col flex-1 min-h-0 rounded-lg border border-aria-border bg-[#0a0a0f] overflow-hidden">
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {conversationHistory.length === 0 ? (
          <p className="text-center text-sm text-aria-muted">No messages yet</p>
        ) : (
          conversationHistory.map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] rounded-lg px-3 py-2 text-sm text-slate-200 ${
                  msg.role === "user" ? "bg-indigo-600" : "bg-slate-800"
                }`}
              >
                {msg.content}
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="border-t border-aria-border p-3 flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type a message..."
          className="flex-1 rounded-md bg-aria-surface px-3 py-2 text-sm text-slate-200 placeholder-aria-muted outline-none focus:ring-1 focus:ring-aria-accent"
        />
        <button
          type="button"
          onClick={handleSend}
          className="rounded-md bg-aria-accent px-4 py-2 text-sm text-white hover:opacity-90"
        >
          Send
        </button>
      </div>

      <div className="border-t border-aria-border px-3 py-1.5 text-xs text-aria-muted flex gap-4">
        <span>emotion: {emotion}</span>
        <span>pitch: {headPose.pitch.toFixed(1)}</span>
        <span>yaw: {headPose.yaw.toFixed(1)}</span>
        <span>roll: {headPose.roll.toFixed(1)}</span>
      </div>
    </div>
  );
}
