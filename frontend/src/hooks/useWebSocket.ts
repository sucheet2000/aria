import { useCallback, useEffect, useRef } from "react";
import { useAriaStore } from "@/store/ariaStore";

const WS_URL = "ws://localhost:8000/ws";
const MAX_BACKOFF_MS = 30_000;

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const { setWsConnected, setVisionState, setGestureState, setTranscript, setIsSpeaking } =
    useAriaStore();

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      attemptRef.current = 0;
      setWsConnected(true);
    };

    ws.onmessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data as string);
        if (data.vision) setVisionState(data.vision);
        if (data.gesture) setGestureState(data.gesture);
        if (data.audio) {
          setTranscript(data.audio.transcript ?? "");
          setIsSpeaking(data.audio.is_speaking ?? false);
        }
      } catch {
        // malformed message — ignore
      }
    };

    ws.onclose = () => {
      setWsConnected(false);
      scheduleReconnect();
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [setWsConnected, setVisionState, setGestureState, setTranscript, setIsSpeaking]);

  const scheduleReconnect = useCallback(() => {
    if (reconnectTimerRef.current) return;
    const backoff = Math.min(1_000 * 2 ** attemptRef.current, MAX_BACKOFF_MS);
    attemptRef.current += 1;
    reconnectTimerRef.current = setTimeout(() => {
      reconnectTimerRef.current = null;
      connect();
    }, backoff);
  }, [connect]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((message: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  return { send };
}
