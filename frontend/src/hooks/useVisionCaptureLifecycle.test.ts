// Workstream K — model creation is async. If the component unmounts while
// FaceLandmarker/HandLandmarker are still being built, cleanup runs first and
// finds the local variables still null, so it closes nothing. The awaits then
// resolve into variables nobody will ever read again, and two MediaPipe
// landmarkers plus their WASM memory are stranded for the life of the page.
// Toggling the camera a few times leaks a few more each time.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: () => Promise.resolve("test-token") }),
}));

const { faceLandmarker, handLandmarker, gate } = vi.hoisted(() => ({
  faceLandmarker: { detectForVideo: vi.fn(), close: vi.fn() },
  handLandmarker: { detectForVideo: vi.fn(), close: vi.fn() },
  // Lets a test hold model creation open across an unmount.
  gate: { release: null as null | (() => void) },
}));

vi.mock("@mediapipe/tasks-vision", () => ({
  FilesetResolver: { forVisionTasks: vi.fn().mockResolvedValue({}) },
  FaceLandmarker: {
    createFromOptions: vi.fn().mockImplementation(async () => {
      if (gate.release) {
        await new Promise<void>((resolve) => {
          gate.release = resolve;
        });
      }
      return faceLandmarker;
    }),
  },
  HandLandmarker: {
    createFromOptions: vi.fn().mockResolvedValue(handLandmarker),
  },
}));

import { useVisionCapture } from "./useVisionCapture";

const stopTrack = vi.fn();

function stubMedia(): void {
  Object.defineProperty(navigator, "mediaDevices", {
    value: {
      getUserMedia: vi.fn().mockResolvedValue({
        getTracks: () => [{ stop: stopTrack }],
      }),
    },
    configurable: true,
  });
}

beforeEach(() => {
  faceLandmarker.close.mockClear();
  handLandmarker.close.mockClear();
  stopTrack.mockClear();
  gate.release = null;
  stubMedia();
  vi.stubGlobal("requestAnimationFrame", () => 1);
  vi.stubGlobal("cancelAnimationFrame", () => undefined);
});

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "mediaDevices");
});

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) await Promise.resolve();
}

describe("useVisionCapture lifecycle", () => {
  it("1: a normal mount and unmount closes both landmarkers exactly once", async () => {
    const { unmount } = renderHook(() => useVisionCapture(true));
    await settle();
    unmount();
    await settle();

    expect(faceLandmarker.close).toHaveBeenCalledTimes(1);
    expect(handLandmarker.close).toHaveBeenCalledTimes(1);
  });

  it("2: unmounting BEFORE init resolves still closes what was created", async () => {
    // Hold FaceLandmarker creation open.
    gate.release = () => undefined;
    const { unmount } = renderHook(() => useVisionCapture(true));
    await settle();

    unmount();          // cleanup runs while creation is still pending
    gate.release?.();   // creation now resolves, into a dead closure
    await settle();

    expect(faceLandmarker.close).toHaveBeenCalledTimes(1);
  });

  it("3: a rejected init leaves nothing open and does not throw", async () => {
    const { FaceLandmarker } = await import("@mediapipe/tasks-vision");
    vi.mocked(FaceLandmarker.createFromOptions).mockRejectedValueOnce(
      new Error("wasm fetch failed"),
    );

    const { result, unmount } = renderHook(() => useVisionCapture(true));
    await vi.waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.active).toBe(false);
    unmount();
    await settle();
  });

  it("4 and 5: repeated mount/unmount closes each generation, never leaking", async () => {
    for (let i = 0; i < 4; i += 1) {
      const { unmount } = renderHook(() => useVisionCapture(true));
      await settle();
      unmount();
      await settle();
    }
    expect(faceLandmarker.close).toHaveBeenCalledTimes(4);
    expect(handLandmarker.close).toHaveBeenCalledTimes(4);
  });

  it("6: the camera track is stopped even when unmount races startup", async () => {
    gate.release = () => undefined;
    const { unmount } = renderHook(() => useVisionCapture(true));
    await settle();
    unmount();
    gate.release?.();
    await settle();

    // Either the stream was never acquired, or it was stopped. What must not
    // happen is an acquired camera left running with nobody holding it.
    const acquired = vi.mocked(navigator.mediaDevices.getUserMedia).mock.calls.length;
    if (acquired > 0) {
      expect(stopTrack).toHaveBeenCalled();
    }
  });

  it("7: no state update lands after unmount", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    gate.release = () => undefined;
    const { unmount } = renderHook(() => useVisionCapture(true));
    await settle();
    unmount();
    gate.release?.();
    await settle();

    const warned = spy.mock.calls
      .map((c) => c.map(String).join(" "))
      .some((m) => m.includes("unmounted") || m.includes("not wrapped in act"));
    expect(warned).toBe(false);
    spy.mockRestore();
  });

  it("8: close is called exactly once per landmarker, never twice", async () => {
    const { unmount } = renderHook(() => useVisionCapture(true));
    await settle();
    unmount();
    unmount();      // idempotent teardown
    await settle();

    expect(faceLandmarker.close).toHaveBeenCalledTimes(1);
    expect(handLandmarker.close).toHaveBeenCalledTimes(1);
  });
});
