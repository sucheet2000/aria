import { describe, it, expect } from "vitest";
import type { PerceptionFrame } from "@/store/ariaStore";
import {
  buildCognitionVisionState,
  VISION_FRAME_MAX_AGE_MS,
} from "./cognitionVisionState";

const NOW_MS = 1_700_000_000_000;

function frame(overrides: Partial<PerceptionFrame> = {}): PerceptionFrame {
  return {
    face_landmarks: [[0.5, 0.5, 0]],
    emotion: "happy",
    emotion_confidence: 0.85,
    head_pose: { pitch: 1, yaw: 2, roll: 3 },
    hand_landmarks: [],
    timestamp: NOW_MS / 1000,
    ...overrides,
  };
}

describe("buildCognitionVisionState", () => {
  it("omits emotion_confidence when there is no frame", () => {
    const out = buildCognitionVisionState(null, NOW_MS);
    expect(out).toEqual({
      emotion: "neutral",
      pitch: 0,
      yaw: 0,
      roll: 0,
      face_detected: false,
      hands_detected: false,
    });
    expect("emotion_confidence" in out).toBe(false);
    expect(JSON.stringify(out)).not.toContain("emotion_confidence");
  });

  it("treats a stale frame as perception unavailable", () => {
    const stale = frame({ timestamp: (NOW_MS - 3000) / 1000 });
    const out = buildCognitionVisionState(stale, NOW_MS);
    expect(out.emotion).toBe("neutral");
    expect(out.face_detected).toBe(false);
    expect("emotion_confidence" in out).toBe(false);
  });

  it("accepts a frame just inside the max age", () => {
    const fresh = frame({ timestamp: (NOW_MS - VISION_FRAME_MAX_AGE_MS + 1) / 1000 });
    const out = buildCognitionVisionState(fresh, NOW_MS);
    expect(out.emotion).toBe("happy");
    expect(out.face_detected).toBe(true);
  });

  it("reports neutral with confidence 0 when no face is in the frame", () => {
    const noFace = frame({ face_landmarks: [] });
    const out = buildCognitionVisionState(noFace, NOW_MS);
    expect(out.emotion).toBe("neutral");
    expect(out.emotion_confidence).toBe(0);
    expect(out.face_detected).toBe(false);
  });

  it("forwards the measured emotion and confidence for a fresh face frame", () => {
    const out = buildCognitionVisionState(frame({ emotion_confidence: 0.83 }), NOW_MS);
    expect(out.emotion).toBe("happy");
    expect(out.emotion_confidence).toBe(0.83);
    expect(out.pitch).toBe(1);
    expect(out.yaw).toBe(2);
    expect(out.roll).toBe(3);
    expect(out.face_detected).toBe(true);
    expect(out.hands_detected).toBe(false);
  });

  it("reports hands_detected from hand landmarks", () => {
    const out = buildCognitionVisionState(frame({ hand_landmarks: [[0.1, 0.2, 0]] }), NOW_MS);
    expect(out.hands_detected).toBe(true);
  });

  it("clamps confidence into [0, 1]", () => {
    expect(buildCognitionVisionState(frame({ emotion_confidence: 1.2 }), NOW_MS).emotion_confidence).toBe(1);
    expect(buildCognitionVisionState(frame({ emotion_confidence: -0.2 }), NOW_MS).emotion_confidence).toBe(0);
  });

  it("omits emotion_confidence when the frame value is missing or not finite", () => {
    const missing = buildCognitionVisionState(frame({ emotion_confidence: undefined }), NOW_MS);
    expect("emotion_confidence" in missing).toBe(false);
    expect(missing.emotion).toBe("happy");

    const nan = buildCognitionVisionState(frame({ emotion_confidence: NaN }), NOW_MS);
    expect("emotion_confidence" in nan).toBe(false);
  });
});
