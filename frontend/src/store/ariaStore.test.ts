import { describe, it, expect, beforeEach } from "vitest";
import { useAriaStore } from "./ariaStore";

const initial = useAriaStore.getState();

beforeEach(() => {
  useAriaStore.setState(initial, true);
});

describe("clearVisionFrame", () => {
  it("resets perception fields but leaves avatarEmotion alone (R3 boundary)", () => {
    const s = useAriaStore.getState();
    s.setVisionFrame({
      face_landmarks: [[0.5, 0.5, 0]],
      emotion: "happy",
      emotion_confidence: 0.83,
      head_pose: { pitch: 1, yaw: 2, roll: 3 },
      hand_landmarks: [[0.1, 0.2, 0]],
      timestamp: 123,
    });
    s.setAvatarEmotion("sad");

    useAriaStore.getState().clearVisionFrame();

    const after = useAriaStore.getState();
    expect(after.avatarEmotion).toBe("sad");
    expect(after.visionState).toBeNull();
    expect(after.emotionConfidence).toBe(0);
    expect(after.emotion).toBe("neutral");
    expect(after.faceLandmarks).toEqual([]);
    expect(after.handLandmarks).toEqual([]);
    expect(after.headPose).toEqual({ pitch: 0, yaw: 0, roll: 0 });
    expect(after.lastFrameTimestamp).toBe(0);
  });
});
