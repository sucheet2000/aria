// Workstream L (B22) — when a request failed, the hook wrote a fabricated
// assistant turn into the conversation history: "I could not process that
// request." That history is sent back to the model on the next turn, so the
// model read its own transcript as having said something it never said, and
// every later turn was conditioned on that fiction.
//
// The user still needs to see that something went wrong, so the message stays
// on screen — it just stops being part of what the model is told it said.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAriaStore } from "@/store/ariaStore";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: () => Promise.resolve("t") }),
}));

import { useCognition } from "./useCognition";

const ERROR_TEXT = "I could not process that request.";

beforeEach(() => {
  useAriaStore.setState({ conversationHistory: [] });
});

afterEach(() => {
  vi.unstubAllGlobals();
  useAriaStore.setState({ conversationHistory: [] });
});

function okResponse(body: object) {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  };
}

describe("a failed turn never becomes model-visible history", () => {
  it("still shows the user that the request failed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    const { result } = renderHook(() => useCognition());

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    const shown = useAriaStore.getState().conversationHistory.map((m) => m.content);
    expect(shown).toContain(ERROR_TEXT);
  });

  it("does not replay the placeholder to the model on the next turn", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce(
        okResponse({
          natural_language_response: "Hello again.",
          avatar_emotion: "neutral",
          spatial_event: null,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useCognition());

    await act(async () => {
      await result.current.sendMessage("first");
    });
    await act(async () => {
      await result.current.sendMessage("second");
    });

    const secondCall = fetchMock.mock.calls[1];
    const sent = JSON.parse(secondCall[1].body as string);
    const replayed = (sent.conversation_history as Array<{ content: string }>).map(
      (t) => t.content,
    );

    expect(replayed).not.toContain(ERROR_TEXT);
    // The user's own turns must still be replayed.
    expect(replayed).toContain("first");
  });

  it("keeps replaying genuine assistant answers", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        okResponse({
          natural_language_response: "A real answer.",
          avatar_emotion: "neutral",
          spatial_event: null,
        }),
      )
      .mockResolvedValueOnce(
        okResponse({
          natural_language_response: "Another.",
          avatar_emotion: "neutral",
          spatial_event: null,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useCognition());

    await act(async () => {
      await result.current.sendMessage("one");
    });
    await act(async () => {
      await result.current.sendMessage("two");
    });

    const sent = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    const replayed = (sent.conversation_history as Array<{ content: string }>).map(
      (t) => t.content,
    );
    expect(replayed).toContain("A real answer.");
  });
});
