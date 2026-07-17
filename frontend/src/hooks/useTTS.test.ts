import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: () => Promise.resolve("test-token") }),
}));

import { useTTS } from "./useTTS";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(0),
    })
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useTTS emotion-matched voice", () => {
  it("includes emotion in the TTS POST body when provided", async () => {
    const { result } = renderHook(() => useTTS());

    await result.current.speak("Hello there, this is a test line.", "happy");

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/tts"),
      expect.any(Object)
    );
    const [, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({
      text: "Hello there, this is a test line.",
      emotion: "happy",
    });
  });

  it("degrades byte-identically to today when no emotion is given", async () => {
    const { result } = renderHook(() => useTTS());

    await result.current.speak("Hello there, this is a test line.");

    const [, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({ text: "Hello there, this is a test line." });
    expect(body).not.toHaveProperty("emotion");
  });
});
