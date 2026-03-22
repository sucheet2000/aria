"use client";

import { useAriaStore } from "@/store/ariaStore";

export default function VoiceDot() {
  const isListening = useAriaStore(s => s.isListening);
  const isSpeaking  = useAriaStore(s => s.isSpeaking);
  const isRecording = useAriaStore(s => s.isRecording);

  const active = isListening || isRecording;

  if (isSpeaking) {
    // Wave bars
    return (
      <div style={{
        display: "flex",
        alignItems: "flex-end",
        gap: 3,
        height: 20,
        padding: "0 4px",
      }}>
        {[0, 0.15, 0.3].map((delay, i) => (
          <span key={i} style={{
            display: "inline-block",
            width: 3,
            backgroundColor: "var(--primary)",
            borderRadius: 2,
            animation: `aria-voice-wave 0.7s ease-in-out ${delay}s infinite`,
          }} />
        ))}
      </div>
    );
  }

  if (active) {
    // Pulsing dot with expanding ring
    return (
      <div style={{ position: "relative", width: 24, height: 24, display: "flex", alignItems: "center", justifyContent: "center" }}>
        {/* Expanding ring */}
        <span style={{
          position: "absolute",
          width: 24, height: 24,
          borderRadius: "50%",
          border: "1px solid var(--primary)",
          opacity: 0.4,
          animation: "aria-listen-ring 1.2s ease-out infinite",
        }} />
        {/* Core dot */}
        <span style={{
          width: 8, height: 8,
          borderRadius: "50%",
          backgroundColor: "var(--primary)",
          animation: "aria-pulse-dot 0.8s ease infinite",
        }} />
      </div>
    );
  }

  // Idle dot
  return (
    <div style={{ width: 24, height: 24, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <span style={{
        width: 6, height: 6,
        borderRadius: "50%",
        backgroundColor: "var(--on-surface-faint)",
        animation: "aria-pulse-dot 3s ease infinite",
      }} />
    </div>
  );
}
