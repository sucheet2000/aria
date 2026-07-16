import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useAriaStore } from "@/store/ariaStore";
import { visionCaptureActiveRef } from "@/hooks/visionCaptureState";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: () => Promise.resolve("test-token") }),
}));

// A face result (478 uniform landmarks -> neutral, identity head pose) and an
// open-palm hand result (-> gesture "stop"), built inside the hoisted factory so
// the module mock can reference them.
const { faceResult, handResult, faceLandmarker, handLandmarker } = vi.hoisted(() => {
  const uniformFace = Array.from({ length: 478 }, () => ({ x: 0.5, y: 0.5, z: 0 }));
  const identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];

  const hand = Array.from({ length: 21 }, () => ({ x: 0.5, y: 0.5, z: 0 }));
  hand[0] = { x: 0.5, y: 0.9, z: 0 };
  hand[1] = { x: 0.35, y: 0.75, z: 0 };
  hand[2] = { x: 0.3, y: 0.65, z: 0 };
  hand[3] = { x: 0.25, y: 0.55, z: 0 };
  hand[4] = { x: 0.2, y: 0.45, z: 0 };
  for (const [m, p, d, t] of [
    [5, 6, 7, 8],
    [9, 10, 11, 12],
    [13, 14, 15, 16],
    [17, 18, 19, 20],
  ]) {
    hand[m] = { x: 0.5, y: 0.75, z: 0 };
    hand[p] = { x: 0.5, y: 0.67, z: 0 };
    hand[d] = { x: 0.5, y: 0.59, z: 0 };
    hand[t] = { x: 0.5, y: 0.51, z: 0 };
  }

  return {
    faceResult: {
      faceLandmarks: [uniformFace],
      facialTransformationMatrixes: [{ rows: 4, columns: 4, data: identity }],
    },
    handResult: { landmarks: [hand] },
    faceLandmarker: { detectForVideo: vi.fn(), close: vi.fn() },
    handLandmarker: { detectForVideo: vi.fn(), close: vi.fn() },
  };
});

vi.mock("@mediapipe/tasks-vision", () => ({
  FilesetResolver: { forVisionTasks: vi.fn().mockResolvedValue({}) },
  FaceLandmarker: { createFromOptions: vi.fn().mockResolvedValue(faceLandmarker) },
  HandLandmarker: { createFromOptions: vi.fn().mockResolvedValue(handLandmarker) },
}));

import { FilesetResolver } from "@mediapipe/tasks-vision";
import { useVisionCapture } from "./useVisionCapture";

let rafCb: FrameRequestCallback | null = null;
let getUserMedia: ReturnType<typeof vi.fn>;
const stopTrack = vi.fn();
const realCreateElement = document.createElement.bind(document);

function stubMediaDevices(impl: () => Promise<unknown>): void {
  getUserMedia = vi.fn().mockImplementation(impl);
  Object.defineProperty(navigator, "mediaDevices", {
    value: { getUserMedia },
    configurable: true,
  });
}

beforeEach(() => {
  useAriaStore.setState({ visionState: null });
  visionCaptureActiveRef.current = false;
  rafCb = null;
  faceLandmarker.detectForVideo.mockReturnValue(faceResult);
  handLandmarker.detectForVideo.mockReturnValue(handResult);

  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    rafCb = cb;
    return 1;
  });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());

  const fakeVideo = {
    muted: false,
    playsInline: false,
    srcObject: null,
    readyState: 4,
    videoWidth: 640,
    videoHeight: 480,
    play: vi.fn().mockResolvedValue(undefined),
  };
  vi.spyOn(document, "createElement").mockImplementation(((tag: string) =>
    tag === "video"
      ? (fakeVideo as unknown as HTMLVideoElement)
      : realCreateElement(tag)) as typeof document.createElement);

  stubMediaDevices(() => Promise.resolve({ getTracks: () => [{ stop: stopTrack }] }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  Reflect.deleteProperty(navigator, "mediaDevices");
});

describe("useVisionCapture", () => {
  it("produces a well-formed PerceptionFrame from the local camera", async () => {
    const { result } = renderHook(() => useVisionCapture(true));

    await vi.waitFor(() => expect(result.current.active).toBe(true));
    expect(visionCaptureActiveRef.current).toBe(true);
    expect(rafCb).not.toBeNull();

    rafCb!(performance.now());

    const frame = useAriaStore.getState().visionState;
    expect(frame).not.toBeNull();
    expect(frame!.face_landmarks).toHaveLength(478);
    expect(frame!.hand_landmarks).toHaveLength(21);
    expect(frame!.emotion).toBe("neutral");
    expect(frame!.gesture_name).toBe("stop");
    expect(frame!.head_pose).toEqual({ pitch: 0, yaw: 0, roll: 0 });
    expect(frame!.pointing_vector).toBeNull();
    expect(typeof frame!.timestamp).toBe("number");
  });

  it("reports loading during init and clears it once active", async () => {
    let resolveFileset!: (v: unknown) => void;
    const pending = new Promise<unknown>((res) => {
      resolveFileset = res;
    });
    vi.mocked(FilesetResolver.forVisionTasks).mockReturnValueOnce(pending as never);

    const { result } = renderHook(() => useVisionCapture(true));

    await vi.waitFor(() => expect(result.current.loading).toBe(true));
    expect(result.current.active).toBe(false);

    resolveFileset({});

    await vi.waitFor(() => expect(result.current.active).toBe(true));
    expect(result.current.loading).toBe(false);
  });

  it("reports a permission error and does not become active when denied", async () => {
    stubMediaDevices(() =>
      Promise.reject(Object.assign(new Error("denied"), { name: "NotAllowedError" })),
    );

    const { result } = renderHook(() => useVisionCapture(true));

    await vi.waitFor(() => expect(result.current.error).toBe("Camera permission denied"));
    expect(result.current.active).toBe(false);
    expect(result.current.loading).toBe(false);
    expect(visionCaptureActiveRef.current).toBe(false);
    expect(useAriaStore.getState().visionState).toBeNull();
  });

  it("does not touch the camera while disabled", () => {
    renderHook(() => useVisionCapture(false));
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(visionCaptureActiveRef.current).toBe(false);
  });

  it("tears down capture on unmount", async () => {
    const { unmount } = renderHook(() => useVisionCapture(true));
    await vi.waitFor(() => expect(visionCaptureActiveRef.current).toBe(true));

    unmount();

    expect(visionCaptureActiveRef.current).toBe(false);
    expect(stopTrack).toHaveBeenCalled();
    expect(faceLandmarker.close).toHaveBeenCalled();
    expect(handLandmarker.close).toHaveBeenCalled();
  });
});
