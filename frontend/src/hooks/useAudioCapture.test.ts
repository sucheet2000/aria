import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { AUDIO_WS_URL } from "@/lib/config";
import { FRAME_SAMPLES } from "@/lib/audio/pcm";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: () => Promise.resolve("test-token") }),
}));

import { useAudioCapture } from "./useAudioCapture";

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  url: string;
  protocols?: string | string[];
  binaryType = "blob";
  readyState = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onclose: ((ev: { code: number; reason: string }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  send = vi.fn();
  close = vi.fn();

  constructor(url: string, protocols?: string | string[]) {
    this.url = url;
    this.protocols = protocols;
    MockWebSocket.instances.push(this);
  }

  open(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }
}

class MockAudioWorkletNode {
  static instances: MockAudioWorkletNode[] = [];
  port = { onmessage: null as ((ev: MessageEvent) => void) | null, postMessage: vi.fn() };
  connect = vi.fn();
  disconnect = vi.fn();

  constructor() {
    MockAudioWorkletNode.instances.push(this);
  }
}

class MockAudioContext {
  static instances: MockAudioContext[] = [];
  sampleRate = 48000;
  state = "running";
  destination = {};
  audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) };
  createMediaStreamSource = vi.fn(() => ({ connect: vi.fn(), disconnect: vi.fn() }));
  resume = vi.fn().mockResolvedValue(undefined);
  close = vi.fn().mockResolvedValue(undefined);

  constructor() {
    MockAudioContext.instances.push(this);
  }
}

let getUserMedia: ReturnType<typeof vi.fn>;
const stopTrack = vi.fn();

function stubMediaDevices(impl: () => Promise<unknown>): void {
  getUserMedia = vi.fn().mockImplementation(impl);
  Object.defineProperty(navigator, "mediaDevices", {
    value: { getUserMedia },
    configurable: true,
  });
}

beforeEach(() => {
  MockWebSocket.instances = [];
  MockAudioWorkletNode.instances = [];
  MockAudioContext.instances = [];
  stopTrack.mockClear();

  vi.stubGlobal("WebSocket", MockWebSocket);
  vi.stubGlobal("AudioContext", MockAudioContext);
  vi.stubGlobal("AudioWorkletNode", MockAudioWorkletNode);

  stubMediaDevices(() =>
    Promise.resolve({ getTracks: () => [{ stop: stopTrack }] })
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "mediaDevices");
});

describe("useAudioCapture", () => {
  it("requests a 16kHz-target mono stream with echo/noise/gain processing", async () => {
    const { result, unmount } = renderHook(() => useAudioCapture(true));

    await vi.waitFor(() => expect(result.current.active).toBe(true));

    const constraints = getUserMedia.mock.calls[0][0];
    expect(constraints.audio.channelCount).toBe(1);
    expect(constraints.audio.echoCancellation).toBe(true);
    expect(constraints.audio.noiseSuppression).toBe(true);
    expect(constraints.audio.autoGainControl).toBe(true);

    unmount();
  });

  it("opens /ws/audio with the token in the subprotocol, never in the URL", async () => {
    const { result, unmount } = renderHook(() => useAudioCapture(true));
    await vi.waitFor(() => expect(result.current.active).toBe(true));
    await vi.waitFor(() => expect(MockWebSocket.instances.length).toBeGreaterThan(0));

    const ws = MockWebSocket.instances.at(-1)!;
    expect(ws.url).toBe(AUDIO_WS_URL);
    expect(ws.url).not.toContain("token=");
    expect(ws.protocols).toEqual(["aria-ws", "test-token"]);

    unmount();
  });

  it("streams Int16 PCM frames of the contract length over the WS", async () => {
    const { result, unmount } = renderHook(() => useAudioCapture(true));
    await vi.waitFor(() => expect(result.current.active).toBe(true));
    await vi.waitFor(() => expect(MockAudioWorkletNode.instances.length).toBeGreaterThan(0));
    await vi.waitFor(() => expect(MockWebSocket.instances.length).toBeGreaterThan(0));

    const ws = MockWebSocket.instances.at(-1)!;
    ws.open();

    const node = MockAudioWorkletNode.instances.at(-1)!;
    // 0.1s of 48kHz audio -> ~1600 samples at 16kHz -> 5 frames of 320.
    const block = new Float32Array(4800).fill(0.4);
    node.port.onmessage?.({ data: block } as MessageEvent);

    expect(ws.send).toHaveBeenCalled();
    const sent = ws.send.mock.calls[0][0];
    expect(sent).toBeInstanceOf(ArrayBuffer);
    expect(sent.byteLength).toBe(FRAME_SAMPLES * 2);
    expect(new Int16Array(sent).length).toBe(FRAME_SAMPLES);

    unmount();
  });

  it("does not send frames until the WS is open", async () => {
    const { result, unmount } = renderHook(() => useAudioCapture(true));
    await vi.waitFor(() => expect(result.current.active).toBe(true));
    await vi.waitFor(() => expect(MockAudioWorkletNode.instances.length).toBeGreaterThan(0));

    const ws = MockWebSocket.instances.at(-1)!;
    const node = MockAudioWorkletNode.instances.at(-1)!;
    node.port.onmessage?.({ data: new Float32Array(4800).fill(0.4) } as MessageEvent);

    expect(ws.send).not.toHaveBeenCalled();

    unmount();
  });

  it("reports a permission error and stays inactive when denied", async () => {
    stubMediaDevices(() =>
      Promise.reject(Object.assign(new Error("denied"), { name: "NotAllowedError" }))
    );

    const { result } = renderHook(() => useAudioCapture(true));

    await vi.waitFor(() =>
      expect(result.current.error).toBe("Microphone permission denied")
    );
    expect(result.current.active).toBe(false);
    expect(MockWebSocket.instances.length).toBe(0);
  });

  it("does not touch the microphone while disabled", () => {
    renderHook(() => useAudioCapture(false));
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(MockAudioContext.instances.length).toBe(0);
  });

  it("tears down the stream, worklet, context and WS on unmount", async () => {
    const { result, unmount } = renderHook(() => useAudioCapture(true));
    await vi.waitFor(() => expect(result.current.active).toBe(true));
    await vi.waitFor(() => expect(MockWebSocket.instances.length).toBeGreaterThan(0));

    const ws = MockWebSocket.instances.at(-1)!;
    const node = MockAudioWorkletNode.instances.at(-1)!;
    const ctx = MockAudioContext.instances.at(-1)!;

    unmount();

    expect(stopTrack).toHaveBeenCalled();
    expect(node.disconnect).toHaveBeenCalled();
    expect(ctx.close).toHaveBeenCalled();
    expect(ws.close).toHaveBeenCalled();
  });
});
