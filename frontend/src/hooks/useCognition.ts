"use client";

import { useState } from "react";
import { useAriaStore } from "@/store/ariaStore";

interface CognitionResponse {
  response: string;
  emotion_suggestion: string;
  processing_ms: number;
}

export function useCognition() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const addMessage = useAriaStore((s) => s.addMessage);
  const setAvatarEmotion = useAriaStore((s) => s.setAvatarEmotion);
  const setProcessingMs = useAriaStore((s) => s.setProcessingMs);

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
    } = state;

    addMessage("user", text.trim());
    setIsLoading(true);
    setError(null);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);

    try {
      const res = await fetch("http://localhost:8080/api/cognition", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          message: text.trim(),
          vision_state: {
            emotion,
            head_pose: headPose,
            face_detected: faceLandmarks.length > 0,
            hands_detected: handLandmarks.length > 0,
          },
          conversation_history: conversationHistory,
        }),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data: CognitionResponse = await res.json();
      addMessage("assistant", data.response);
      setAvatarEmotion(data.emotion_suggestion);
      setProcessingMs(data.processing_ms);
      if (onResponse) {
        onResponse(data.response);
      }
    } catch (err) {
      const msg =
        err instanceof Error && err.name === "AbortError"
          ? "Request timed out."
          : "I could not process that request.";
      setError(msg);
      addMessage("assistant", "I could not process that request.");
    } finally {
      clearTimeout(timeoutId);
      setIsLoading(false);
    }
  }

  return { sendMessage, isLoading, error };
}
