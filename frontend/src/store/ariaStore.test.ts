import { describe, it, expect, beforeEach } from "vitest";
import { useAriaStore } from "./ariaStore";
import type { PerceptionFrame } from "./ariaStore";

const initial = useAriaStore.getState();

beforeEach(() => {
  useAriaStore.setState(initial, true);
});

function frame(emotion: string, overrides: Partial<PerceptionFrame> = {}): PerceptionFrame {
  return {
    face_landmarks: [[0.5, 0.5, 0]],
    emotion,
    emotion_confidence: 0.9,
    head_pose: { pitch: 1, yaw: 2, roll: 3 },
    hand_landmarks: [[0.1, 0.2, 0]],
    timestamp: 123,
    ...overrides,
  };
}

describe("avatarEmotion ownership (R3)", () => {
  it("starts at the neutral default before any cognition response", () => {
    expect(useAriaStore.getState().avatarEmotion).toBe("neutral");
  });

  it("setVisionFrame updates perception state but never avatarEmotion", () => {
    useAriaStore.getState().setVisionFrame(frame("happy"));

    const s = useAriaStore.getState();
    expect(s.emotion).toBe("happy");
    expect(s.emotionConfidence).toBe(0.9);
    expect(s.visionState?.emotion).toBe("happy");
    expect(s.headPose).toEqual({ pitch: 1, yaw: 2, roll: 3 });
    expect(s.avatarEmotion).toBe("neutral");
  });

  it("a no-face frame leaves avatarEmotion untouched", () => {
    useAriaStore.getState().setAvatarEmotion("sad");
    useAriaStore.getState().setVisionFrame(
      frame("neutral", { face_landmarks: [], emotion_confidence: 0 }),
    );
    expect(useAriaStore.getState().avatarEmotion).toBe("sad");
  });

  it("follows the full ordering sequence: only cognition moves the avatar", () => {
    const s = useAriaStore.getState();
    expect(s.avatarEmotion).toBe("neutral");

    s.setVisionFrame(frame("happy"));
    expect(useAriaStore.getState().avatarEmotion).toBe("neutral");

    s.setAvatarEmotion("sad");
    expect(useAriaStore.getState().avatarEmotion).toBe("sad");

    s.setVisionFrame(frame("angry"));
    expect(useAriaStore.getState().avatarEmotion).toBe("sad");
    expect(useAriaStore.getState().emotion).toBe("angry");

    s.setAvatarEmotion("happy");
    expect(useAriaStore.getState().avatarEmotion).toBe("happy");
  });
});

describe("clearVisionFrame", () => {
  it("resets perception fields but leaves avatarEmotion alone (R3 boundary)", () => {
    const s = useAriaStore.getState();
    s.setVisionFrame(frame("happy", { emotion_confidence: 0.83 }));
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
