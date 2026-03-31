import { useCallback, useEffect, useRef } from "react";
import { useAriaStore } from "@/store/ariaStore";
import { abortCognitionRef } from "@/hooks/useCognition";

export const wsSendRef: { current: ((data: object) => void) | null } = { current: null };

const WS_URL = "ws://localhost:8080/ws";
const INITIAL_DELAY_MS = 1000;
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
      ) {
        console.log(`[useWebSocket] skipping connect, readyState=${wsRef.current.readyState}`);
        return;
      }

      console.log(`[useWebSocket] connecting to ${WS_URL}`);
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("[useWebSocket] connected");
        currentDelayRef.current = INITIAL_DELAY_MS;
        useAriaStore.getState().setWsConnected(true);
        useAriaStore.getState().setWsError(null);
      };

      ws.onmessage = (event: MessageEvent) => {
        try {
          const msg = JSON.parse(event.data as string);

          if (msg.type === "aria_sleep") {
            useAriaStore.getState().setIsListening(false);
            useAriaStore.getState().setIsSpeaking(false);
            return;
          }

          if (msg.type === "wake_word") {
            useAriaStore.getState().setIsListening(true);
            setTimeout(() => useAriaStore.getState().setIsListening(false), 2000);
            return;
          }

          if (msg.type === "vision_state" || !msg.type) {
            useAriaStore.getState().setVisionFrame(msg.payload ?? msg);
            return;
          }

          if (msg.type === "aria_interrupt") {
            const currentSessionId = useAriaStore.getState().sessionId;
            if (msg.session_id === "default" || msg.session_id === currentSessionId) {
              abortCognitionRef.current?.();
              window.dispatchEvent(new CustomEvent("aria:interrupt"));
              useAriaStore.getState().setIsSpeaking(false);
              useAriaStore.getState().setIsThinking(false);
            }
            return;
          }

          if (msg.type === "transcript") {
            const t = msg.payload;
            if (t.is_final && t.transcript) {
              useAriaStore.getState().setVoiceTranscript(t.transcript);
              useAriaStore.getState().setVoiceConfidence(t.confidence ?? 0);
              useAriaStore.getState().setIsListening(true);
              setTimeout(() => useAriaStore.getState().setIsListening(false), 2000);
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

      ws.onclose = (ev) => {
        console.log(`[useWebSocket] closed, code=${ev.code} reason=${ev.reason}`);
        useAriaStore.getState().setWsConnected(false);
        scheduleReconnect();
      };

      ws.onerror = (ev) => {
        console.error("[useWebSocket] error", ev);
        useAriaStore.getState().setWsError("connection failed");
      };
    }

    // Delay initial connection to allow the Go server to be ready
    reconnectTimerRef.current = setTimeout(() => {
      reconnectTimerRef.current = null;
      connect();
    }, INITIAL_DELAY_MS);

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

  wsSendRef.current = send;
  return { connected, error, send };
}
