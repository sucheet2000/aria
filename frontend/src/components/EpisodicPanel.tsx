"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { API_BASE } from "@/lib/config";

interface EpisodicPanelProps {
  assistantMessageCount: number;
}

export default function EpisodicPanel({ assistantMessageCount }: EpisodicPanelProps) {
  const { getToken } = useAuth();
  const [memories, setMemories] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);

  async function fetchEpisodicMemories() {
    setIsLoading(true);
    try {
      const token = await getToken();
      const res = await fetch(`${API_BASE}/api/memory/episodic`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) return;
      const data = await res.json();
      const facts: string[] = Array.isArray(data.facts) ? data.facts : [];
      setMemories(facts);
      setLastUpdated(Date.now());
    } catch {
      // silent — memory panel is a developer feature
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    fetchEpisodicMemories();
  }, []);

  useEffect(() => {
    if (assistantMessageCount > 0) {
      fetchEpisodicMemories();
    }
  }, [assistantMessageCount]);

  useEffect(() => {
    function handleMemoryUpdated() {
      fetchEpisodicMemories();
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
          episodic memory
        </span>
        <span
          style={{
            marginLeft: 8,
            fontFamily: "var(--font-data)",
            fontSize: 11,
            color:
              memories.length > 0
                ? "var(--primary)"
                : "var(--on-surface-faint)",
          }}
        >
          {isLoading ? "..." : memories.length}
        </span>
      </div>

      {/* Memory list */}
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
        ) : memories.length === 0 ? (
          <span
            style={{
              fontFamily: "var(--font-data)",
              fontSize: 11,
              color: "var(--on-surface-faint)",
              fontStyle: "italic",
            }}
          >
            no memories yet
          </span>
        ) : (
          memories.map((memory, i) => (
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
              {memory}
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
