"use client";

import { useEffect, useState } from "react";

interface MemoryPanelProps {
  assistantMessageCount: number;
}

export default function MemoryPanel({ assistantMessageCount }: MemoryPanelProps) {
  const [profileFacts, setProfileFacts] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
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
    return () =>
      window.removeEventListener("aria:memory-updated", handleMemoryUpdated);
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
        height: "100%",
        display: "flex",
        flexDirection: "column",
        backgroundColor: "var(--glass-bg)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        borderRight: "1px solid var(--outline-ghost)",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "20px 16px 12px",
          flexShrink: 0,
          borderBottom: "1px solid var(--outline-ghost)",
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-data)",
            fontWeight: 500,
            fontSize: 11,
            color: "var(--on-surface-muted)",
            textTransform: "uppercase",
            letterSpacing: "0.15em",
          }}
        >
          memory
        </span>
        <span
          style={{
            marginLeft: 8,
            fontFamily: "var(--font-data)",
            fontSize: 11,
            color:
              profileFacts.length > 0
                ? "var(--primary)"
                : "var(--on-surface-faint)",
          }}
        >
          {isLoading ? "..." : profileFacts.length}
        </span>
      </div>

      {/* Fact list */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "12px 16px",
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        {isLoading ? (
          <span
            style={{
              fontFamily: "var(--font-data)",
              fontSize: 11,
              color: "var(--on-surface-faint)",
            }}
          >
            loading...
          </span>
        ) : profileFacts.length === 0 ? (
          <span
            style={{
              fontFamily: "var(--font-data)",
              fontSize: 11,
              color: "var(--on-surface-faint)",
              fontStyle: "italic",
            }}
          >
            no facts stored
          </span>
        ) : (
          profileFacts.map((fact, i) => (
            <span
              key={i}
              style={{
                fontFamily: "var(--font-data)",
                fontWeight: 400,
                fontSize: 11,
                color: "var(--on-surface-muted)",
                backgroundColor: "var(--surface-high)",
                borderRadius: 8,
                padding: "6px 12px",
                display: "block",
              }}
            >
              {fact}
            </span>
          ))
        )}
      </div>

      {/* Footer */}
      {lastUpdated !== null && (
        <div
          style={{
            padding: "8px 16px",
            borderTop: "1px solid var(--outline-ghost)",
            flexShrink: 0,
          }}
        >
          <span
            style={{
              fontFamily: "var(--font-data)",
              fontSize: 10,
              color: "var(--on-surface-faint)",
            }}
          >
            {secondsAgo()}
          </span>
        </div>
      )}
    </div>
  );
}
