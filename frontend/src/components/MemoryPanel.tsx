"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { API_BASE } from "@/lib/config";
import { useAriaStore } from "@/store/ariaStore";

interface MemoryPanelProps {
  assistantMessageCount: number;
}

const controlTextStyle: React.CSSProperties = {
  fontFamily: "var(--font-data)",
  fontSize: 11,
  color: "var(--on-surface-muted)",
};

const controlButtonStyle: React.CSSProperties = {
  ...controlTextStyle,
  background: "none",
  border: "none",
  padding: 0,
  cursor: "pointer",
  textDecoration: "underline",
  textAlign: "left",
};

export default function MemoryPanel({ assistantMessageCount }: MemoryPanelProps) {
  const { getToken } = useAuth();
  const [profileFacts, setProfileFacts] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteStatus, setDeleteStatus] = useState("");
  const [isExporting, setIsExporting] = useState(false);

  const EXPORT_PAGE = 500;

  interface MemoryExportPage {
    profile: unknown[];
    episodic: unknown[];
    working: unknown[];
    truncated: string[];
  }

  // Fetches every page of /api/memory/export (the edge caps each collection
  // at 500 per page) and hands the merged JSON to the browser as a download.
  async function exportMyData() {
    setIsExporting(true);
    setDeleteStatus("");
    try {
      const token = await getToken();
      const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
      const merged: MemoryExportPage = { profile: [], episodic: [], working: [], truncated: [] };
      let offset = 0;
      for (;;) {
        const res = await fetch(`${API_BASE}/api/memory/export?offset=${offset}`, { headers });
        if (!res.ok) {
          setDeleteStatus("could not export memory");
          return;
        }
        const page = (await res.json()) as MemoryExportPage;
        merged.profile.push(...(page.profile ?? []));
        merged.episodic.push(...(page.episodic ?? []));
        merged.working.push(...(page.working ?? []));
        if (!Array.isArray(page.truncated) || page.truncated.length === 0) break;
        offset += EXPORT_PAGE;
      }
      const blob = new Blob([JSON.stringify(merged, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "aria-memory-export.json";
      link.click();
      URL.revokeObjectURL(url);
      setDeleteStatus("memory exported");
    } catch {
      setDeleteStatus("could not export memory");
    } finally {
      setIsExporting(false);
    }
  }

  async function deleteAllMemory() {
    setIsDeleting(true);
    setDeleteStatus("");
    try {
      const token = await getToken();
      const res = await fetch(`${API_BASE}/api/memory`, {
        method: "DELETE",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) {
        setDeleteStatus("could not delete memory");
        return;
      }
      setProfileFacts([]);
      // Old replies in the transcript could re-state deleted facts on the
      // next turn (history is sent to the model), so drop them too.
      useAriaStore.getState().clearConversation();
      setLastUpdated(Date.now());
      setIsConfirmingDelete(false);
      setDeleteStatus("memory deleted");
      window.dispatchEvent(new CustomEvent("aria:memory-updated"));
    } catch {
      setDeleteStatus("could not delete memory");
    } finally {
      setIsDeleting(false);
    }
  }

  async function fetchProfileFacts() {
    setIsLoading(true);
    try {
      const token = await getToken();
      const res = await fetch(`${API_BASE}/api/memory/profile`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
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

      {/* Delete all memory */}
      <div
        style={{
          padding: "8px 16px",
          borderTop: "1px solid var(--outline-ghost)",
          flexShrink: 0,
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        {isConfirmingDelete ? (
          <>
            <span style={controlTextStyle}>
              delete everything ARIA remembers about you?
            </span>
            <div style={{ display: "flex", gap: 12 }}>
              <button
                type="button"
                onClick={deleteAllMemory}
                disabled={isDeleting}
                style={controlButtonStyle}
              >
                yes, delete
              </button>
              <button
                type="button"
                onClick={() => setIsConfirmingDelete(false)}
                disabled={isDeleting}
                style={controlButtonStyle}
              >
                cancel
              </button>
            </div>
          </>
        ) : (
          <div style={{ display: "flex", gap: 12 }}>
            <button
              type="button"
              onClick={exportMyData}
              disabled={isExporting}
              style={controlButtonStyle}
            >
              export my data
            </button>
            <button
              type="button"
              onClick={() => {
                setDeleteStatus("");
                setIsConfirmingDelete(true);
              }}
              style={controlButtonStyle}
            >
              delete all memory
            </button>
          </div>
        )}
        <span role="status" aria-live="polite" style={controlTextStyle}>
          {deleteStatus}
        </span>
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
