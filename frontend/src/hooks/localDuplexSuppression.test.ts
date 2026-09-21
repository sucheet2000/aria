// V3.1 — the browser must not put ARIA's own voice on the wire, even when the
// control socket that carries tts_mute is down.
//
// V3 suppressed capture at the Go edge, driven by a control message on the MAIN
// WebSocket. That message is dropped silently whenever that socket is not open,
// while the microphone rides a SEPARATE socket that keeps streaming. So the
// guarantee depended on a delivery the browser could not make. These tests
// drive the real useTTS and the real useAudioCapture together and assert on the
// only thing that matters: whether a PCM frame reaches the audio socket.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: () => Promise.resolve("test-token") }),
}));

import { useAudioCapture } from "./useAudioCapture";
import { useTTS } from "./useTTS";
import { wsSendRef } from "./useWebSocket";
import { ttsResyncRef } from "./ttsResyncState";
import { isTtsCaptureSuppressed, ttsSpeakingHolds } from "./ttsSpeakingState";

const PRIVATE = "PRIVATE_LOCAL_DUPLEX_8842";

// ── browser environment doubles ──────────────────────────────────────────────

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
  drop(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code: 1006, reason: "blip" });
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

const stopTrack = vi.fn();
let streamsHandedOut = 0;

function makeTrack() {
  return { stop: stopTrack, addEventListener: vi.fn(), removeEventListener: vi.fn() };
}
function defaultStream(): unknown {
  streamsHandedOut += 1;
  const track = makeTrack();
  return { getTracks: () => [track], getAudioTracks: () => [track] };
}
function stubMediaDevices(): void {
  Object.defineProperty(navigator, "mediaDevices", {
    value: {
      getUserMedia: vi.fn().mockImplementation(() => Promise.resolve(defaultStream())),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    },
    configurable: true,
  });
}

// ── TTS doubles ──────────────────────────────────────────────────────────────

interface FakeUtterance {
  text: string;
  onend: (() => void) | null;
  onerror: ((e: unknown) => void) | null;
}
let lastUtterance: FakeUtterance | null = null;

interface FakeAudio {
  onended: (() => void) | null;
  onerror: (() => void) | null;
}
let lastAudio: FakeAudio | null = null;

function installSpeech(playBehavior: "resolve" | "reject"): void {
  lastUtterance = null;
  lastAudio = null;
  class U implements FakeUtterance {
    text: string;
    rate = 1;
    pitch = 1;
    volume = 1;
    voice: unknown = null;
    onend: (() => void) | null = null;
    onerror: ((e: unknown) => void) | null = null;
    constructor(t: string) {
      this.text = t;
      lastUtterance = this;
    }
  }
  const synth = {
    cancel: () => lastUtterance?.onend?.(),
    getVoices: () => [],
    speak: vi.fn(),
  };
  vi.stubGlobal("SpeechSynthesisUtterance", U);
  vi.stubGlobal("speechSynthesis", synth);
  const w = window as unknown as Record<string, unknown>;
  w.speechSynthesis = synth;
  w.SpeechSynthesisUtterance = U;

  class A implements FakeAudio {
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    pause = vi.fn();
    constructor(_u: string) {
      lastAudio = this;
    }
    play(): Promise<void> {
      return playBehavior === "reject"
        ? Promise.reject(new Error("NotAllowedError"))
        : Promise.resolve();
    }
  }
  vi.stubGlobal("Audio", A);
  vi.stubGlobal("URL", {
    createObjectURL: () => "blob:x",
    revokeObjectURL: () => undefined,
  });
}

function mockTtsFetch(kind: "ok" | "tiny" | "reject"): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() =>
      kind === "reject"
        ? Promise.reject(new Error("network down"))
        : Promise.resolve({
            ok: true,
            arrayBuffer: async () => new ArrayBuffer(kind === "tiny" ? 0 : 4096),
          })
    )
  );
}

// ── harness ──────────────────────────────────────────────────────────────────

async function startCapture(): Promise<{
  ws: MockWebSocket;
  node: MockAudioWorkletNode;
  unmount: () => void;
}> {
  const { result, unmount } = renderHook(() => useAudioCapture(true));
  await vi.waitFor(() => expect(result.current.active).toBe(true));
  await vi.waitFor(() => expect(MockAudioWorkletNode.instances.length).toBeGreaterThan(0));
  await vi.waitFor(() => expect(MockWebSocket.instances.length).toBeGreaterThan(0));
  const ws = MockWebSocket.instances.at(-1)!;
  ws.open();
  return { ws, node: MockAudioWorkletNode.instances.at(-1)!, unmount };
}

// One block of 48 kHz audio that resamples into several 16 kHz frames.
function pushMic(node: MockAudioWorkletNode): void {
  node.port.onmessage?.({ data: new Float32Array(4800).fill(0.4) } as MessageEvent);
}

function framesSentTo(ws: MockWebSocket): number {
  return ws.send.mock.calls.length;
}

beforeEach(() => {
  MockWebSocket.instances = [];
  MockAudioWorkletNode.instances = [];
  MockAudioContext.instances = [];
  stopTrack.mockClear();
  streamsHandedOut = 0;
  vi.stubGlobal("WebSocket", MockWebSocket);
  vi.stubGlobal("AudioContext", MockAudioContext);
  vi.stubGlobal("AudioWorkletNode", MockAudioWorkletNode);
  stubMediaDevices();
  installSpeech("resolve");
  // The control socket is DOWN for every test unless a test opens it. This is
  // the whole point: none of these guarantees may depend on it.
  wsSendRef.current = null;
});

afterEach(() => {
  // The hold count is module state shared by every test in this file, so a
  // leak in one would silently suppress capture in the next. Assert it is
  // clean, and clean up in `finally` so a failure here cannot cascade.
  try {
    expect(ttsSpeakingHolds()).toBe(0);
    expect(isTtsCaptureSuppressed()).toBe(false);
  } finally {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(navigator, "mediaDevices");
    const w = window as unknown as Record<string, unknown>;
    delete w.speechSynthesis;
    wsSendRef.current = null;
  }
});

describe("V3.1 — local PCM suppression, control socket unavailable", () => {
  it("Test 1: sends PCM normally when ARIA is not speaking", async () => {
    const { ws, node, unmount } = await startCapture();

    pushMic(node);

    expect(framesSentTo(ws)).toBeGreaterThan(0);
    unmount();
  });

  it("Test 4 (critical): drops PCM in the browser while the fallback speaks with the control socket down", async () => {
    const { ws, node, unmount } = await startCapture();
    mockTtsFetch("tiny"); // unusable body -> browser fallback

    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("Sure, I can help with that.");

    const before = framesSentTo(ws);
    pushMic(node);
    pushMic(node);

    expect(framesSentTo(ws)).toBe(before); // not one frame of ARIA's own voice

    lastUtterance?.onend?.();
    unmount();
  });

  it("Test 3: drops PCM while remote playback runs with the control socket down", async () => {
    const { ws, node, unmount } = await startCapture();
    mockTtsFetch("ok");

    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("Sure, I can help with that.");

    const before = framesSentTo(ws);
    pushMic(node);

    expect(framesSentTo(ws)).toBe(before);

    lastAudio?.onended?.();
    unmount();
  });

  it("Test 6: resumes sending once the final hold is released", async () => {
    const { ws, node, unmount } = await startCapture();
    mockTtsFetch("ok");

    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("Sure, I can help with that.");
    pushMic(node);
    const during = framesSentTo(ws);

    lastAudio?.onended?.();
    pushMic(node);

    expect(framesSentTo(ws)).toBeGreaterThan(during);
    unmount();
  });
});

describe("V3.1 — socket churn while ARIA speaks", () => {
  it("Test 5: stays suppressed across a control-socket reconnect mid-speech", async () => {
    const { ws, node, unmount } = await startCapture();
    mockTtsFetch("tiny");

    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("a long reply");

    // The control socket comes back mid-sentence and the V3 resync runs.
    const control: object[] = [];
    wsSendRef.current = (m) => control.push(m);
    ttsResyncRef.current?.();
    expect(control).toEqual([{ type: "tts_mute" }]); // re-asserted, not cleared

    const before = framesSentTo(ws);
    pushMic(node);
    expect(framesSentTo(ws)).toBe(before);   // still locally suppressed

    lastUtterance?.onend?.();
    pushMic(node);
    expect(framesSentTo(ws)).toBeGreaterThan(before);
    unmount();
  });

  it("Test 8: a NEW audio socket still carries no PCM until the hold ends", async () => {
    const { ws, node, unmount } = await startCapture();
    mockTtsFetch("tiny");

    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("a long reply");

    // The audio socket drops and the hook reconnects.
    ws.drop();
    // useAudioCapture reconnects on a ~1 s backoff, so this one wait is longer
    // than the default.
    await vi.waitFor(() => expect(MockWebSocket.instances.length).toBeGreaterThan(1), {
      timeout: 4000,
    });
    const fresh = MockWebSocket.instances.at(-1)!;
    fresh.open();

    pushMic(node);
    expect(framesSentTo(fresh)).toBe(0);   // the reconnect did not clear suppression

    lastUtterance?.onend?.();
    pushMic(node);
    expect(framesSentTo(fresh)).toBeGreaterThan(0);
    unmount();
  });

  it("Test 20: both control messages lost entirely — safe during, recovered after", async () => {
    const { ws, node, unmount } = await startCapture();
    mockTtsFetch("tiny");
    // wsSendRef stays null for the whole lifecycle: mute AND unmute are lost.
    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("nothing reaches the server at all");

    pushMic(node);
    expect(framesSentTo(ws)).toBe(0);

    lastUtterance?.onend?.();
    pushMic(node);
    expect(framesSentTo(ws)).toBeGreaterThan(0);
    unmount();
  });
});

describe("V3.1 — overlap, handoff and repetition", () => {
  it("Test 11: suppression never lifts during the remote-to-fallback handoff", async () => {
    const { ws, node, unmount } = await startCapture();
    mockTtsFetch("ok");
    installSpeech("reject");   // play() refuses -> hands off to the fallback

    const seen: boolean[] = [];
    const probe = setInterval(() => seen.push(isTtsCaptureSuppressed()), 0);

    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("handoff line");
    clearInterval(probe);

    expect(isTtsCaptureSuppressed()).toBe(true);
    expect(seen.every((v) => v === true) || seen.length === 0).toBe(true);

    pushMic(node);
    expect(framesSentTo(ws)).toBe(0);

    lastUtterance?.onend?.();
    unmount();
  });

  it("Test 7: two overlapping lifecycles — capture returns only after the last", async () => {
    const { ws, node, unmount } = await startCapture();

    mockTtsFetch("ok");
    const a = renderHook(() => useTTS());
    await a.result.current.speak("first");
    const remote = lastAudio;

    mockTtsFetch("tiny");
    const b = renderHook(() => useTTS());
    await b.result.current.speak("second");
    expect(ttsSpeakingHolds()).toBe(2);

    remote?.onended?.();               // A ends while B still speaks
    expect(isTtsCaptureSuppressed()).toBe(true);
    pushMic(node);
    expect(framesSentTo(ws)).toBe(0);

    lastUtterance?.onend?.();          // B ends
    expect(isTtsCaptureSuppressed()).toBe(false);
    pushMic(node);
    expect(framesSentTo(ws)).toBeGreaterThan(0);
    unmount();
  });

  it("Test 12: 20 speech cycles leave no stuck suppression", async () => {
    const { ws, node, unmount } = await startCapture();

    for (let i = 0; i < 20; i += 1) {
      mockTtsFetch("ok");
      const tts = renderHook(() => useTTS());
      await tts.result.current.speak(`line ${i}`);
      expect(isTtsCaptureSuppressed()).toBe(true);

      const during = framesSentTo(ws);
      pushMic(node);
      expect(framesSentTo(ws)).toBe(during);

      lastAudio?.onended?.();
      expect(ttsSpeakingHolds()).toBe(0);
    }

    pushMic(node);
    expect(framesSentTo(ws)).toBeGreaterThan(0);
    unmount();
  });

  it("Test 9: a fallback error restores capture", async () => {
    const { ws, node, unmount } = await startCapture();
    mockTtsFetch("tiny");
    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("line");

    lastUtterance?.onerror?.(new Error("synthesis failed"));

    expect(isTtsCaptureSuppressed()).toBe(false);
    pushMic(node);
    expect(framesSentTo(ws)).toBeGreaterThan(0);
    unmount();
  });

  it("Test 10: a remote playback error restores capture", async () => {
    const { ws, node, unmount } = await startCapture();
    mockTtsFetch("ok");
    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("line");

    lastAudio?.onerror?.();

    expect(isTtsCaptureSuppressed()).toBe(false);
    pushMic(node);
    expect(framesSentTo(ws)).toBeGreaterThan(0);
    unmount();
  });
});

describe("V3.1 — self-trigger, isolation and the capture pipeline", () => {
  it("Test 14: ARIA saying a wake phrase puts no PCM on the wire", async () => {
    const { ws, node, unmount } = await startCapture();
    mockTtsFetch("tiny");
    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("Hey aria, here is what I found.");

    pushMic(node);
    pushMic(node);
    expect(framesSentTo(ws)).toBe(0);   // no audio, so no transcript, so no wake

    lastUtterance?.onend?.();
    unmount();
  });

  it("Test 15: ARIA saying a sleep phrase puts no PCM on the wire", async () => {
    const { ws, node, unmount } = await startCapture();
    mockTtsFetch("tiny");
    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("That would be all for now.");

    pushMic(node);
    expect(framesSentTo(ws)).toBe(0);

    lastUtterance?.onend?.();
    unmount();
  });

  it("Test 18: the MediaStream, worklet and context survive a speech cycle", async () => {
    const { ws, node, unmount } = await startCapture();
    const streamsAtStart = streamsHandedOut;
    const contextsAtStart = MockAudioContext.instances.length;
    const nodesAtStart = MockAudioWorkletNode.instances.length;

    mockTtsFetch("ok");
    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("line");
    lastAudio?.onended?.();

    expect(streamsHandedOut).toBe(streamsAtStart);          // no re-acquisition
    expect(stopTrack).not.toHaveBeenCalled();               // no track.stop()
    expect(MockAudioContext.instances.length).toBe(contextsAtStart);
    expect(MockAudioWorkletNode.instances.length).toBe(nodesAtStart);

    pushMic(node);   // the same worklet node still feeds the same socket
    expect(framesSentTo(ws)).toBeGreaterThan(0);
    unmount();
  });

  it("Test 16: suppression is page-local module state, carrying no owner identity", async () => {
    const { unmount } = await startCapture();
    mockTtsFetch("tiny");
    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("line");

    // Nothing about the gate is keyed by user, session or socket: it is one
    // boolean derived from this page's own speech lifecycle.
    expect(isTtsCaptureSuppressed()).toBe(true);
    expect(ttsSpeakingHolds()).toBe(1);

    lastUtterance?.onend?.();
    expect(ttsSpeakingHolds()).toBe(0);
    unmount();
  });

  it("Test 17: the spoken line never reaches the console", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);
    const { ws, node, unmount } = await startCapture();

    mockTtsFetch("reject");
    const tts = renderHook(() => useTTS());
    await tts.result.current.speak(PRIVATE);
    pushMic(node);
    lastUtterance?.onend?.();

    const all = [...spy.mock.calls, ...log.mock.calls]
      .map((c) => c.map(String).join(" "))
      .join("\n");
    expect(all).not.toContain(PRIVATE);
    expect(framesSentTo(ws)).toBe(0);
    spy.mockRestore();
    log.mockRestore();
    unmount();
  });
});

describe("V3.1 — the gate closes before the first audible sample", () => {
  it("Test 13: suppression is already active when remote playback is invoked", async () => {
    const { node, unmount } = await startCapture();
    mockTtsFetch("ok");

    // Record the gate's state at the exact instant play() is called. Under V3
    // this was a network round trip away; here it is a synchronous read, so no
    // frame captured after ARIA becomes audible can ever be sent.
    let suppressedAtPlay: boolean | null = null;
    class RecordingAudio {
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(_u: string) {
        lastAudio = this as unknown as FakeAudio;
      }
      play(): Promise<void> {
        suppressedAtPlay = isTtsCaptureSuppressed();
        return Promise.resolve();
      }
    }
    vi.stubGlobal("Audio", RecordingAudio);

    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("line");

    expect(suppressedAtPlay).toBe(true);
    lastAudio?.onended?.();
    void node;
    unmount();
  });

  it("Test 13: suppression is already active when the fallback is invoked", async () => {
    const { unmount } = await startCapture();
    mockTtsFetch("tiny");

    let suppressedAtSpeak: boolean | null = null;
    const synth = {
      cancel: () => lastUtterance?.onend?.(),
      getVoices: () => [],
      speak: () => {
        suppressedAtSpeak = isTtsCaptureSuppressed();
      },
    };
    vi.stubGlobal("speechSynthesis", synth);
    (window as unknown as Record<string, unknown>).speechSynthesis = synth;

    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("line");

    expect(suppressedAtSpeak).toBe(true);
    lastUtterance?.onend?.();
    unmount();
  });

  it("Test 13: the last frame on the wire precedes the first audible sample", async () => {
    const { ws, node, unmount } = await startCapture();
    mockTtsFetch("ok");

    // The user is mid-sentence when ARIA begins.
    pushMic(node);
    const framesFromUser = framesSentTo(ws);
    expect(framesFromUser).toBeGreaterThan(0);

    let framesAtPlay = -1;
    class RecordingAudio {
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(_u: string) {
        lastAudio = this as unknown as FakeAudio;
      }
      play(): Promise<void> {
        framesAtPlay = framesSentTo(ws);
        return Promise.resolve();
      }
    }
    vi.stubGlobal("Audio", RecordingAudio);

    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("ARIA's reply");

    // Everything the server ever received was captured before ARIA was audible.
    expect(framesAtPlay).toBe(framesFromUser);
    pushMic(node);
    expect(framesSentTo(ws)).toBe(framesFromUser);

    lastAudio?.onended?.();
    unmount();
  });
});

describe("V3.1 — a speech lifecycle that never reports an end", () => {
  // Every release is event-driven. A media element paused by a hardware key,
  // or an utterance the browser silently drops, fires neither its end nor its
  // error handler. Before the watchdog, that stranded the hold and shut this
  // page's uplink for good: the microphone stayed dead until reload, with no
  // server-side timeout able to help, because the gate is local.
  it("releases the hold on its own so the microphone cannot stay dead", async () => {
    vi.useFakeTimers();
    try {
      const { ws, node, unmount } = await startCapture();
      mockTtsFetch("ok");

      const tts = renderHook(() => useTTS());
      await tts.result.current.speak("a reply that never reports completion");
      expect(isTtsCaptureSuppressed()).toBe(true);

      // The element never fires ended or error. Nothing in the app will ever
      // release this hold.
      pushMic(node);
      expect(framesSentTo(ws)).toBe(0);

      await vi.advanceTimersByTimeAsync(10 * 60 * 1000);

      expect(isTtsCaptureSuppressed()).toBe(false);
      pushMic(node);
      expect(framesSentTo(ws)).toBeGreaterThan(0);
      unmount();
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not fire the watchdog after a normal release", async () => {
    vi.useFakeTimers();
    try {
      const { unmount } = await startCapture();
      mockTtsFetch("ok");

      const tts = renderHook(() => useTTS());
      await tts.result.current.speak("an ordinary reply");
      lastAudio?.onended?.();
      expect(ttsSpeakingHolds()).toBe(0);

      // A second utterance starts, then the FIRST one's watchdog would have
      // fired. It must not drop the second one's hold.
      const again = renderHook(() => useTTS());
      await again.result.current.speak("the next reply");
      expect(ttsSpeakingHolds()).toBe(1);

      await vi.advanceTimersByTimeAsync(10 * 60 * 1000);

      // The second hold's own watchdog has now also fired, which is correct,
      // but the point is the count never went negative or double-released.
      expect(ttsSpeakingHolds()).toBe(0);
      unmount();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("V3.1 — review findings", () => {
  // Code review F1: the watchdog constants were pinned by nothing. Collapsing
  // the floor to 3 seconds left all 242 tests green, so a regression that cuts
  // ARIA off mid-reply — re-opening the mic while she is still audible — would
  // have shipped. These two assert the MARGIN, one constant each.
  it("does not cut a SHORT reply short (pins the floor)", async () => {
    vi.useFakeTimers();
    try {
      const { ws, node, unmount } = await startCapture();
      mockTtsFetch("ok");

      const tts = renderHook(() => useTTS());
      await tts.result.current.speak("Yes, I can.");   // a few seconds spoken

      await vi.advanceTimersByTimeAsync(20_000);

      expect(isTtsCaptureSuppressed()).toBe(true);
      pushMic(node);
      expect(framesSentTo(ws)).toBe(0);

      lastAudio?.onended?.();
      unmount();
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not cut a LONG reply short (pins the per-character rate)", async () => {
    vi.useFakeTimers();
    try {
      const { ws, node, unmount } = await startCapture();
      mockTtsFetch("ok");

      const reply = "This is a realistic answer from ARIA. ".repeat(11).slice(0, 400);
      const tts = renderHook(() => useTTS());
      await tts.result.current.speak(reply);

      // 400 characters is over half a minute of speech; the deadline must
      // scale with the text, not sit at the floor.
      await vi.advanceTimersByTimeAsync(80_000);

      expect(isTtsCaptureSuppressed()).toBe(true);
      pushMic(node);
      expect(framesSentTo(ws)).toBe(0);

      lastAudio?.onended?.();
      unmount();
    } finally {
      vi.useRealTimers();
    }
  });

  // QA finding Y1: HTMLMediaElement.pause() fires neither `ended` nor `error`.
  // A hardware media key or an OS audio interruption therefore stranded the
  // hold — and left isPlaying stuck true, so ARIA could never speak again
  // either. One keypress bricked both halves of the conversation until reload.
  it("treats a paused clip as the end of speech", async () => {
    const { ws, node, unmount } = await startCapture();
    mockTtsFetch("ok");

    const tts = renderHook(() => useTTS());
    await tts.result.current.speak("a reply the user pauses");
    expect(isTtsCaptureSuppressed()).toBe(true);

    (lastAudio as unknown as { onpause?: () => void }).onpause?.();

    expect(isTtsCaptureSuppressed()).toBe(false);
    pushMic(node);
    expect(framesSentTo(ws)).toBeGreaterThan(0);
    unmount();
  });

  // Security review, companion to finding 1: the 500-character cap is applied
  // server-side only, to what is sent to ElevenLabs. The raw reply reached
  // speechSynthesis, so a long answer became minutes of speech — past the point
  // where browsers silently stop and fire no event, and long enough that even a
  // proportional watchdog left the microphone dead for ages.
  it("caps the text handed to the speech engine", async () => {
    const { unmount } = await startCapture();
    mockTtsFetch("tiny");

    const long = "word ".repeat(400); // 2000 characters
    const tts = renderHook(() => useTTS());
    await tts.result.current.speak(long);

    expect(lastUtterance).not.toBeNull();
    expect(lastUtterance!.text.length).toBeLessThanOrEqual(500);
    expect(long.startsWith(lastUtterance!.text.slice(0, 100))).toBe(true);

    lastUtterance?.onend?.();
    unmount();
  });
});
