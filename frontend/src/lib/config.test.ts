import { describe, it, expect } from "vitest";
import {
  COGNITION_REQUEST_TIMEOUT_MS,
  deriveWsUrl,
  deriveAudioWsUrl,
  isBackendMisconfigured,
  backendConfigured,
  API_BASE,
  WS_URL,
  AUDIO_WS_URL,
} from "./config";

describe("deriveWsUrl", () => {
  it("maps http to ws and appends /ws", () => {
    expect(deriveWsUrl("http://localhost:8080")).toBe("ws://localhost:8080/ws");
  });

  it("maps https to wss and appends /ws", () => {
    expect(deriveWsUrl("https://api.example.com")).toBe(
      "wss://api.example.com/ws"
    );
  });

  it("strips trailing slashes before appending /ws", () => {
    expect(deriveWsUrl("http://localhost:8080/")).toBe(
      "ws://localhost:8080/ws"
    );
  });
});

describe("deriveAudioWsUrl", () => {
  it("appends /audio to the base WS URL", () => {
    expect(deriveAudioWsUrl("ws://localhost:8080/ws")).toBe(
      "ws://localhost:8080/ws/audio"
    );
  });

  it("strips trailing slashes before appending /audio", () => {
    expect(deriveAudioWsUrl("wss://api.example.com/ws/")).toBe(
      "wss://api.example.com/ws/audio"
    );
  });
});

describe("isBackendMisconfigured", () => {
  it("treats local http dev with a localhost base as configured", () => {
    expect(isBackendMisconfigured("http://localhost:8080", "http:")).toBe(false);
  });

  it("flags an https origin whose base still points at localhost", () => {
    expect(isBackendMisconfigured("http://localhost:8080", "https:")).toBe(true);
    expect(isBackendMisconfigured("https://localhost:8080", "https:")).toBe(true);
    expect(isBackendMisconfigured("http://127.0.0.1:8080", "https:")).toBe(true);
  });

  it("treats an https origin with a real backend base as configured", () => {
    expect(isBackendMisconfigured("https://api.example.com", "https:")).toBe(false);
  });
});

describe("backendConfigured", () => {
  it("is true in the local (http) test environment", () => {
    expect(backendConfigured).toBe(true);
  });
});

describe("config defaults", () => {
  it("defaults API_BASE to the local Go server", () => {
    expect(API_BASE).toBe("http://localhost:8080");
  });

  it("derives WS_URL from the default API_BASE", () => {
    expect(WS_URL).toBe("ws://localhost:8080/ws");
  });

  it("derives AUDIO_WS_URL as the /ws/audio path on the same host", () => {
    expect(AUDIO_WS_URL).toBe("ws://localhost:8080/ws/audio");
  });
});

describe("COGNITION_REQUEST_TIMEOUT_MS (R6 deadline ordering)", () => {
  // Mirrors backend/internal/cognition UpstreamTimeout. If either side moves,
  // this test fails and forces the whole budget to be re-agreed.
  const GO_UPSTREAM_TIMEOUT_MS = 20000;

  it("is the agreed 25s browser backstop", () => {
    expect(COGNITION_REQUEST_TIMEOUT_MS).toBe(25000);
  });

  it("is strictly the outermost bound, above the Go upstream timeout", () => {
    expect(COGNITION_REQUEST_TIMEOUT_MS).toBeGreaterThan(GO_UPSTREAM_TIMEOUT_MS);
  });
});
