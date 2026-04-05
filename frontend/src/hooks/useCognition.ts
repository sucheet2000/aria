"use client";

import { useEffect, useRef, useState } from "react";
import { useAriaStore } from "@/store/ariaStore";
import { useWorldModel } from "@/spatial/useWorldModel";
import type { SpatialAnchor } from "@/spatial/useWorldModel";
import { broadcastAnchorAdded } from "@/spatial/useSpatialSync";

// Module-level ref so useWebSocket can abort the in-flight fetch without
// importing useCognition (which would create a circular dependency).
export const abortCognitionRef: { current: (() => void) | null } = { current: null };

interface CognitionResponse {
  natural_language_response: string;
  avatar_emotion: string;
  processing_ms: number;
  symbolic_inference: string;
  world_model_update?: {
    triple: { subject: string; predicate: string; object: string };
    confidence: number;
    source: string;
  } | null;
  spatial_event?: Record<string, unknown> | null;
}

function handleSpatialEvent(event: Record<string, unknown> | null | undefined): void {
  if (!event) return;
  const store = useWorldModel.getState();

  if (event.type === "anchor_registered" && event.anchor) {
    const anchor = event.anchor as SpatialAnchor;
    store.addAnchor(anchor);
    broadcastAnchorAdded(anchor);
  }

  if (event.type === "anchors_bonded" && Array.isArray(event.anchor_ids)) {
    store.setActiveGesture("BOND");
    setTimeout(() => store.setActiveGesture(null), 800);
  }

  if (event.type === "world_expand" && event.factor) {
    store.setActiveGesture("EXPAND");
    setTimeout(() => store.setActiveGesture(null), 600);
  }

  if (event.type === "anchor_thrown" && event.anchor_id && event.velocity) {
    store.setAnchorVelocity(
      event.anchor_id as string,
      event.velocity as [number, number, number]
    );
  }
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
            head_pose: headPose,
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
      if (data.world_model_update) {
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
