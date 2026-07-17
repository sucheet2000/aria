import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, act, cleanup } from "@testing-library/react";
import { useAriaStore } from "@/store/ariaStore";

const connectAudio = vi.fn();
let mockAmplitude = 0;

vi.mock("@/hooks/useAudioAmplitude", () => ({
  useAudioAmplitude: () => ({ amplitude: mockAmplitude, connectAudio }),
}));

import SkullAvatar, { STATE_PALETTES } from "./SkullAvatar";
import { ttsAudioRef } from "@/hooks/useTTS";

let rafCallbacks: FrameRequestCallback[] = [];

function flushFrames(n: number) {
  for (let i = 0; i < n; i++) {
    const cbs = rafCallbacks;
    rafCallbacks = [];
    act(() => {
      cbs.forEach((cb) => cb(performance.now()));
    });
  }
}

function resetStore() {
  useAriaStore.setState({
    avatarEmotion: "idle",
    isThinking: false,
    isSpeaking: false,
    isListening: false,
  });
}

beforeEach(() => {
  resetStore();
  mockAmplitude = 0;
  connectAudio.mockClear();
  rafCallbacks = [];
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    rafCallbacks.push(cb);
    return rafCallbacks.length;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {});
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SkullAvatar", () => {
  it("renders an svg with role img and a descriptive label", () => {
    const { getByRole } = render(<SkullAvatar />);
    const svg = getByRole("img");
    expect(svg.getAttribute("aria-label")).toMatch(/skull/i);
  });

  it.each(Object.keys(STATE_PALETTES))(
    "applies the %s palette's iris color as a CSS variable",
    (state) => {
      act(() => {
        useAriaStore.setState({ avatarEmotion: state });
      });
      const { getByRole } = render(<SkullAvatar />);
      const svg = getByRole("img");
      expect(svg.style.getPropertyValue("--skullav-iris")).toBe(
        STATE_PALETTES[state].iris,
      );
    },
  );

  it("speaking state wins over the current emotion", () => {
    act(() => {
      useAriaStore.setState({ avatarEmotion: "happy", isSpeaking: true });
    });
    const { getByRole } = render(<SkullAvatar />);
    const svg = getByRole("img");
    expect(svg.style.getPropertyValue("--skullav-iris")).toBe(
      STATE_PALETTES.speaking.iris,
    );
  });

  it("drops the jaw with audio amplitude while speaking", () => {
    mockAmplitude = 0.6;
    act(() => {
      useAriaStore.setState({ isSpeaking: true });
    });
    const { getByTestId } = render(<SkullAvatar />);
    const jaw = getByTestId("skull-jaw");
    flushFrames(20);
    const transform = jaw.style.transform;
    expect(transform).toMatch(/translateY\(/);
    const px = parseFloat(transform.replace(/[^0-9.-]/g, ""));
    expect(px).toBeGreaterThan(1);
  });

  it("keeps the jaw closed when silent", () => {
    const { getByTestId } = render(<SkullAvatar />);
    const jaw = getByTestId("skull-jaw");
    flushFrames(20);
    const px = parseFloat(jaw.style.transform.replace(/[^0-9.-]/g, "") || "0");
    expect(px).toBeLessThan(0.5);
  });

  it("connects the analyser to the TTS audio element when speaking starts", () => {
    const fakeAudio = {} as HTMLAudioElement;
    ttsAudioRef.current = fakeAudio;
    act(() => {
      useAriaStore.setState({ isSpeaking: true });
    });
    render(<SkullAvatar />);
    expect(connectAudio).toHaveBeenCalledWith(fakeAudio);
    ttsAudioRef.current = null;
  });

  it("omits ambient motion classes when reduced motion is preferred", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockImplementation((q: string) => ({
        matches: q.includes("prefers-reduced-motion"),
        addEventListener: () => {},
        removeEventListener: () => {},
      })),
    );
    const { container } = render(<SkullAvatar />);
    expect(container.querySelector(".skullav-bob")).toBeNull();
    expect(container.querySelector(".skullav-pulse")).toBeNull();
  });

  it("includes ambient motion classes by default", () => {
    const { container } = render(<SkullAvatar />);
    expect(container.querySelector(".skullav-bob")).not.toBeNull();
    expect(container.querySelector(".skullav-pulse")).not.toBeNull();
  });
});
