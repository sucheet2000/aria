"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAriaStore } from "@/store/ariaStore";
import { useCognition } from "@/hooks/useCognition";
import { useTTS } from "@/hooks/useTTS";

export default function ChatPanel() {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const conversationHistory = useAriaStore((s) => s.conversationHistory);
  const isRecording = useAriaStore((s) => s.isRecording);
  const isSpeaking = useAriaStore((s) => s.isSpeaking);
  const voiceTranscript = useAriaStore((s) => s.voiceTranscript);

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
      if (text && !isLoading) {
        handleSendWithTTS(text);
      }
    };
    window.addEventListener("aria:voice-transcript", handler);
    return () => window.removeEventListener("aria:voice-transcript", handler);
  }, [handleSendWithTTS, isLoading]);

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

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        flex: 1,
        minHeight: 0,
        overflow: "hidden",
      }}
    >
      {/* Message list */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "16px 24px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        {conversationHistory.length === 0 ? (
          <p
            style={{
              textAlign: "center",
              fontSize: 13,
              color: "var(--on-surface-faint)",
              fontFamily: "var(--font-body)",
            }}
          >
            speak or type to begin
          </p>
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
                  animation: "aria-fade-up 0.3s ease forwards",
                }}
              >
                {showLabel && (
                  <span
                    style={{
                      fontFamily: "var(--font-data)",
                      fontWeight: 400,
                      fontSize: 10,
                      color: isUser ? "var(--on-surface-faint)" : "var(--primary)",
                      opacity: isUser ? 1 : 0.6,
                      marginBottom: 4,
                    }}
                  >
                    {isUser ? "you" : "aria"}
                  </span>
                )}
                <div
                  style={{
                    fontFamily: "var(--font-body)",
                    fontWeight: 400,
                    fontSize: 14,
                    color: "var(--on-surface)",
                    maxWidth: "80%",
                    lineHeight: 1.5,
                    textAlign: isUser ? "right" : "left",
                    borderRight: isUser
                      ? "2px solid rgba(163, 166, 255, 0.3)"
                      : "none",
                    paddingRight: isUser ? 8 : 0,
                  }}
                >
                  {msg.content}
                </div>
              </div>
            );
          })
        )}

        {/* Thinking indicator */}
        {isLoading && (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-start",
              gap: 6,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              {[0, 0.2, 0.4].map((delay, idx) => (
                <span
                  key={idx}
                  style={{
                    display: "inline-block",
                    width: 5,
                    height: 5,
                    borderRadius: "50%",
                    backgroundColor: "var(--primary)",
                    animation: `aria-dot-stagger 1.2s ease-in-out ${delay}s infinite`,
                  }}
                />
              ))}
            </div>
            <span
              style={{
                fontFamily: "var(--font-data)",
                fontWeight: 400,
                fontSize: 10,
                color: "var(--on-surface-faint)",
              }}
            >
              processing
            </span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div
        style={{
          borderTop: "1px solid var(--outline-ghost)",
          padding: "12px 24px",
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexShrink: 0,
        }}
      >
        {/* Mic indicator when recording */}
        {isRecording && (
          <span
            style={{
              display: "inline-block",
              width: 8,
              height: 8,
              borderRadius: "50%",
              backgroundColor: "#f97316",
              flexShrink: 0,
              animation: "aria-pulse-dot 1.2s ease infinite",
            }}
          />
        )}

        {/* Wave bars when speaking */}
        {isSpeaking && !isRecording && (
          <span
            style={{
              display: "inline-flex",
              alignItems: "flex-end",
              gap: 2,
              height: 14,
              flexShrink: 0,
            }}
          >
            {[0, 0.15, 0.3].map((delay, idx) => (
              <span
                key={idx}
                style={{
                  display: "inline-block",
                  width: 3,
                  backgroundColor: "var(--primary)",
                  borderRadius: 2,
                  height: 8,
                  animation: `aria-voice-wave 0.8s ease-in-out ${delay}s infinite`,
                }}
              />
            ))}
          </span>
        )}

        {/* Live transcript while recording */}
        {isRecording && voiceTranscript && (
          <span
            style={{
              fontFamily: "var(--font-body)",
              fontSize: 13,
              color: "var(--on-surface-muted)",
              fontStyle: "italic",
              flex: 1,
            }}
          >
            {voiceTranscript}
          </span>
        )}

        {!isRecording && (
          <>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="speak or type..."
              style={{
                flex: 1,
                background: "transparent",
                border: "none",
                outline: "none",
                fontFamily: "var(--font-body)",
                fontWeight: 400,
                fontSize: 14,
                color: "var(--on-surface)",
                padding: "4px 0",
              }}
            />
            <button
              type="button"
              onClick={handleSend}
              disabled={isLoading || !input.trim()}
              style={{
                background:
                  "linear-gradient(135deg, var(--primary-dim), var(--primary))",
                borderRadius: 20,
                padding: "6px 16px",
                fontFamily: "var(--font-body)",
                fontWeight: 500,
                fontSize: 12,
                color: "var(--on-surface)",
                border: "none",
                cursor:
                  isLoading || !input.trim() ? "not-allowed" : "pointer",
                opacity: isLoading || !input.trim() ? 0.4 : 1,
                transition: "opacity 0.2s ease",
                flexShrink: 0,
              }}
            >
              Send
            </button>
          </>
        )}
      </div>
    </div>
  );
}
