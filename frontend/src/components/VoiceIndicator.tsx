"use client";

import { useAriaStore } from "@/store/ariaStore";

export default function VoiceIndicator() {
  const isRecording = useAriaStore((s) => s.isRecording);
  const isSpeaking = useAriaStore((s) => s.isSpeaking);
  const voiceTranscript = useAriaStore((s) => s.voiceTranscript);
  const voiceConfidence = useAriaStore((s) => s.voiceConfidence);

  let statusLabel: string;
  let dotContent: React.ReactNode;

  if (isRecording) {
    statusLabel = "listening";
    dotContent = <span className="voice-pulse-dot" />;
  } else if (isSpeaking) {
    statusLabel = "speaking";
    dotContent = (
      <span className="voice-wave-bars">
        <span />
        <span />
        <span />
      </span>
    );
  } else {
    statusLabel = "idle";
    dotContent = <span className="voice-idle-dot" />;
  }

  return (
    <>
      <style>{`
        .voice-pulse-dot {
          display: inline-block;
          width: 10px;
          height: 10px;
          border-radius: 50%;
          background-color: #f97316;
          flex-shrink: 0;
          animation: voice-pulse 1.2s ease-in-out infinite;
        }

        @keyframes voice-pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.4; transform: scale(1.35); }
        }

        .voice-idle-dot {
          display: inline-block;
          width: 10px;
          height: 10px;
          border-radius: 50%;
          background-color: #475569;
          flex-shrink: 0;
        }

        .voice-wave-bars {
          display: inline-flex;
          align-items: flex-end;
          gap: 2px;
          height: 14px;
          flex-shrink: 0;
        }

        .voice-wave-bars span {
          display: inline-block;
          width: 3px;
          background-color: #6366f1;
          border-radius: 2px;
          animation: voice-wave 0.8s ease-in-out infinite;
        }

        .voice-wave-bars span:nth-child(1) {
          animation-delay: 0s;
        }

        .voice-wave-bars span:nth-child(2) {
          animation-delay: 0.15s;
        }

        .voice-wave-bars span:nth-child(3) {
          animation-delay: 0.3s;
        }

        @keyframes voice-wave {
          0%, 100% { height: 4px; }
          50% { height: 14px; }
        }

        .voice-indicator {
          transition: opacity 0.2s ease;
        }
      `}</style>

      <div
        className="voice-indicator border-b border-aria-border px-3 py-2"
        style={{ display: "flex", flexDirection: "column", gap: 4 }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {dotContent}
          <span
            className="text-xs"
            style={{
              color: isRecording
                ? "#f97316"
                : isSpeaking
                ? "#6366f1"
                : "#64748b",
              transition: "color 0.2s ease",
            }}
          >
            {statusLabel}
          </span>
        </div>

        {isRecording && voiceTranscript && (
          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <p
              className="text-xs"
              style={{ color: "#cbd5e1", fontStyle: "italic", margin: 0 }}
            >
              {voiceTranscript}
            </p>
            {voiceConfidence > 0 && (
              <span className="text-xs" style={{ color: "#475569" }}>
                {Math.round(voiceConfidence * 100)}%
              </span>
            )}
          </div>
        )}
      </div>
    </>
  );
}
