"use client";

import { useAriaStore } from "@/store/ariaStore";

const EMOTION_COLORS: Record<string, string> = {
  neutral: "#64748b",
  happy: "#22c55e",
  sad: "#3b82f6",
  angry: "#ef4444",
  surprised: "#f59e0b",
  fearful: "#8b5cf6",
  disgusted: "#84cc16",
};

function colorForEmotion(emotion: string): string {
  return EMOTION_COLORS[emotion] ?? EMOTION_COLORS["neutral"];
}

export default function Avatar3D() {
  const avatarEmotion = useAriaStore((s) => s.avatarEmotion);
  const color = colorForEmotion(avatarEmotion);

  return (
    <div className="flex h-full w-full items-center justify-center rounded-2xl border border-aria-accent/20 bg-aria-surface">
      <div className="text-center">
        <p
          className="text-3xl font-bold"
          style={{ color, transition: "color 0.5s ease" }}
        >
          ARIA [{avatarEmotion}]
        </p>
        <p className="text-sm text-aria-muted mt-2">3D avatar renders in v0.7.0</p>
      </div>
    </div>
  );
}
