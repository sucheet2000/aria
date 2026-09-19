import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAriaStore } from "@/store/ariaStore";
import type { PerceptionFrame } from "@/store/ariaStore";
import { useCognition } from "./useCognition";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: () => Promise.resolve("test-token") }),
}));

const initial = useAriaStore.getState();

const okResponse = {
  avatar_emotion: "sad",
  natural_language_response: "ok",
  symbolic_inference: "",
  world_model_update: null,
  processing_ms: 1,
  episodic_memory: [],
  spatial_event: null,
};

let fetchMock: ReturnType<typeof vi.fn>;

function happyFrame(overrides: Partial<PerceptionFrame> = {}): PerceptionFrame {
  return {
    face_landmarks: [[0.5, 0.5, 0]],
    emotion: "happy",
    emotion_confidence: 0.83,
    head_pose: { pitch: 1, yaw: 2, roll: 3 },
    hand_landmarks: [],
    timestamp: Date.now() / 1000,
    ...overrides,
  };
}

function sentBody(): Record<string, unknown> {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const init = fetchMock.mock.calls[0][1] as RequestInit;
  return JSON.parse(init.body as string) as Record<string, unknown>;
}

beforeEach(() => {
  useAriaStore.setState(initial, true);
  fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => okResponse,
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useCognition vision_state contract", () => {
  it("sends the perception frame's emotion and confidence", async () => {
    useAriaStore.setState({ visionState: happyFrame() });
    const { result } = renderHook(() => useCognition());

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    const vision = sentBody().vision_state as Record<string, unknown>;
    expect(vision.emotion).toBe("happy");
    expect(vision.emotion_confidence).toBe(0.83);
    expect(vision.pitch).toBe(1);
    expect(vision.face_detected).toBe(true);
  });

  it("sends neutral with confidence 0 when the frame has no face", async () => {
    useAriaStore.setState({ visionState: happyFrame({ face_landmarks: [] }) });
    const { result } = renderHook(() => useCognition());

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    const vision = sentBody().vision_state as Record<string, unknown>;
    expect(vision.emotion).toBe("neutral");
    expect(vision.emotion_confidence).toBe(0);
    expect(vision.face_detected).toBe(false);
  });

  it("omits emotion_confidence when there is no perception frame", async () => {
    useAriaStore.setState({ visionState: null });
    const { result } = renderHook(() => useCognition());

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    const vision = sentBody().vision_state as Record<string, unknown>;
    expect("emotion_confidence" in vision).toBe(false);
    expect(vision.emotion).toBe("neutral");
  });

  it("lets the cognition response, not the face, set avatarEmotion (R3 boundary)", async () => {
    useAriaStore.setState({ visionState: happyFrame() });
    const { result } = renderHook(() => useCognition());

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    expect(useAriaStore.getState().avatarEmotion).toBe("sad");
    expect(JSON.stringify(sentBody())).not.toContain("avatar_emotion");
  });
});

describe("avatarEmotion ownership (R3)", () => {
  function respond(avatar_emotion: unknown) {
    const body: Record<string, unknown> = { ...okResponse };
    if (avatar_emotion === undefined) delete body.avatar_emotion;
    else body.avatar_emotion = avatar_emotion;
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: async () => body });
  }

  it("runs the full ordering sequence through the real hook and store", async () => {
    const { result } = renderHook(() => useCognition());
    const store = useAriaStore.getState();

    // 1–3: initial neutral; a happy face does not move the avatar
    expect(store.avatarEmotion).toBe("neutral");
    store.setVisionFrame(happyFrame());
    expect(useAriaStore.getState().avatarEmotion).toBe("neutral");

    // 4–5: cognition says sad
    respond("sad");
    await act(async () => {
      await result.current.sendMessage("hello");
    });
    expect(useAriaStore.getState().avatarEmotion).toBe("sad");

    // 6–7: an angry face arrives after the response; avatar stays sad
    store.setVisionFrame(happyFrame({ emotion: "angry" }));
    expect(useAriaStore.getState().avatarEmotion).toBe("sad");
    expect(useAriaStore.getState().emotion).toBe("angry");

    // 8–9: next cognition response changes it
    respond("happy");
    await act(async () => {
      await result.current.sendMessage("again");
    });
    expect(useAriaStore.getState().avatarEmotion).toBe("happy");
  });

  it("preserves the current avatar emotion when the response has no usable avatar_emotion", async () => {
    useAriaStore.getState().setAvatarEmotion("sad");
    const { result } = renderHook(() => useCognition());

    respond(undefined);
    await act(async () => {
      await result.current.sendMessage("hello");
    });
    expect(useAriaStore.getState().avatarEmotion).toBe("sad");

    respond("");
    await act(async () => {
      await result.current.sendMessage("hello");
    });
    expect(useAriaStore.getState().avatarEmotion).toBe("sad");

    // A non-string value must not reach the store either (code review P2).
    respond(42);
    await act(async () => {
      await result.current.sendMessage("hello");
    });
    expect(useAriaStore.getState().avatarEmotion).toBe("sad");
  });
});

describe("TTS-facing response path (R5)", () => {
  it("hands onResponse exactly the natural_language_response the server sent", async () => {
    const safe = "Sorry, I lost my train of thought for a moment. Could you say that again?";
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ ...okResponse, natural_language_response: safe, symbolic_inference: "" }),
    });
    const onResponse = vi.fn();
    const { result } = renderHook(() => useCognition());

    await act(async () => {
      await result.current.sendMessage("hello", onResponse);
    });

    expect(onResponse).toHaveBeenCalledTimes(1);
    expect(onResponse.mock.calls[0][0]).toBe(safe);
    const history = useAriaStore.getState().conversationHistory;
    expect(history[history.length - 1]).toEqual({ role: "assistant", content: safe });
    // The browser never parses or reconstructs model JSON: it speaks the field as given.
    expect(onResponse.mock.calls[0][0]).not.toContain("{");
  });
});
