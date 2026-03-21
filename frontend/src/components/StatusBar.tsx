"use client";

import { useAriaStore } from "@/store/ariaStore";

export default function StatusBar() {
  const wsConnected = useAriaStore((s) => s.wsConnected);
  const emotion = useAriaStore((s) => s.emotion);
  const processingMs = useAriaStore((s) => s.processingMs);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        width: "100%",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span
          style={{
            fontFamily: "var(--font-display)",
            fontWeight: 600,
            fontSize: 18,
            color: "var(--on-surface)",
            letterSpacing: "0.15em",
          }}
        >
          ARIA
        </span>
        <span
          style={{
            display: "inline-block",
            width: 6,
            height: 6,
            borderRadius: "50%",
            backgroundColor: wsConnected ? "#22c55e" : "var(--on-surface-faint)",
            flexShrink: 0,
            animation: wsConnected ? "aria-pulse-dot 2s ease infinite" : "none",
          }}
        />
        <span
          style={{
            fontFamily: "var(--font-data)",
            fontWeight: 400,
            fontSize: 10,
            color: "var(--on-surface-muted)",
            letterSpacing: "0.2em",
            textTransform: "uppercase",
          }}
        >
          {wsConnected ? "LIVE" : "OFFLINE"}
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span
          style={{
            fontFamily: "var(--font-data)",
            fontWeight: 400,
            fontSize: 11,
            color:
              emotion !== "neutral"
                ? "var(--primary)"
                : "var(--on-surface-muted)",
            backgroundColor: "var(--surface-high)",
            borderRadius: 20,
            padding: "4px 12px",
            textTransform: "uppercase",
          }}
        >
          {emotion}
        </span>
        {processingMs > 0 && (
          <span
            style={{
              fontFamily: "var(--font-data)",
              fontWeight: 400,
              fontSize: 11,
              color: "var(--on-surface-faint)",
            }}
          >
            {(processingMs / 1000).toFixed(1)}s
          </span>
        )}
      </div>
    </div>
  );
}
