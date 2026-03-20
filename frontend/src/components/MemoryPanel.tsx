"use client";

import { useEffect, useState } from "react";

interface MemoryPanelProps {
  assistantMessageCount: number;
}

export default function MemoryPanel({ assistantMessageCount }: MemoryPanelProps) {
  const [profileFacts, setProfileFacts] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);

  async function fetchProfileFacts() {
    setIsLoading(true);
    try {
      const res = await fetch("http://localhost:8000/api/memory/profile");
      if (!res.ok) return;
      const data = await res.json();
      const facts: string[] = Array.isArray(data.facts) ? data.facts : [];
      setProfileFacts(facts);
      setLastUpdated(Date.now());
    } catch {
      // silent — memory panel is a developer feature
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    fetchProfileFacts();
  }, []);

  useEffect(() => {
    if (assistantMessageCount > 0) {
      fetchProfileFacts();
    }
  }, [assistantMessageCount]);

  useEffect(() => {
    function handleMemoryUpdated() {
      fetchProfileFacts();
    }
    window.addEventListener("aria:memory-updated", handleMemoryUpdated);
    return () => window.removeEventListener("aria:memory-updated", handleMemoryUpdated);
  }, []);

  function secondsAgo(): string {
    if (lastUpdated === null) return "";
    const secs = Math.round((Date.now() - lastUpdated) / 1000);
    if (secs < 5) return "just now";
    if (secs < 60) return `${secs}s ago`;
    return `${Math.round(secs / 60)}m ago`;
  }

  return (
    <div
      style={{
        borderTop: "1px solid #1e293b",
        backgroundColor: "#0a0a0f",
      }}
    >
      {/* Header row */}
      <button
        type="button"
        onClick={() => setIsExpanded((v) => !v)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          width: "100%",
          padding: "8px 12px",
          background: "none",
          border: "none",
          cursor: "pointer",
          color: "#94a3b8",
          fontSize: "12px",
          textAlign: "left",
        }}
      >
        <span style={{ fontWeight: 500, color: "#cbd5e1" }}>Memory</span>
        <span
          style={{
            backgroundColor: "#1e293b",
            borderRadius: "10px",
            padding: "1px 7px",
            fontSize: "11px",
            color: profileFacts.length > 0 ? "#6366f1" : "#475569",
          }}
        >
          {isLoading ? "..." : profileFacts.length}
        </span>
        {!isExpanded && profileFacts.length > 0 && (
          <span
            style={{
              display: "inline-block",
              width: 6,
              height: 6,
              borderRadius: "50%",
              backgroundColor: "#22c55e",
              marginLeft: "2px",
            }}
          />
        )}
        <span style={{ marginLeft: "auto", fontSize: "10px", color: "#475569" }}>
          {isExpanded ? "▲" : "▼"}
        </span>
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div
          style={{
            maxHeight: "180px",
            overflowY: "auto",
            padding: "0 12px 10px",
          }}
        >
          <p style={{ fontSize: "11px", color: "#475569", marginBottom: "8px", fontWeight: 500 }}>
            Profile facts
          </p>
          {profileFacts.length === 0 ? (
            <p style={{ fontSize: "12px", color: "#334155", fontStyle: "italic" }}>
              No facts stored yet
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              {profileFacts.map((fact, i) => (
                <span
                  key={i}
                  style={{
                    display: "inline-block",
                    backgroundColor: "#0f172a",
                    border: "0.5px solid #334155",
                    color: "#94a3b8",
                    fontSize: "12px",
                    padding: "4px 10px",
                    borderRadius: "12px",
                  }}
                >
                  {fact}
                </span>
              ))}
            </div>
          )}
          {lastUpdated !== null && (
            <p style={{ fontSize: "11px", color: "#334155", marginTop: "8px" }}>
              Last updated: {secondsAgo()}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
