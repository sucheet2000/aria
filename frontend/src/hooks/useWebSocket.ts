import { useCallback, useEffect, useRef } from "react";
import { useAriaStore } from "@/store/ariaStore";

const WS_URL = "ws://localhost:8080/ws";
const INITIAL_DELAY_MS = 500;
const MAX_DELAY_MS = 30_000;
const BACKOFF_MULTIPLIER = 1.5;
const JITTER_FACTOR = 0.2;

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentDelayRef = useRef(INITIAL_DELAY_MS);
  const mountedRef = useRef(true);

  const connected = useAriaStore((s) => s.wsConnected);
  const error = useAriaStore((s) => s.wsError);

  useEffect(() => {
    mountedRef.current = true;

    function scheduleReconnect() {
      if (!mountedRef.current) return;
      if (reconnectTimerRef.current) return;
      const jitter = 1 + Math.random() * JITTER_FACTOR;
      const delay = Math.min(currentDelayRef.current * jitter, MAX_DELAY_MS);
      currentDelayRef.current = Math.min(
        currentDelayRef.current * BACKOFF_MULTIPLIER,
        MAX_DELAY_MS
      );
      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null;
        connect();
      }, delay);
    }

    function connect() {
      if (!mountedRef.current) return;
      if (
        wsRef.current?.readyState === WebSocket.OPEN ||
        wsRef.current?.readyState === WebSocket.CONNECTING
      )
        return;

      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        currentDelayRef.current = INITIAL_DELAY_MS;
        useAriaStore.getState().setWsConnected(true);
        useAriaStore.getState().setWsError(null);
      };

      ws.onmessage = (event: MessageEvent) => {
        try {
          const msg = JSON.parse(event.data as string);

          if (msg.type === "vision_state" || !msg.type) {
            useAriaStore.getState().setVisionFrame(msg.payload ?? msg);
            return;
          }

          if (msg.type === "transcript") {
            const t = msg.payload;
            if (t.is_final && t.transcript) {
              useAriaStore.getState().setVoiceTranscript(t.transcript);
              useAriaStore.getState().setVoiceConfidence(t.confidence ?? 0);
              window.dispatchEvent(
                new CustomEvent("aria:voice-transcript", {
                  detail: { transcript: t.transcript },
                })
              );
            }
            return;
          }
        } catch {
          // malformed message -- ignore
        }
      };

      ws.onclose = () => {
        useAriaStore.getState().setWsConnected(false);
        scheduleReconnect();
      };

      ws.onerror = () => {
        console.error("[useWebSocket] connection failed");
        useAriaStore.getState().setWsError("connection failed");
      };
    }

    connect();

    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, []);

  const send = useCallback((data: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  return { connected, error, send };
}
