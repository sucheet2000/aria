"use client";

import { useState, useEffect } from "react";
import Avatar3D from "@/components/Avatar3D";
import ChatPanel from "@/components/ChatPanel";
import MemoryPanel from "@/components/MemoryPanel";
import StatusBar from "@/components/StatusBar";
import VoiceDot from "@/components/VoiceDot";
import { SpatialCanvas } from "@/spatial/SpatialCanvas";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useAriaStore } from "@/store/ariaStore";
import { useCognition } from "@/hooks/useCognition";
import { useTTS } from "@/hooks/useTTS";

type SidebarPanel = "chat" | "memory";

function ChatIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function MemoryIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  );
}

function SpatialIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
    </svg>
  );
}

const SIDEBAR_ITEMS: Array<{ id: SidebarPanel; icon: () => JSX.Element }> = [
  { id: "chat", icon: ChatIcon },
  { id: "memory", icon: MemoryIcon },
];

export default function Home() {
  const [activePanel, setActivePanel] = useState<SidebarPanel | null>(null);
  const [showSpatial, setShowSpatial] = useState(false);
  const conversationHistory = useAriaStore(s => s.conversationHistory);
  const assistantMessageCount = conversationHistory.filter(m => m.role === "assistant").length;
  const isThinking = useAriaStore(s => s.isThinking);
  const { sendMessage } = useCognition();
  const { speak } = useTTS();

  useWebSocket();

  useEffect(() => {
    const handler = (e: Event) => {
      const text = (e as CustomEvent<{ transcript: string }>).detail.transcript;
      if (text && !isThinking) sendMessage(text, speak);
    };
    window.addEventListener("aria:voice-transcript", handler);
    return () => window.removeEventListener("aria:voice-transcript", handler);
  }, [sendMessage, speak, isThinking]);

  function togglePanel(id: SidebarPanel) {
    setActivePanel(prev => prev === id ? null : id);
  }

  return (
    <main style={{
      position: "relative",
      width: "100vw",
      height: "100dvh",
      overflow: "hidden",
      backgroundColor: "var(--void)",
    }}>
      {/* Ambient glow */}
      <div style={{
        position: "absolute",
        top: "50%", left: "50%",
        transform: "translate(-50%, -50%)",
        width: 600, height: 600,
        background: "radial-gradient(circle, rgba(99,102,241,0.06) 0%, transparent 70%)",
        pointerEvents: "none",
        zIndex: 0,
        animation: "aria-ambient-pulse 4s ease-in-out infinite",
      }} />

      {/* Avatar + spatial split layout */}
      <div style={{
        position: "absolute",
        top: 0, right: 0, bottom: 0, left: 0,
        zIndex: 1,
        display: "flex",
      }}>
        {/* Avatar — shrinks when spatial is open */}
        <div style={{
          flex: showSpatial ? "0 0 50%" : "1 1 100%",
          position: "relative",
          transition: "flex 0.3s ease",
        }}>
          <Avatar3D />
        </div>

        {/* Spatial canvas panel */}
        {showSpatial && (
          <div style={{
            flex: "0 0 50%",
            position: "relative",
            borderLeft: "1px solid var(--outline-ghost)",
            background: "#000",
            animation: "aria-fade-up 0.2s ease forwards",
          }}>
            <SpatialCanvas />
          </div>
        )}
      </div>

      {/* Top status bar */}
      <header style={{
        position: "absolute",
        top: 0, left: 0, right: 0,
        height: 56,
        zIndex: 10,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 24px",
        background: "linear-gradient(to bottom, rgba(14,14,18,0.8), transparent)",
      }}>
        <StatusBar />
      </header>

      {/* Left icon sidebar */}
      <nav style={{
        position: "absolute",
        left: 0, top: 56, bottom: 0,
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
      }}>
        {SIDEBAR_ITEMS.map(({ id, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => togglePanel(id)}
            className={`sidebar-btn${activePanel === id ? " sidebar-btn-active" : ""}`}
          >
            <Icon />
          </button>
        ))}

        {/* Spatial toggle */}
        <button
          type="button"
          onClick={() => setShowSpatial(prev => !prev)}
          className={`sidebar-btn${showSpatial ? " sidebar-btn-active" : ""}`}
          title="Toggle spatial canvas"
        >
          <SpatialIcon />
        </button>
      </nav>

      {/* Slide-out log panel — chat */}
      {activePanel === "chat" && (
        <div style={{
          position: "absolute",
          left: 60, top: 56, bottom: 0,
          width: 320,
          zIndex: 20,
          display: "flex",
          flexDirection: "column",
          background: "var(--glass-bg)",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
          borderRight: "1px solid var(--outline-ghost)",
          animation: "aria-fade-up 0.2s ease forwards",
        }}>
          <ChatPanel />
        </div>
      )}

      {/* Slide-out memory panel */}
      {activePanel === "memory" && (
        <div style={{
          position: "absolute",
          left: 60, top: 56, bottom: 0,
          width: 280,
          zIndex: 20,
        }}>
          <MemoryPanel assistantMessageCount={assistantMessageCount} />
        </div>
      )}

      {/* Voice indicator — bottom center */}
      <div style={{
        position: "absolute",
        bottom: 32,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 10,
      }}>
        <VoiceDot />
      </div>
    </main>
  );
}
