"use client";

import { useState } from "react";
import { useAriaStore } from "@/store/ariaStore";

export const ttsAudioRef: { current: HTMLAudioElement | null } = {
  current: null,
};

export function useTTS() {
  const [isPlaying, setIsPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setIsSpeaking = useAriaStore((s) => s.setIsSpeaking);

  async function speak(text: string): Promise<void> {
    if (!text || isPlaying) return;

    setIsPlaying(true);
    setError(null);

    try {
      const response = await fetch("http://localhost:8080/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
        signal: AbortSignal.timeout(15000),
      });

      if (!response.ok) {
        throw new Error(`TTS request failed: HTTP ${response.status}`);
      }

      const blob = new Blob([await response.arrayBuffer()], { type: "audio/mpeg" });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      ttsAudioRef.current = audio;
      setIsSpeaking(true);

      audio.onended = () => {
        URL.revokeObjectURL(url);
        setIsPlaying(false);
        setIsSpeaking(false);
      };

      audio.onerror = () => {
        URL.revokeObjectURL(url);
        setIsPlaying(false);
        setIsSpeaking(false);
      };

      try {
        await audio.play();
      } catch (err) {
        console.error("[useTTS] play failed:", err);
      }
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "TTS playback failed.";
      setError(msg);
      console.error("[useTTS]", err);
      setIsPlaying(false);
      setIsSpeaking(false);
    }
  }

  return { speak, isPlaying, error };
}
