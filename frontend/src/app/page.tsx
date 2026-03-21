"use client";

import { useState } from "react";
import Avatar3D from "@/components/Avatar3D";
import CameraFeed from "@/components/CameraFeed";
import ChatPanel from "@/components/ChatPanel";
import MemoryPanel from "@/components/MemoryPanel";
import StatusBar from "@/components/StatusBar";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useAriaStore } from "@/store/ariaStore";

type SidebarPanel = "chat" | "memory" | "vision" | "settings";

function ChatIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function MemoryIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  );
}

function VisionIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

const SIDEBAR_ITEMS: Array<{ id: SidebarPanel; icon: () => JSX.Element }> = [
  { id: "chat", icon: ChatIcon },
  { id: "memory", icon: MemoryIcon },
  { id: "vision", icon: VisionIcon },
  { id: "settings", icon: SettingsIcon },
];

export default function Home() {
  const [activePanel, setActivePanel] = useState<SidebarPanel>("chat");

  useWebSocket();

  const conversationHistory = useAriaStore((s) => s.conversationHistory);

  const assistantMessageCount = conversationHistory.filter(
    (m) => m.role === "assistant"
  ).length;

  return (
    <main
      style={{
        position: "relative",
        width: "100vw",
        height: "100dvh",
        overflow: "hidden",
        backgroundColor: "var(--void)",
      }}
    >
      {/* Ambient glow behind avatar */}
      <div
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 600,
          height: 600,
          background:
            "radial-gradient(circle, rgba(99,102,241,0.06) 0%, transparent 70%)",
          pointerEvents: "none",
          zIndex: 0,
          animation: "aria-ambient-pulse 4s ease-in-out infinite",
        }}
      />

      {/* Full-bleed avatar — centered behind everything */}
      <div
        style={{
          position: "absolute",
          top: 0,
          right: 0,
          bottom: 0,
          left: 0,
          zIndex: 1,
        }}
      >
        <Avatar3D />
      </div>

      {/* Top status bar */}
      <header
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 56,
          zIndex: 10,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 24px",
          background:
            "linear-gradient(to bottom, rgba(14,14,18,0.8), transparent)",
        }}
      >
        <StatusBar />
      </header>

      {/* Left icon sidebar */}
      <nav
        style={{
          position: "absolute",
          left: 0,
          top: 56,
          bottom: 0,
          width: 60,
          zIndex: 10,
          background: "var(--glass-bg)",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
          borderRight: "1px solid var(--outline-ghost)",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          paddingTop: 24,
          gap: 24,
        }}
      >
        {SIDEBAR_ITEMS.map(({ id, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setActivePanel(id)}
            className={`sidebar-btn${activePanel === id ? " sidebar-btn-active" : ""}`}
          >
            <Icon />
          </button>
        ))}
      </nav>

      {/* Memory panel overlay */}
      {activePanel === "memory" && (
        <div
          style={{
            position: "absolute",
            left: 60,
            top: 56,
            bottom: 0,
            width: 280,
            zIndex: 20,
          }}
        >
          <MemoryPanel assistantMessageCount={assistantMessageCount} />
        </div>
      )}

      {/* Bottom conversation panel */}
      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 60,
          right: 0,
          height: "45vh",
          background: "var(--glass-bg)",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
          borderTop: "1px solid var(--outline-ghost)",
          zIndex: 10,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <ChatPanel />
      </div>

      {/* Camera feed — small floating card */}
      <div
        style={{
          position: "absolute",
          top: 72,
          right: 20,
          width: 160,
          height: 120,
          borderRadius: 16,
          overflow: "hidden",
          border: "1px solid var(--outline-ghost)",
          zIndex: 11,
        }}
      >
        <CameraFeed />
      </div>
    </main>
  );
}
