import type { PerceptionFrame } from "@/store/ariaStore";

// Builds the `vision_state` block of the cognition request from the latest
// perception frame. `emotion_confidence` is the classifier's heuristic score in
// [0, 1] (not a calibrated probability). It is ABSENT when perception is
// unavailable (no frame, or a frame older than VISION_FRAME_MAX_AGE_MS) and 0
// when a frame was measured but no face was found. It is never fabricated here.

export const VISION_FRAME_MAX_AGE_MS = 2000;

export interface CognitionVisionState {
  emotion: string;
  emotion_confidence?: number;
  pitch: number;
  yaw: number;
  roll: number;
  face_detected: boolean;
  hands_detected: boolean;
}

const UNAVAILABLE: CognitionVisionState = {
  emotion: "neutral",
  pitch: 0,
  yaw: 0,
  roll: 0,
  face_detected: false,
  hands_detected: false,
};

function isStale(frame: PerceptionFrame, nowMs: number): boolean {
  return nowMs / 1000 - frame.timestamp > VISION_FRAME_MAX_AGE_MS / 1000;
}

export function buildCognitionVisionState(
  frame: PerceptionFrame | null,
  nowMs: number,
): CognitionVisionState {
  if (!frame || isStale(frame, nowMs)) return { ...UNAVAILABLE };

  const faceDetected = frame.face_landmarks.length > 0;
  const handsDetected = frame.hand_landmarks.length > 0;
  const base = {
    pitch: frame.head_pose.pitch,
    yaw: frame.head_pose.yaw,
    roll: frame.head_pose.roll,
    face_detected: faceDetected,
    hands_detected: handsDetected,
  };

  if (!faceDetected) return { emotion: "neutral", emotion_confidence: 0, ...base };

  const raw = frame.emotion_confidence;
  const hasConfidence = typeof raw === "number" && Number.isFinite(raw);
  return {
    emotion: frame.emotion,
    ...(hasConfidence ? { emotion_confidence: Math.max(0, Math.min(1, raw)) } : {}),
    ...base,
  };
}
