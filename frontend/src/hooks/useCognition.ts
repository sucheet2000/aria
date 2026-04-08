"use client";

import { useEffect, useRef, useState } from "react";
import { useAriaStore } from "@/store/ariaStore";
import type { WorldModelUpdate } from "@/store/ariaStore";
import { useWorldModel } from "@/spatial/useWorldModel";
import type { SpatialAnchor } from "@/spatial/useWorldModel";
import { broadcastAnchorAdded } from "@/spatial/useSpatialSync";

// Module-level ref so useWebSocket can abort the in-flight fetch without
// importing useCognition (which would create a circular dependency).
export const abortCognitionRef: { current: (() => void) | null } = { current: null };

interface SpatialEvent {
  event_type: string;
  anchor_id?: string;
  anchor_ids?: string[];
  velocity?: [number, number, number];
  factor?: number;
  label?: string;
  x?: number;
  y?: number;
  z?: number;
}

interface CognitionResponse {
  symbolic_inference: string;
  world_model_update: Record<string, unknown> | null;
  natural_language_response: string;
  avatar_emotion: string;
  processing_ms: number;
  episodic_memory: string[];
  spatial_event: SpatialEvent | null;
}


function handleSpatialEvent(event: SpatialEvent | null | undefined): void {
  if (!event) return;
  const store = useWorldModel.getState();

  if (event.event_type === "anchor_registered" && event.anchor_id) {
    const anchor: SpatialAnchor = {
      anchor_id: event.anchor_id,
      label: event.label ?? "object",
      x: event.x ?? 0,
      y: event.y ?? 0,
      z: event.z ?? 0,
    };
    store.addAnchor(anchor);
    broadcastAnchorAdded(anchor);
  }

  if (event.event_type === "anchors_bonded" && Array.isArray(event.anchor_ids)) {
    store.setActiveGesture("BOND");
    setTimeout(() => store.setActiveGesture(null), 800);
  }

  if (event.event_type === "world_expand" && event.factor) {
    store.setActiveGesture("EXPAND");
    setTimeout(() => store.setActiveGesture(null), 600);
  }

  if (event.event_type === "anchor_thrown" && event.anchor_id && event.velocity) {
    store.setAnchorVelocity(event.anchor_id, event.velocity);
  }
}

function isWorldModelUpdate(obj: unknown): obj is Omit<WorldModelUpdate, "timestamp"> {
  if (!obj || typeof obj !== "object") return false;
  const o = obj as Record<string, unknown>;
  const triple = o.triple as Record<string, unknown> | undefined;
  return (
    typeof triple === "object" &&
    triple !== null &&
    typeof triple.subject === "string" &&
    typeof triple.predicate === "string" &&
    typeof triple.object === "string" &&
    typeof o.confidence === "number" &&
    typeof o.source === "string"
  );
}

export function useCognition() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const interruptedRef = useRef(false);

  const addMessage = useAriaStore((s) => s.addMessage);
  const setAvatarEmotion = useAriaStore((s) => s.setAvatarEmotion);
  const setProcessingMs = useAriaStore((s) => s.setProcessingMs);
  const setIsThinking = useAriaStore((s) => s.setIsThinking);
  const setSymbolicInference = useAriaStore((s) => s.setSymbolicInference);
  const addWorldModelUpdate = useAriaStore((s) => s.addWorldModelUpdate);

  async function sendMessage(
    text: string,
    onResponse?: (responseText: string) => void
  ): Promise<void> {
    if (!text.trim() || isLoading) return;

    const state = useAriaStore.getState();
    const {
      emotion,
      headPose,
      faceLandmarks,
      handLandmarks,
      conversationHistory,
      visionState,
    } = state;

    addMessage("user", text.trim());
    setIsLoading(true);
    setIsThinking(true);
    setError(null);

    const controller = new AbortController();
    abortCognitionRef.current = () => controller.abort();
    const timeoutId = setTimeout(() => controller.abort(), 15000);

    try {
      const res = await fetch("http://localhost:8080/api/cognition", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          message: text.trim(),
          session_id: useAriaStore.getState().sessionId,
          vision_state: {
            emotion,
            pitch: headPose?.pitch ?? 0,
            yaw: headPose?.yaw ?? 0,
            roll: headPose?.roll ?? 0,
            face_detected: faceLandmarks.length > 0,
            hands_detected: handLandmarks.length > 0,
          },
          conversation_history: conversationHistory,
          gesture: visionState?.gesture_name ?? "none",
          two_hand_gesture: visionState?.two_hand_gesture ?? "NONE",
          pointing_vector: visionState?.pointing_vector ?? null,
        }),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data: CognitionResponse = await res.json();
      setIsThinking(false);
      addMessage("assistant", data.natural_language_response);
      setAvatarEmotion(data.avatar_emotion);
      setProcessingMs(data.processing_ms);
      setSymbolicInference(data.symbolic_inference ?? "");
      if (data.world_model_update && isWorldModelUpdate(data.world_model_update)) {
        addWorldModelUpdate({
          ...data.world_model_update,
          timestamp: Date.now(),
        });
      }
      handleSpatialEvent(data.spatial_event);
      window.dispatchEvent(new CustomEvent("aria:memory-updated"));
      if (onResponse) {
        onResponse(data.natural_language_response);
      }
    } catch (err) {
      if (interruptedRef.current) {
        interruptedRef.current = false;
        setIsThinking(false);
        return;
      }
      const msg =
        err instanceof Error && err.name === "AbortError"
          ? "Request timed out."
          : "I could not process that request.";
      setError(msg);
      setIsThinking(false);
      addMessage("assistant", "I could not process that request.");
    } finally {
      clearTimeout(timeoutId);
      abortCognitionRef.current = null;
      setIsLoading(false);
    }
  }

  useEffect(() => {
    function handleInterrupt() {
      interruptedRef.current = true;
      abortCognitionRef.current?.();
      setIsLoading(false);
      setIsThinking(false);
      useAriaStore.getState().setIsSpeaking(false);
    }
    window.addEventListener("aria:interrupt", handleInterrupt);
    return () => window.removeEventListener("aria:interrupt", handleInterrupt);
  }, [setIsThinking]);

  return { sendMessage, isLoading, error };
}
