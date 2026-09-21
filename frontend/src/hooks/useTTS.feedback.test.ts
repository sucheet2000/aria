// V3 — ARIA must never have the mic uplink live while it is audibly speaking.
//
// Mic suppression is server-side: the browser sends {type:"tts_mute"} on the
// MAIN WebSocket and the Go edge drops this owner's PCM frames. So the browser
// contract is observable as the ORDER of control messages on wsSendRef relative
// to playback, plus the guarantee that every hold is eventually released.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: () => Promise.resolve("test-token") }),
}));

import { useTTS, __ttsMuteHoldCount } from "./useTTS";
import { wsSendRef } from "./useWebSocket";
import { ttsResyncRef } from "./ttsResyncState";
import { isTtsCaptureSuppressed } from "./ttsSpeakingState";

const LINE = "Sure, I can help with that.";
const PRIVATE = "PRIVATE_TTS_FEEDBACK_5197";

// One ordered trace of every duplex-relevant event.
let trace: string[] = [];

interface FakeUtterance {
  text: string;
  onend: (() => void) | null;
  onerror: ((e: unknown) => void) | null;
}
let lastUtterance: FakeUtterance | null = null;
let speakThrows = false;

function installSpeechSynthesis(): void {
  lastUtterance = null;
  speakThrows = false;
  class FakeUtteranceCtor implements FakeUtterance {
    text: string;
    rate = 1;
    pitch = 1;
    volume = 1;
    voice: unknown = null;
    onend: (() => void) | null = null;
    onerror: ((e: unknown) => void) | null = null;
    constructor(text: string) {
      this.text = text;
      lastUtterance = this;
    }
  }
  const synth = {
    cancel: () => {
      trace.push("browser:cancel");
      // Per spec, cancel() fires 'end' on the utterance it stopped.
      const stopped = lastUtterance;
      if (stopped) stopped.onend?.();
    },
    getVoices: () => [],
    speak: () => {
      if (speakThrows) throw new Error("synthesis unavailable");
      trace.push("browser:speak");
    },
  };
  vi.stubGlobal("SpeechSynthesisUtterance", FakeUtteranceCtor);
  vi.stubGlobal("speechSynthesis", synth);
  const w = window as unknown as Record<string, unknown>;
  w.speechSynthesis = synth;
  w.SpeechSynthesisUtterance = FakeUtteranceCtor;
}

function removeSpeechSynthesis(): void {
  const w = window as unknown as Record<string, unknown>;
  delete w.speechSynthesis;
}

interface FakeAudio {
  onended: (() => void) | null;
  onerror: (() => void) | null;
}
let lastAudio: FakeAudio | null = null;

function installAudio(playBehavior: "resolve" | "reject"): void {
  lastAudio = null;
  class FakeAudioCtor implements FakeAudio {
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    pause = () => trace.push("audio:pause");
    constructor(_url: string) {
      lastAudio = this;
    }
    play(): Promise<void> {
      if (playBehavior === "reject") {
        trace.push("audio:play-rejected");
        return Promise.reject(new Error("NotAllowedError"));
      }
      trace.push("audio:play");
      return Promise.resolve();
    }
  }
  vi.stubGlobal("Audio", FakeAudioCtor);
  vi.stubGlobal("URL", {
    createObjectURL: () => "blob:fake",
    revokeObjectURL: () => undefined,
  });
}

type FetchKind = "ok" | "tiny" | "reject" | "not-ok" | "unavailable" | "gateway" | "cutoff" | "timeout";

function mockTtsFetch(kind: FetchKind): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() => {
      if (kind === "reject") return Promise.reject(new Error("network down"));
      if (kind === "timeout") {
        return Promise.reject(
          Object.assign(new Error("signal timed out"), { name: "TimeoutError" })
        );
      }
      if (kind === "cutoff") {
        // The server aborted the connection mid-clip, so the status says 200
        // but the body can never be read to the end.
        return Promise.resolve({
          ok: true,
          status: 200,
          arrayBuffer: () =>
            Promise.reject(new TypeError("network error: connection closed")),
        });
      }
      if (kind === "gateway") {
        // An intermediary — Railway's edge, a proxy, Cloudflare — answers a
        // dead origin with an HTML page. It is a 5xx and it is far larger than
        // the 100-byte usability floor, so ONLY the status tells the browser
        // this is not speech.
        return Promise.resolve({
          ok: false,
          status: 503,
          arrayBuffer: async () =>
            new TextEncoder().encode("<html><body>" + "service unavailable ".repeat(20) + "</body></html>").buffer,
        });
      }
      if (kind === "unavailable") {
        // Closure 2: the server no longer answers a dead provider with an empty
        // 200. It says 503 with a JSON error and no audio at all.
        return Promise.resolve({
          ok: false,
          status: 503,
          arrayBuffer: async () => new TextEncoder().encode(
            '{"error":"speech synthesis unavailable"}'
          ).buffer,
        });
      }
      if (kind === "not-ok") {
        return Promise.resolve({
          ok: false,
          status: 502,
          arrayBuffer: async () => new ArrayBuffer(0),
        });
      }
      const bytes = kind === "tiny" ? 0 : 4096;
      return Promise.resolve({ ok: true, arrayBuffer: async () => new ArrayBuffer(bytes) });
    })
  );
}

// Finish whatever ARIA is still saying, the way a real browser eventually would.
function endAllSpeech(): void {
  lastUtterance?.onend?.();
  lastAudio?.onended?.();
}

beforeEach(() => {
  trace = [];
  wsSendRef.current = (msg: object) => {
    const t = (msg as { type?: string }).type;
    if (t === "tts_mute" || t === "tts_unmute") trace.push(t);
  };
  installSpeechSynthesis();
  installAudio("resolve");
  // Module state must not leak between tests.
  expect(__ttsMuteHoldCount()).toBe(0);
});

afterEach(() => {
  // Test 21: once every speech lifecycle has ended, no hold may remain. This
  // runs after EVERY test, so any leaked mute anywhere fails the suite.
  // Cleanup goes in `finally` so a failure here does not strand the stubs and
  // cascade into every later test in the file.
  try {
    endAllSpeech();
    expect(__ttsMuteHoldCount()).toBe(0);
  } finally {
    vi.unstubAllGlobals();
    removeSpeechSynthesis();
    wsSendRef.current = null;
  }
});

function firstIndex(label: string): number {
  return trace.indexOf(label);
}

describe("V3 — remote (ElevenLabs) playback", () => {
  it("Test 10: mutes BEFORE playback starts, releases after it ends", async () => {
    mockTtsFetch("ok");
    const { result } = renderHook(() => useTTS());

    await result.current.speak(LINE);
    expect(trace).toEqual(["tts_mute", "audio:play"]);

    lastAudio?.onended?.();   // Test 7
    expect(trace).toEqual(["tts_mute", "audio:play", "tts_unmute"]);
  });

  it("Test 8: releases capture when playback errors", async () => {
    mockTtsFetch("ok");
    const { result } = renderHook(() => useTTS());
    await result.current.speak(LINE);

    lastAudio?.onerror?.();
    expect(trace.at(-1)).toBe("tts_unmute");
  });

  it("releases exactly once when both ended and error fire", async () => {
    mockTtsFetch("ok");
    const { result } = renderHook(() => useTTS());
    await result.current.speak(LINE);

    lastAudio?.onended?.();
    lastAudio?.onerror?.();
    expect(trace.filter((e) => e === "tts_unmute")).toHaveLength(1);
  });
});

describe("V3 — browser SpeechSynthesis fallback (the finding)", () => {
  it("Test 3: mutes before speaking when the remote body is unusable", async () => {
    mockTtsFetch("tiny");
    const { result } = renderHook(() => useTTS());

    await result.current.speak(LINE);

    expect(trace).toContain("tts_mute");
    expect(firstIndex("tts_mute")).toBeLessThan(firstIndex("browser:speak"));
  });

  it("Test 9: no unmuted gap when the remote request fails outright", async () => {
    mockTtsFetch("reject");
    const { result } = renderHook(() => useTTS());

    await result.current.speak(LINE);

    expect(firstIndex("tts_mute")).toBeLessThan(firstIndex("browser:speak"));
    expect(trace.slice(0, firstIndex("browser:speak"))).not.toContain("tts_unmute");
  });

  it("Test 9: no unmuted gap when the remote returns a non-OK status", async () => {
    mockTtsFetch("not-ok");
    const { result } = renderHook(() => useTTS());

    await result.current.speak(LINE);

    expect(firstIndex("tts_mute")).toBeLessThan(firstIndex("browser:speak"));
    expect(trace.slice(0, firstIndex("browser:speak"))).not.toContain("tts_unmute");
  });

  it("Test 9: no unmuted gap when the remote request times out", async () => {
    mockTtsFetch("timeout");
    const { result } = renderHook(() => useTTS());

    await result.current.speak(LINE);

    expect(firstIndex("tts_mute")).toBeLessThan(firstIndex("browser:speak"));
    expect(trace.slice(0, firstIndex("browser:speak"))).not.toContain("tts_unmute");
  });

  it("Test 9: hands the mute over when play() is rejected, with no gap", async () => {
    mockTtsFetch("ok");
    installAudio("reject");
    const { result } = renderHook(() => useTTS());

    await result.current.speak(LINE);

    // The remote hold is released only after the fallback has taken its own,
    // so the mic is never open between the two pieces of ARIA speech. The gap
    // would appear BEFORE the fallback starts, so check the whole trace, not
    // just the tail — checking only the tail is what a wrong fix would pass.
    const spoke = firstIndex("browser:speak");
    expect(spoke).toBeGreaterThanOrEqual(0);
    expect(firstIndex("tts_mute")).toBeLessThan(spoke);
    expect(trace).not.toContain("tts_unmute");
  });

  // ── Closure 2 ────────────────────────────────────────────────────────────
  // The server used to answer a dead provider with 200 and an empty body, and
  // the browser fell back because the BODY was unusable. Now it answers 503
  // with a JSON error body, so the fallback has to be reached by the STATUS.
  // A JSON error body is over 100 bytes of nothing useful, so the old size
  // check would have played it as audio.
  it("Closure 2 test 6: the browser voice still speaks when the server says 503", async () => {
    mockTtsFetch("unavailable");
    const { result } = renderHook(() => useTTS());

    await result.current.speak(LINE);

    expect(trace).toContain("browser:speak");
    expect(lastUtterance?.text).toBe(LINE);
    expect(firstIndex("tts_mute")).toBeLessThan(firstIndex("browser:speak"));
    expect(trace.slice(0, firstIndex("browser:speak"))).not.toContain("tts_unmute");
  });

  it("Closure 2 test 7: the 503 path completes the whole mute lifecycle", async () => {
    mockTtsFetch("unavailable");
    const { result } = renderHook(() => useTTS());

    await result.current.speak(LINE);

    // Local gate shut while the fallback voice is talking...
    expect(isTtsCaptureSuppressed()).toBe(true);
    expect(__ttsMuteHoldCount()).toBe(1);

    lastUtterance?.onend?.();

    // ...and fully open once it stops, with the server told as well.
    expect(isTtsCaptureSuppressed()).toBe(false);
    expect(__ttsMuteHoldCount()).toBe(0);
    expect(trace[trace.length - 1]).toBe("tts_unmute");
  });

  it("Closure 2 test 6b: a large 5xx error page is never played as audio", async () => {
    mockTtsFetch("gateway");
    const { result } = renderHook(() => useTTS());

    await result.current.speak(LINE);

    // Nothing was handed to the audio element; the browser voice spoke instead.
    expect(lastAudio).toBeNull();
    expect(trace).toContain("browser:speak");
    expect(lastUtterance?.text).toBe(LINE);
  });

  it("Closure 2 test 6c: a clip cut off mid-sentence hands over to the browser voice", async () => {
    mockTtsFetch("cutoff");
    const { result } = renderHook(() => useTTS());

    await result.current.speak(LINE);

    // Half a clip is not speech. The fallback says the whole line.
    expect(lastAudio).toBeNull();
    expect(trace).toContain("browser:speak");
    expect(lastUtterance?.text).toBe(LINE);
    // And the mic is not left shut by the abandoned attempt.
    expect(trace.slice(0, firstIndex("browser:speak"))).not.toContain("tts_unmute");
  });

  it("Test 4: releases capture when fallback speech finishes", async () => {
    mockTtsFetch("tiny");
    const { result } = renderHook(() => useTTS());
    await result.current.speak(LINE);

    lastUtterance?.onend?.();
    expect(trace.at(-1)).toBe("tts_unmute");
  });

  it("Test 5: releases capture when fallback speech errors", async () => {
    mockTtsFetch("tiny");
    const { result } = renderHook(() => useTTS());
    await result.current.speak(LINE);

    lastUtterance?.onerror?.(new Error("synthesis-failed"));
    expect(trace.at(-1)).toBe("tts_unmute");
  });

  it("Test 6: a cancelled utterance does not leave capture muted", async () => {
    mockTtsFetch("tiny");
    const { result } = renderHook(() => useTTS());
    await result.current.speak(LINE);

    // speechSynthesis.cancel() fires 'end' on the utterance it stopped.
    window.speechSynthesis.cancel();
    expect(trace.at(-1)).toBe("tts_unmute");
    expect(__ttsMuteHoldCount()).toBe(0);
  });

  it("Test 16: a fallback that never starts speaking does not strand the mute", async () => {
    mockTtsFetch("tiny");
    speakThrows = true;
    const { result } = renderHook(() => useTTS());

    await result.current.speak(LINE);

    expect(trace).not.toContain("browser:speak");
    expect(__ttsMuteHoldCount()).toBe(0);
    expect(trace.at(-1)).toBe("tts_unmute");
  });

  it("Test 25: the fallback still speaks when the remote is unavailable", async () => {
    mockTtsFetch("reject");
    const { result } = renderHook(() => useTTS());

    await result.current.speak(LINE);

    // V3 adds duplex safety; it must not remove the fallback.
    expect(trace).toContain("browser:speak");
    expect(lastUtterance?.text).toBe(LINE);
  });

  it("does nothing at all when the browser has no speech synthesis", async () => {
    mockTtsFetch("reject");
    removeSpeechSynthesis();
    const { result } = renderHook(() => useTTS());

    await result.current.speak(LINE);

    // No speech means no mute is taken, and none is left behind.
    expect(trace).not.toContain("browser:speak");
    expect(__ttsMuteHoldCount()).toBe(0);
  });
});

describe("V3 — overlapping speech and repeated cycles", () => {
  it("Test 14: the first speech to end must not re-open the mic while the second speaks", async () => {
    mockTtsFetch("ok");
    const { result } = renderHook(() => useTTS());
    await result.current.speak(LINE);       // remote holds
    const remote = lastAudio;

    // A second piece of ARIA speech begins before the first has torn down.
    mockTtsFetch("tiny");
    const second = renderHook(() => useTTS());
    await second.result.current.speak("And one more thing.");
    expect(trace).toContain("browser:speak");

    remote?.onended?.();                    // A ends while B is still speaking
    expect(trace).not.toContain("tts_unmute");
    expect(__ttsMuteHoldCount()).toBe(1);

    lastUtterance?.onend?.();               // B ends — now the mic re-opens
    expect(trace.at(-1)).toBe("tts_unmute");
    expect(__ttsMuteHoldCount()).toBe(0);
  });

  it("Test 21: many speak/end cycles leak no holds", async () => {
    for (let i = 0; i < 12; i += 1) {
      mockTtsFetch("ok");
      const { result } = renderHook(() => useTTS());
      await result.current.speak(`line ${i}`);
      lastAudio?.onended?.();
      expect(__ttsMuteHoldCount()).toBe(0);
    }
    expect(trace.filter((e) => e === "tts_mute")).toHaveLength(12);
    expect(trace.filter((e) => e === "tts_unmute")).toHaveLength(12);
  });

  it("Test 22: a failed cycle is followed by a healthy one", async () => {
    mockTtsFetch("reject");
    const first = renderHook(() => useTTS());
    await first.result.current.speak(LINE);
    lastUtterance?.onend?.();
    expect(__ttsMuteHoldCount()).toBe(0);

    trace = [];
    mockTtsFetch("ok");
    const second = renderHook(() => useTTS());
    await second.result.current.speak(LINE);
    expect(trace).toEqual(["tts_mute", "audio:play"]);
    lastAudio?.onended?.();
    expect(trace.at(-1)).toBe("tts_unmute");
  });

  it("Test 15: unmounting mid-speech still releases when speech ends", async () => {
    mockTtsFetch("tiny");
    const { result, unmount } = renderHook(() => useTTS());
    await result.current.speak(LINE);

    unmount();
    expect(__ttsMuteHoldCount()).toBe(1);   // still speaking: stay muted

    lastUtterance?.onend?.();
    expect(trace.at(-1)).toBe("tts_unmute");
    expect(__ttsMuteHoldCount()).toBe(0);
  });
});

describe("V3 — privacy and idle behaviour", () => {
  it("Test 1: no control message is sent when ARIA is not speaking", () => {
    renderHook(() => useTTS());
    expect(trace).toEqual([]);
    expect(__ttsMuteHoldCount()).toBe(0);
  });

  it("Test 24: the spoken line never reaches the console", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    mockTtsFetch("reject");
    const { result } = renderHook(() => useTTS());

    await result.current.speak(PRIVATE);
    lastUtterance?.onend?.();

    const logged = spy.mock.calls.map((c) => c.map(String).join(" ")).join("\n");
    expect(logged).not.toContain(PRIVATE);
    spy.mockRestore();
  });
});

describe("V3 — browsers that do not fire 'end' when speech is cancelled", () => {
  it("still releases the superseded hold when a new fallback replaces an old one", async () => {
    // The spec says cancel() fires 'end' on the utterance it stopped. Not every
    // engine does. Without the defensive release, the superseded hold would
    // leak and the owner would stay muted until the page reloaded.
    const silentCancel = {
      cancel: () => trace.push("browser:cancel"),   // fires nothing
      getVoices: () => [],
      speak: () => trace.push("browser:speak"),
    };
    vi.stubGlobal("speechSynthesis", silentCancel);
    (window as unknown as Record<string, unknown>).speechSynthesis = silentCancel;

    mockTtsFetch("tiny");
    const first = renderHook(() => useTTS());
    await first.result.current.speak("first line");
    expect(__ttsMuteHoldCount()).toBe(1);

    const second = renderHook(() => useTTS());
    await second.result.current.speak("second line");
    // Two utterances, but only the live one holds the mute.
    expect(__ttsMuteHoldCount()).toBe(1);

    lastUtterance?.onend?.();
    expect(__ttsMuteHoldCount()).toBe(0);
    expect(trace.at(-1)).toBe("tts_unmute");
  });
});

describe("V3 — resync when the control socket comes back", () => {
  it("re-asserts the mute if ARIA is still speaking", async () => {
    mockTtsFetch("ok");
    const { result } = renderHook(() => useTTS());
    await result.current.speak(LINE);

    // The socket dropped and came back; the server may have lost the mute.
    trace.length = 0;
    ttsResyncRef.current?.();

    expect(trace).toEqual(["tts_mute"]);
    lastAudio?.onended?.();
  });

  it("clears a stale mute if ARIA is not speaking", () => {
    // A fresh page owes nothing. Saying so is what releases a mute the server
    // is still holding for a page that went away mid-sentence.
    renderHook(() => useTTS());
    ttsResyncRef.current?.();

    expect(trace).toEqual(["tts_unmute"]);
  });

  it("is registered by the hook, so the socket can call it", () => {
    renderHook(() => useTTS());
    expect(typeof ttsResyncRef.current).toBe("function");
  });
});
