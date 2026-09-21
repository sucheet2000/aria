import { useCallback, useEffect, useRef } from "react";
import { useAuth } from "@clerk/nextjs";
import { useAriaStore } from "@/store/ariaStore";
import { abortCognitionRef } from "@/hooks/useCognition";
import { visionCaptureActiveRef } from "@/hooks/visionCaptureState";
import { ttsResyncRef } from "@/hooks/ttsResyncState";
import { WS_URL } from "@/lib/config";
import { parseWsFrame } from "@/lib/wsMessages";

export const wsSendRef: { current: ((data: object) => void) | null } = { current: null };

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

  // Latest Clerk token accessor, held in a ref so the connect effect stays [].
  const { getToken } = useAuth();
  const getTokenRef = useRef(getToken);
  getTokenRef.current = getToken;

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

    async function connect() {
      if (!mountedRef.current) return;
      if (
        wsRef.current?.readyState === WebSocket.OPEN ||
        wsRef.current?.readyState === WebSocket.CONNECTING
      ) {
        console.log(`[useWebSocket] skipping connect, readyState=${wsRef.current.readyState}`);
        return;
      }

      // Browsers can't set headers on a WS handshake, so the Clerk session token
      // travels in the Sec-WebSocket-Protocol header via the subprotocol list
      // (SEC-1: never in the URL, where it leaks into logs/history). The Go
      // server reads the token from the subprotocol and echoes back only the
      // "aria-ws" marker before upgrading.
      const token = await getTokenRef.current?.();
      if (!mountedRef.current) return;

      console.log(`[useWebSocket] connecting to ${WS_URL}`);
      const ws = token
        ? new WebSocket(WS_URL, ["aria-ws", token])
        : new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("[useWebSocket] connected");
        currentDelayRef.current = INITIAL_DELAY_MS;
        useAriaStore.getState().setWsConnected(true);
        useAriaStore.getState().setWsError(null);
        const sessionId = useAriaStore.getState().sessionId;
        if (sessionId) {
          ws.send(JSON.stringify({ type: "session_init", session_id: sessionId }));
        }
        // V3: re-state whether ARIA is currently speaking. This socket carries
        // the mic-suppression control messages, and they are dropped silently
        // while it is down, so every fresh connection has to say what is true
        // now instead of assuming the server still knows.
        ttsResyncRef.current?.();
      };

      ws.onmessage = (event: MessageEvent) => {
        const msg = parseWsFrame(event.data as string);
        if (!msg) return; // parseWsFrame already logged the drop

        switch (msg.type) {
          case "aria_sleep":
            useAriaStore.getState().setIsListening(false);
            useAriaStore.getState().setIsSpeaking(false);
            return;

          case "wake_word":
            useAriaStore.getState().setIsListening(true);
            setTimeout(() => useAriaStore.getState().setIsListening(false), 2000);
            return;

          case "vision_state":
            // Once the browser produces PerceptionFrames locally (Phase A.2a),
            // the local producer is the source of truth — drop server frames.
            if (visionCaptureActiveRef.current) return;
            useAriaStore.getState().setVisionFrame(msg.frame);
            return;

          case "aria_interrupt": {
            const currentSessionId = useAriaStore.getState().sessionId;
            if (msg.sessionId === currentSessionId) {
              abortCognitionRef.current?.();
              window.dispatchEvent(new CustomEvent("aria:interrupt"));
              useAriaStore.getState().setIsSpeaking(false);
              useAriaStore.getState().setIsThinking(false);
            }
            return;
          }

          case "transcript": {
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

          case "anchor_registered":
            window.dispatchEvent(
              new CustomEvent("aria:anchor_registered", { detail: msg.anchor })
            );
            return;
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
