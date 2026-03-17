"use client";

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

interface EmotionIndicatorProps {
  emotion: string;
  confidence: number;
  size?: "sm" | "md";
}

export default function EmotionIndicator({
  emotion,
  confidence,
  size = "md",
}: EmotionIndicatorProps) {
  const circleSize = size === "sm" ? 8 : 12;
  const fontSize = size === "sm" ? 11 : 13;
  const color = colorForEmotion(emotion);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span
        style={{
          display: "inline-block",
          width: circleSize,
          height: circleSize,
          borderRadius: "50%",
          backgroundColor: color,
          flexShrink: 0,
        }}
      />
      <span style={{ fontSize, color: "#cbd5e1" }}>
        {emotion}
        {confidence > 0 && (
          <span style={{ color: "#64748b", marginLeft: 4 }}>
            {Math.round(confidence * 100)}%
          </span>
        )}
      </span>
    </div>
  );
}
