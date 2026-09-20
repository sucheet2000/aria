import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAriaStore } from "@/store/ariaStore";
import type { PerceptionFrame } from "@/store/ariaStore";
import { useCognition } from "./useCognition";
import { COGNITION_REQUEST_TIMEOUT_MS } from "@/lib/config";

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

// A real browser rejects an aborted fetch with a DOMException, which extends
// Error there. jsdom's DOMException does not, so it would take the wrong catch
// branch; this mirrors what the hook actually sees in a browser.
function abortError(): Error {
  const err = new Error("The user aborted a request.");
  err.name = "AbortError";
  return err;
}

// Never settles on its own: it rejects only when the caller's signal aborts,
// which is exactly how a stalled network request behaves.
function stallingFetch(): ReturnType<typeof vi.fn> {
  return vi.fn(
    (_url: string, init: RequestInit) =>
      new Promise((_resolve, reject) => {
        const signal = init.signal as AbortSignal;
        if (signal.aborted) reject(abortError());
        else signal.addEventListener("abort", () => reject(abortError()));
      })
  );
}

function sentSignal(): AbortSignal {
  return (fetchMock.mock.calls[0][1] as RequestInit).signal as AbortSignal;
}

describe("browser cognition deadline (R6)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("holds the request open until COGNITION_REQUEST_TIMEOUT_MS, then aborts", async () => {
    fetchMock = stallingFetch();
    vi.stubGlobal("fetch", fetchMock);
    useAriaStore.getState().setAvatarEmotion("fearful");
    const onResponse = vi.fn();
    const { result } = renderHook(() => useCognition());

    let pending!: Promise<void>;
    await act(async () => {
      pending = result.current.sendMessage("hello", onResponse);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // One millisecond before the deadline the browser is still waiting: the Go
    // edge (20s) is meant to answer first, so the browser must not bail early.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(COGNITION_REQUEST_TIMEOUT_MS - 1);
    });
    expect(sentSignal().aborted).toBe(false);
    expect(result.current.isLoading).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
      await pending;
    });

    expect(sentSignal().aborted).toBe(true);
    expect(result.current.error).toBe("Request timed out.");
    expect(result.current.isLoading).toBe(false);
    expect(useAriaStore.getState().isThinking).toBe(false);
  });

  it("does not speak the timeout: onResponse (TTS) is never invoked", async () => {
    fetchMock = stallingFetch();
    vi.stubGlobal("fetch", fetchMock);
    const onResponse = vi.fn();
    const { result } = renderHook(() => useCognition());

    let pending!: Promise<void>;
    await act(async () => {
      pending = result.current.sendMessage("hello", onResponse);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(COGNITION_REQUEST_TIMEOUT_MS);
      await pending;
    });

    expect(
      onResponse,
      "a timed-out request must not reach TTS"
    ).not.toHaveBeenCalled();
  });

  it("leaves avatar emotion and the response-derived state untouched on timeout", async () => {
    fetchMock = stallingFetch();
    vi.stubGlobal("fetch", fetchMock);
    useAriaStore.getState().setAvatarEmotion("fearful");
    const memoryUpdated = vi.fn();
    window.addEventListener("aria:memory-updated", memoryUpdated);
    const { result } = renderHook(() => useCognition());

    let pending!: Promise<void>;
    await act(async () => {
      pending = result.current.sendMessage("hello");
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(COGNITION_REQUEST_TIMEOUT_MS);
      await pending;
    });

    const state = useAriaStore.getState();
    expect(state.avatarEmotion).toBe("fearful");
    expect(state.processingMs).toBe(0);
    expect(state.symbolicInference).toBe("");
    expect(state.worldModelUpdates).toEqual([]);
    expect(memoryUpdated).not.toHaveBeenCalled();
    window.removeEventListener("aria:memory-updated", memoryUpdated);
  });

  it("clears the deadline timer once a response lands, leaving no late abort", async () => {
    const clearSpy = vi.spyOn(globalThis, "clearTimeout");
    const onResponse = vi.fn();
    const { result } = renderHook(() => useCognition());

    await act(async () => {
      await result.current.sendMessage("hello", onResponse);
    });

    // Normal path is unchanged by the deadline work.
    const history = useAriaStore.getState().conversationHistory;
    expect(history[history.length - 1]).toEqual({ role: "assistant", content: "ok" });
    expect(useAriaStore.getState().avatarEmotion).toBe("sad");
    expect(onResponse).toHaveBeenCalledTimes(1);
    expect(onResponse.mock.calls[0][0]).toBe("ok");
    expect(clearSpy).toHaveBeenCalled();

    // Long past the deadline nothing fires: no late abort, no extra state churn.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(COGNITION_REQUEST_TIMEOUT_MS * 2);
    });
    expect(sentSignal().aborted).toBe(false);
    expect(result.current.error).toBeNull();
    expect(useAriaStore.getState().conversationHistory).toHaveLength(2);
    clearSpy.mockRestore();
  });
});

describe("server-side deadline reaches the browser (R6)", () => {
  it("renders a 504 as a timeout, not a generic failure", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 504, json: async () => ({}) });
    const onResponse = vi.fn();
    useAriaStore.setState({ avatarEmotion: "fearful" });
    const { result } = renderHook(() => useCognition());

    await act(async () => {
      await result.current.sendMessage("hello", onResponse);
    });

    // Go (20s) and Python (15s) both give up before the browser's 25s backstop,
    // so a real timeout arrives as a 504 rather than an AbortError.
    expect(result.current.error).toBe("Request timed out.");
    expect(onResponse).not.toHaveBeenCalled();
    expect(useAriaStore.getState().avatarEmotion).toBe("fearful");
    expect(result.current.isLoading).toBe(false);
  });

  it("still reports a non-timeout HTTP failure generically", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({}) });
    const { result } = renderHook(() => useCognition());

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    expect(result.current.error).toBe("I could not process that request.");
  });
});
