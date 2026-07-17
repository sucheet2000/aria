import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { WS_URL } from "@/lib/config";

const { mockGetToken } = vi.hoisted(() => ({ mockGetToken: vi.fn() }));

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: mockGetToken }),
}));

import { useWebSocket } from "./useWebSocket";

// Minimal WebSocket stand-in that records how it was constructed. The hook only
// reads the static readyState constants and assigns event handlers.
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  url: string;
  protocols?: string | string[];
  readyState = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onclose: ((ev: { code: number; reason: string }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;

  constructor(url: string, protocols?: string | string[]) {
    this.url = url;
    this.protocols = protocols;
    MockWebSocket.instances.push(this);
  }

  send = vi.fn();
  close = vi.fn();
}

describe("useWebSocket subprotocol auth (SEC-1)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    mockGetToken.mockReset();
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("carries the token in the subprotocol, not the URL query string", async () => {
    mockGetToken.mockResolvedValue("jwt.header.token");

    const { unmount } = renderHook(() => useWebSocket());
    await vi.advanceTimersByTimeAsync(1000);

    const ws = MockWebSocket.instances.at(-1);
    expect(ws).toBeDefined();
    expect(ws!.url).toBe(WS_URL);
    expect(ws!.url).not.toContain("token=");
    expect(ws!.protocols).toEqual(["aria-ws", "jwt.header.token"]);

    unmount();
  });

  it("connects without a token subprotocol when no token is available", async () => {
    mockGetToken.mockResolvedValue(null);

    const { unmount } = renderHook(() => useWebSocket());
    await vi.advanceTimersByTimeAsync(1000);

    const ws = MockWebSocket.instances.at(-1);
    expect(ws).toBeDefined();
    expect(ws!.url).toBe(WS_URL);
    expect(ws!.url).not.toContain("token=");
    expect(ws!.protocols).toBeUndefined();

    unmount();
  });
});

describe("useWebSocket frame validation (FE-3)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    mockGetToken.mockReset();
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("logs and drops a malformed frame without leaking payload contents", async () => {
    mockGetToken.mockResolvedValue("jwt.header.token");
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const { unmount } = renderHook(() => useWebSocket());
    await vi.advanceTimersByTimeAsync(1000);

    const ws = MockWebSocket.instances.at(-1);
    expect(ws).toBeDefined();
    expect(ws!.onmessage).toBeTypeOf("function");

    ws!.onmessage!({
      data: JSON.stringify({
        type: "aria_response",
        payload: { transcript: "SECRET_PII_XYZ" },
      }),
    } as MessageEvent);

    expect(warnSpy).toHaveBeenCalled();
    expect(JSON.stringify(warnSpy.mock.calls)).not.toContain("SECRET_PII_XYZ");

    warnSpy.mockRestore();
    unmount();
  });
});
