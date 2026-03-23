"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useAriaStore } from "@/store/ariaStore";
import { useCognition } from "@/hooks/useCognition";
import { useTTS } from "@/hooks/useTTS";

export default function ChatPanel() {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const conversationHistory = useAriaStore(s => s.conversationHistory);
  const isLoading = useAriaStore(s => s.isThinking);
  const { sendMessage } = useCognition();
  const { speak } = useTTS();

  // Auto-scroll to latest message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversationHistory]);

  // Listen for voice transcripts and auto-send
  const handleSendWithTTS = useCallback(async (text: string) => {
    await sendMessage(text, speak);
  }, [sendMessage, speak]);

  useEffect(() => {
    const handler = (e: Event) => {
      const text = (e as CustomEvent<{ transcript: string }>).detail.transcript;
      console.log('[ChatPanel] aria:voice-transcript received:', text, 'isLoading:', isLoading);
      if (text && !isLoading) handleSendWithTTS(text);
    };
    window.addEventListener("aria:voice-transcript", handler);
    return () => window.removeEventListener("aria:voice-transcript", handler);
  }, [handleSendWithTTS, isLoading]);

  async function handleSend() {
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;
    setInput("");
    await handleSendWithTTS(trimmed);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  }

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      height: "100%",
      minHeight: 0,
    }}>
      {/* Panel header */}
      <div style={{
        padding: "16px 20px 12px",
        borderBottom: "1px solid var(--outline-ghost)",
        flexShrink: 0,
      }}>
        <span style={{
          fontFamily: "var(--font-data)",
          fontWeight: 500,
          fontSize: 11,
          color: "var(--on-surface-muted)",
          textTransform: "uppercase",
          letterSpacing: "0.15em",
        }}>
          conversation log
        </span>
      </div>

      {/* Message log — read only */}
      <div style={{
        flex: 1,
        overflowY: "auto",
        padding: "12px 20px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}>
        {conversationHistory.length === 0 ? (
          <p style={{
            fontFamily: "var(--font-data)",
            fontSize: 11,
            color: "var(--on-surface-faint)",
            fontStyle: "italic",
            textAlign: "center",
            marginTop: 24,
          }}>
            no messages yet
          </p>
        ) : (
          conversationHistory.map((msg, i) => {
            const isUser = msg.role === "user";
            const showLabel = i === 0 || conversationHistory[i-1]?.role !== msg.role;
            return (
              <div key={i} style={{
                display: "flex",
                flexDirection: "column",
                alignItems: isUser ? "flex-end" : "flex-start",
                animation: "aria-fade-up 0.25s ease forwards",
              }}>
                {showLabel && (
                  <span style={{
                    fontFamily: "var(--font-data)",
                    fontSize: 10,
                    color: isUser ? "var(--on-surface-faint)" : "var(--primary)",
                    opacity: isUser ? 1 : 0.7,
                    marginBottom: 3,
                    letterSpacing: "0.1em",
                  }}>
                    {isUser ? "you" : "aria"}
                  </span>
                )}
                <div style={{
                  fontFamily: "var(--font-body)",
                  fontSize: 13,
                  color: "var(--on-surface)",
                  lineHeight: 1.55,
                  maxWidth: "90%",
                  textAlign: isUser ? "right" : "left",
                  borderRight: isUser ? "2px solid rgba(163,166,255,0.25)" : "none",
                  paddingRight: isUser ? 8 : 0,
                }}>
                  {msg.content}
                </div>
              </div>
            );
          })
        )}

        {/* Thinking indicator */}
        {isLoading && (
          <div style={{ display: "flex", alignItems: "center", gap: 5, paddingLeft: 2 }}>
            {[0, 0.2, 0.4].map((delay, idx) => (
              <span key={idx} style={{
                display: "inline-block",
                width: 4, height: 4,
                borderRadius: "50%",
                backgroundColor: "var(--primary)",
                animation: `aria-dot-stagger 1.2s ease-in-out ${delay}s infinite`,
              }} />
            ))}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Text input — for users who cannot speak */}
      <div style={{
        borderTop: "1px solid var(--outline-ghost)",
        padding: "10px 16px",
        display: "flex",
        alignItems: "center",
        gap: 8,
        flexShrink: 0,
      }}>
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="type a message..."
          style={{
            flex: 1,
            background: "transparent",
            border: "none",
            outline: "none",
            fontFamily: "var(--font-body)",
            fontSize: 13,
            color: "var(--on-surface)",
            padding: "4px 0",
          }}
        />
        <button
          type="button"
          onClick={handleSend}
          disabled={isLoading || !input.trim()}
          style={{
            background: "linear-gradient(135deg, var(--primary-dim), var(--primary))",
            borderRadius: 16,
            padding: "5px 14px",
            fontFamily: "var(--font-body)",
            fontWeight: 500,
            fontSize: 11,
            color: "var(--on-surface)",
            border: "none",
            cursor: isLoading || !input.trim() ? "not-allowed" : "pointer",
            opacity: isLoading || !input.trim() ? 0.4 : 1,
            flexShrink: 0,
          }}
        >
          send
        </button>
      </div>
    </div>
  );
}
