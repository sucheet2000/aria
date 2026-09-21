// Workstream E — the amplitude meter drove a React state update on every
// animation frame. Both consumers immediately copied that value into a ref and
// read it from their own render loop, so the state existed only to force ~60
// re-renders a second of the avatar subtree, for a number nothing rendered.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";

import { useAudioAmplitude } from "./useAudioAmplitude";

let frame: (() => void) | null = null;
let rafCalls = 0;
let cancelled: number[] = [];

class FakeAnalyser {
  fftSize = 0;
  frequencyBinCount = 8;
  connect = vi.fn();
  disconnect = vi.fn();
  getByteFrequencyData(out: Uint8Array): void {
    out.fill(128);
  }
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  state = "running";
  destination = {};
  analyser = new FakeAnalyser();
  createAnalyser = () => this.analyser;
  createMediaElementSource = vi.fn(() => ({ connect: vi.fn(), disconnect: vi.fn() }));
  resume = vi.fn();
  close = vi.fn();
  constructor() {
    FakeAudioContext.instances.push(this);
  }
}

function tick(): void {
  const f = frame;
  frame = null;
  f?.();
}

beforeEach(() => {
  frame = null;
  rafCalls = 0;
  cancelled = [];
  FakeAudioContext.instances = [];
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("requestAnimationFrame", (cb: () => void) => {
    rafCalls += 1;
    frame = cb;
    return rafCalls;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => {
    cancelled.push(id);
    frame = null;
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useAudioAmplitude", () => {
  it("does not re-render its consumer on every animation frame", () => {
    let renders = 0;
    const { result, unmount } = renderHook(() => {
      renders += 1;
      return useAudioAmplitude();
    });

    const rendersAfterMount = renders;
    act(() => {
      result.current.connectAudio({} as HTMLAudioElement);
    });

    // Sixty frames of audio: the visualization must update without dragging
    // React through a render each time.
    act(() => {
      for (let i = 0; i < 60; i += 1) tick();
    });

    expect(renders).toBe(rendersAfterMount);
    unmount();
  });

  it("still reports the measured amplitude", () => {
    const { result, unmount } = renderHook(() => useAudioAmplitude());
    act(() => {
      result.current.connectAudio({} as HTMLAudioElement);
    });

    expect(result.current.amplitudeRef.current).toBe(0);
    act(() => {
      tick();
    });
    // Every bin at 128 of 255.
    expect(result.current.amplitudeRef.current).toBeCloseTo(128 / 255, 5);

    unmount();
  });

  it("keeps animating across frames", () => {
    const { result, unmount } = renderHook(() => useAudioAmplitude());
    act(() => {
      result.current.connectAudio({} as HTMLAudioElement);
    });

    const before = rafCalls;
    act(() => {
      tick();
      tick();
    });
    expect(rafCalls).toBeGreaterThan(before);
    unmount();
  });

  it("stops the loop and closes the context on unmount", () => {
    const { result, unmount } = renderHook(() => useAudioAmplitude());
    act(() => {
      result.current.connectAudio({} as HTMLAudioElement);
    });

    const ctx = FakeAudioContext.instances.at(-1)!;
    unmount();

    expect(cancelled.length).toBeGreaterThan(0);
    expect(ctx.close).toHaveBeenCalled();
  });

  it("does not schedule a second loop when connected twice", () => {
    const { result, unmount } = renderHook(() => useAudioAmplitude());
    act(() => {
      result.current.connectAudio({} as HTMLAudioElement);
      result.current.connectAudio({} as HTMLAudioElement);
    });

    // One pending frame, not two racing loops both calling requestAnimationFrame.
    const before = rafCalls;
    act(() => {
      tick();
    });
    expect(rafCalls).toBe(before + 1);

    unmount();
  });
});
