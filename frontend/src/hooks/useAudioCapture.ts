"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { AUDIO_WS_URL } from "@/lib/config";
import { isTtsCaptureSuppressed } from "./ttsSpeakingState";
import {
  PcmDownsampler,
  floatTo16BitPCM,
  FRAME_SAMPLES,
  TARGET_SAMPLE_RATE,
} from "@/lib/audio/pcm";

const WORKLET_PATH = "/audio/pcm-worklet.js";
const WORKLET_NAME = "pcm-capture-processor";

const INITIAL_DELAY_MS = 1000;
const MAX_DELAY_MS = 30_000;
const BACKOFF_MULTIPLIER = 1.5;
const JITTER_FACTOR = 0.2;

const AUDIO_CONSTRAINTS: MediaStreamConstraints = {
  audio: {
    channelCount: 1,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
};

export interface UseAudioCaptureResult {
  active: boolean;
  error: string | null;
}

function mapErrorMessage(err: unknown): string {
  if (err instanceof Error) {
    if (err.name === "NotAllowedError" || err.name === "SecurityError") {
      return "Microphone permission denied";
    }
    if (err.name === "NotFoundError" || err.name === "DevicesNotFoundError") {
      return "No microphone found";
    }
    if (err.name === "NotReadableError") {
      return "Microphone is in use by another application";
    }
    return err.message || "Microphone capture failed";
  }
  return "Microphone capture failed";
}

// Browser producer for the server's STT/VAD pipeline (A.2b-1). Captures the mic,
// downsamples to 16 kHz mono Int16 PCM, and streams ~20 ms frames over a
// dedicated /ws/audio WebSocket. STT / wake-word / VAD remain server-side and
// consume this stream (A.2b-2). Transcripts still arrive over the MAIN WS.
export function useAudioCapture(enabled: boolean): UseAudioCaptureResult {
  const [active, setActive] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { getToken } = useAuth();
  const getTokenRef = useRef(getToken);
  getTokenRef.current = getToken;

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;
    let stream: MediaStream | null = null;
    let audioContext: AudioContext | null = null;
    let sourceNode: MediaStreamAudioSourceNode | null = null;
    let workletNode: AudioWorkletNode | null = null;
    let downsampler: PcmDownsampler | null = null;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let currentDelay = INITIAL_DELAY_MS;
    let pending = new Int16Array(0);
    let reacquiring = false;
    let activeTrack: MediaStreamTrack | null = null;

    function scheduleReconnect(): void {
      if (cancelled || reconnectTimer) return;
      const jitter = 1 + Math.random() * JITTER_FACTOR;
      const delay = Math.min(currentDelay * jitter, MAX_DELAY_MS);
      currentDelay = Math.min(currentDelay * BACKOFF_MULTIPLIER, MAX_DELAY_MS);
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        void connectWs();
      }, delay);
    }

    async function connectWs(): Promise<void> {
      if (cancelled) return;
      if (
        ws?.readyState === WebSocket.OPEN ||
        ws?.readyState === WebSocket.CONNECTING
      ) {
        return;
      }

      // Same SEC-1 handshake as the main WS: the Clerk token rides the
      // Sec-WebSocket-Protocol header, never the URL. No token -> dev path.
      const token = await getTokenRef.current?.();
      if (cancelled) return;

      const socket = token
        ? new WebSocket(AUDIO_WS_URL, ["aria-ws", token])
        : new WebSocket(AUDIO_WS_URL);
      socket.binaryType = "arraybuffer";
      ws = socket;

      socket.onopen = () => {
        currentDelay = INITIAL_DELAY_MS;
      };
      // The server's /ws/audio endpoint may be absent (A.2b-2 not shipped) —
      // treat any close as transient and retry with backoff. No crash.
      socket.onclose = () => {
        if (!cancelled) scheduleReconnect();
      };
      socket.onerror = () => {
        // onclose fires next and drives the reconnect; nothing fatal here.
      };
    }

    function handleSamples(block: Float32Array): void {
      if (!downsampler || block.length === 0) return;

      const resampled = downsampler.process(block);
      if (resampled.length === 0) return;
      const int16 = floatTo16BitPCM(resampled);

      const merged = new Int16Array(pending.length + int16.length);
      merged.set(pending);
      merged.set(int16, pending.length);
      pending = merged;

      while (pending.length >= FRAME_SAMPLES) {
        const frame = new Int16Array(pending.subarray(0, FRAME_SAMPLES));
        pending = new Int16Array(pending.subarray(FRAME_SAMPLES));
        // V3.1: while ARIA is audibly speaking, drop the frame here rather than
        // send it and rely on the server to discard it. The server gate is
        // driven by a control message on a DIFFERENT socket, which is dropped
        // silently whenever that socket is down — so this is the only point
        // where the guarantee holds regardless of the network. The frame is
        // still sliced off `pending` so the buffer drains normally, and the
        // MediaStream, worklet and socket are all left untouched.
        if (isTtsCaptureSuppressed()) continue;
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(frame.buffer);
        }
      }
    }

    function attachTrackListeners(media: MediaStream): void {
      activeTrack = media.getAudioTracks?.()[0] ?? media.getTracks()[0] ?? null;
      // Follow the OS default: if this device permanently ends (e.g. the user
      // unplugs earphones), re-acquire whatever became the new default input.
      activeTrack?.addEventListener?.("ended", onTrackLost);
    }

    function detachTrackListeners(): void {
      activeTrack?.removeEventListener?.("ended", onTrackLost);
      activeTrack = null;
    }

    function onTrackLost(): void {
      void reacquire();
    }

    function onDeviceChange(): void {
      void reacquire();
    }

    // getUserMedia binds a fixed device at start; when the OS default changes
    // (earphones unplugged, dock removed, …) that track goes silent and never
    // switches on its own. Rebuild only the mic-bound half of the graph against
    // the new default, reusing the existing AudioContext / worklet / WebSocket /
    // backoff. The reacquiring guard collapses duplicate devicechange bursts.
    async function reacquire(): Promise<void> {
      if (cancelled || reacquiring) return;
      if (!audioContext || !workletNode) return;
      reacquiring = true;
      try {
        detachTrackListeners();
        sourceNode?.disconnect();
        sourceNode = null;
        stream?.getTracks().forEach((t) => t.stop());
        stream = null;
        pending = new Int16Array(0);
        downsampler = new PcmDownsampler(audioContext.sampleRate, TARGET_SAMPLE_RATE);

        const media = await navigator.mediaDevices.getUserMedia(AUDIO_CONSTRAINTS);
        if (cancelled) {
          media.getTracks().forEach((t) => t.stop());
          return;
        }
        stream = media;
        sourceNode = audioContext.createMediaStreamSource(media);
        sourceNode.connect(workletNode);
        attachTrackListeners(media);
        setError(null);
      } catch (err) {
        if (!cancelled) setError(mapErrorMessage(err));
      } finally {
        reacquiring = false;
      }
    }

    async function start(): Promise<void> {
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error("Microphone not supported in this browser");
        }

        stream = await navigator.mediaDevices.getUserMedia(AUDIO_CONSTRAINTS);
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          stream = null;
          return;
        }

        audioContext = new AudioContext();
        downsampler = new PcmDownsampler(audioContext.sampleRate, TARGET_SAMPLE_RATE);
        if (audioContext.state === "suspended") await audioContext.resume();

        await audioContext.audioWorklet.addModule(WORKLET_PATH);
        if (cancelled) return;

        sourceNode = audioContext.createMediaStreamSource(stream);
        workletNode = new AudioWorkletNode(audioContext, WORKLET_NAME);
        workletNode.port.onmessage = (ev: MessageEvent) => {
          const data = ev.data as Float32Array;
          if (data?.length) handleSamples(data);
        };
        sourceNode.connect(workletNode);
        // Route to destination so the graph pulls the processor; it outputs
        // silence, so this never feeds the mic back to the speakers.
        workletNode.connect(audioContext.destination);

        attachTrackListeners(stream);
        navigator.mediaDevices.addEventListener?.("devicechange", onDeviceChange);

        void connectWs();
        setActive(true);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(mapErrorMessage(err));
        setActive(false);
      }
    }

    void start();

    return () => {
      cancelled = true;
      navigator.mediaDevices?.removeEventListener?.("devicechange", onDeviceChange);
      detachTrackListeners();
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (workletNode) {
        workletNode.port.onmessage = null;
        workletNode.disconnect();
      }
      sourceNode?.disconnect();
      stream?.getTracks().forEach((t) => t.stop());
      if (ws) {
        ws.onclose = null;
        ws.onerror = null;
        ws.close();
      }
      audioContext?.close();
      setActive(false);
    };
  }, [enabled]);

  return { active, error };
}
